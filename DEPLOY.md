# Deploying ArchitectHire — runbooks

## Target deployment (2026-08-19 →): Oracle Cloud VM + Vercel

| Piece | Where | Notes |
|---|---|---|
| Backend API + admin + WebSockets | **Oracle Cloud VM** (Always-Free tier), `docker-compose.prod.yml` — https://api.architecthire.com | Postgres 18 + Redis 7 + Django (gunicorn/uvicorn workers) + Caddy, all on the box. Deploys are a **`git push origin main`**: a hook on the VM pulls, rebuilds and restarts. **Migrations run inside the web container at start** (`scripts/docker-entrypoint.sh`) — the hook does not run them, and a push that carried a data migration once shipped the code and left the data behind. Only the container whose command is `gunicorn` migrates; the celery containers start from the same image and must not race it. A migration that keeps failing is logged loudly and the server starts anyway, on the schema already there. Manual equivalent: `git pull && dc build web && dc up -d web`. |
| Media | **Still DigitalOcean Spaces as of 2026-08-19** — probed: `GET https://<api-host>/media/cms/slots/landing__hero-arch.webp` 404s while the same path on the bucket 200s, so the running containers have `MEDIA_BACKEND=s3` whatever this repo's compose file says. Target: the VM's disk, `/srv/architecthire/media`, served by Caddy at `https://<api-host>/media/` (`MEDIA_BACKEND=local`) — see "Taking media off Spaces" below | Bind-mounted (never a named volume), nightly `tar` to `/srv/backups`. Private files (deliverables, credential scans) in `/srv/architecthire/media-private`, reachable only through signed 10-minute URLs (`/api/v1/files/?t=…`). |
| Site | **Vercel** — https://architecthire.com | Unchanged. `API_URL` / `NEXT_PUBLIC_API_URL` → `https://api.architecthire.com`, `BACKEND_MEDIA_HOST=api.architecthire.com`. |
| Studio | **Vercel** — https://architecthire-studio.vercel.app (optionally `studio.architecthire.com`) | `STUDIO_API_URL` and `NEXT_PUBLIC_STUDIO_API_URL` → `https://api.architecthire.com`, `NEXT_PUBLIC_SITE_URL=https://architecthire.com`, `BACKEND_MEDIA_HOST=api.architecthire.com`. |

Everything below "As deployed (2026-08-11)" describes the DigitalOcean deployment this
replaced; it is kept for the rollback window and for the history.

### 0. Prerequisites

- An Oracle VM (Ubuntu 22.04/24.04, ARM64 `VM.Standard.A1.Flex` or x86) with a public IP,
  SSH access, and — in the OCI console — the VCN's **security list ingress rules for TCP
  80 and 443** from `0.0.0.0/0`.
- DNS: an `A` record `api.architecthire.com → <VM public IP>` (lower the TTL to 60 s a day
  before cutover). Caddy issues the certificate on first request once the name resolves.
- The current `.env.prod` values from the DigitalOcean app spec (secrets never leave the
  owner's machine — copy them into the VM's `.env.prod` by hand or `scp`).

### 1. Prepare the VM (once)

```bash
ssh ubuntu@<ip>
# Docker CE + compose plugin (official repository)
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg rclone
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update && sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker $USER && newgrp docker

# Oracle's Ubuntu images ship an iptables INPUT chain that REJECTs everything but 22.
# The cloud firewall (security list) is not enough — open 80/443 on the host too:
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 443 -j ACCEPT
sudo apt-get install -y iptables-persistent && sudo netfilter-persistent save

# Directories the containers bind-mount. Owned by uid 999 (the `app` user in the image).
sudo mkdir -p /srv/architecthire/media /srv/architecthire/media-private /srv/backups
sudo chown -R 999:999 /srv/architecthire
```

### 2. Code and configuration

```bash
sudo mkdir -p /srv/architecthire && sudo chown $USER /srv/architecthire
git clone https://github.com/Ejimone/ArchitectHire-backend.git /srv/architecthire/ArchitectHire-backend
cd /srv/architecthire/ArchitectHire-backend
cp .env.prod.example .env.prod && chmod 600 .env.prod
nano .env.prod          # every value; see the example file for what each is
alias dc='docker compose --env-file .env.prod -f docker-compose.prod.yml'
```

### 3. Build, restore the data, start

```bash
dc build
dc up -d db redis

# --- Data: bring the DigitalOcean database across (PG 18 → PG 18) -----------------
# On the laptop (pg_dump 18 client; the DO URL needs ?sslmode=require):
#   pg_dump "$DO_DATABASE_URL" -Fc --no-owner --no-acl -f architecthire.dump
#   scp architecthire.dump ubuntu@<ip>:/tmp/
dc exec -T db pg_restore -U architecthire -d architecthire --no-owner --no-acl < /tmp/architecthire.dump
dc run --rm web python manage.py migrate         # applies anything newer than the dump
dc run --rm web python manage.py showmigrations | grep -c '\[X\]'

# --- Media: copy the Spaces bucket onto the disk (storage names are unchanged) ----
rclone config    # new remote "spaces": type s3, provider DigitalOcean, the bucket's keys,
                 # endpoint sfo3.digitaloceanspaces.com
rclone sync spaces:allsermon-media/media /srv/architecthire/media -P
sudo chown -R 999:999 /srv/architecthire/media
dc run --rm web python manage.py sync_media_slots  # inventory rows for anything new

dc up -d                                          # web + caddy
dc ps
```

### 4. Verify, then point the world at it

```bash
curl -s https://api.architecthire.com/healthz             # {"status":"ok"} db=ok cache=ok
curl -s https://api.architecthire.com/api/health/         # 200
curl -sI https://api.architecthire.com/media/cms/slots/landing__hero-arch.webp | head -1   # 200
curl -s https://api.architecthire.com/api/v1/content/pages/landing/ | head -c 300
```

Then, in this order:

1. **Vercel — site** (`vercel env` or the dashboard): `API_URL`, `NEXT_PUBLIC_API_URL` →
   `https://api.architecthire.com`; `BACKEND_MEDIA_HOST=api.architecthire.com`. Redeploy
   (`NEXT_PUBLIC_*` are baked at build).
2. **Vercel — studio**: `STUDIO_API_URL`, `NEXT_PUBLIC_STUDIO_API_URL` →
   `https://api.architecthire.com`; `NEXT_PUBLIC_SITE_URL=https://architecthire.com`;
   `BACKEND_MEDIA_HOST=api.architecthire.com`. Redeploy.
3. **Clerk** dashboard → Webhooks → edit the endpoint URL to
   `https://api.architecthire.com/api/webhooks/clerk/` (editing keeps the signing secret).
4. **Stripe** dashboard → Developers → Webhooks → add
   `https://api.architecthire.com/api/webhooks/stripe/` (a new endpoint has a new signing
   secret → `STRIPE_WEBHOOK_SECRET` in `.env.prod` → `dc up -d --force-recreate web`).
5. Vercel Cron already targets `API_URL`; nothing to change.

### 5. Day-2

| Task | Command |
|---|---|
| Deploy a change | `git pull && dc build web && dc run --rm web python manage.py migrate && dc up -d web` |
| After editing `.env.prod` | `dc up -d --force-recreate web` (a plain restart does not re-read the file) |
| Logs | `dc logs -f web` / `dc logs -f caddy` |
| Django shell | `dc exec web python manage.py shell` |
| Postgres shell | `dc exec db psql -U architecthire` |
| Backup (add to `crontab -e`, nightly) | `cd /srv/architecthire/ArchitectHire-backend && dc exec -T db pg_dump -U architecthire -Fc architecthire > /srv/backups/db-$(date +%F).dump && tar czf /srv/backups/media-$(date +%F).tgz -C /srv/architecthire media media-private && find /srv/backups -mtime +7 -delete` |
| Rollback to DigitalOcean (kept running for the soak week) | Flip the Vercel envs back, `dc down`; re-dump the VM's Postgres into DO if any writes happened in between |

Health: `/healthz` is answered by asgi.py before Django and reflects the DB pool and Redis;
Docker's own healthcheck polls it. Sizing: `WEB_CONCURRENCY` workers × ~150 MB; the
Always-Free A1 (24 GB) is comfortable at 4–8.

### 6. Taking media off DigitalOcean Spaces

The running containers still store media in the bucket (probed 2026-08-19: `GET
https://<api-host>/media/cms/slots/landing__hero-arch.webp` 404s while the same path on
the bucket 200s). Moving it onto the VM's disk is what lets the Spaces bill stop; Caddy
already serves `/media/*` from `/srv/architecthire/media`, and the compose file already
bind-mounts it.

**The database stores names, not URLs** — `cms/case-cards/adu-3.webp` — and the public URL
is built from `MEDIA_URL` when a page renders. So a byte-for-byte copy under the same
names *is* the whole migration: no rows change, no links are rewritten, and the rollback
is one variable.

```bash
cd /srv/architecthire/ArchitectHire-backend
alias dc='docker compose --env-file .env.prod -f docker-compose.prod.yml'

# 1. Copy, while the site is still serving from the bucket. Nothing changes for anyone;
#    safe to run as many times as you like — it skips what is already there.
dc run --rm web python manage.py copy_media_local --dry-run   # what would move
dc run --rm web python manage.py copy_media_local

# 2. Flip the switch. MEDIA_URL must be absolute and end in a slash: the two Vercel
#    projects allowlist images by hostname.
printf 'MEDIA_BACKEND=local\nMEDIA_URL=https://<api-host>/media/\n' >> .env.prod
dc up -d --force-recreate web        # a plain restart does not re-read .env.prod

# 3. Verify before touching the bucket.
curl -sI https://<api-host>/media/cms/slots/landing__hero-arch.webp | head -1   # 200
```

Then set `BACKEND_MEDIA_HOST=<api-host>` on both Vercel projects and redeploy them
(`NEXT_PUBLIC_*` and the image allowlist are baked at build time). **Keep the Spaces host
in both allowlists for one release** as a safety net, and only cancel the bucket after a
week of the site serving its own images.

Rollback is `MEDIA_BACKEND=s3` and `dc up -d --force-recreate web`: the objects are still
in the bucket, because the copy only ever reads from it.

---

## As deployed (2026-08-11) — DigitalOcean (superseded, kept for rollback)

| Piece | Where | Notes |
|---|---|---|
| Backend API + admin | DigitalOcean **App Platform** — https://architecthire-wkqzm.ondigitalocean.app | Docker build from `Ejimone/ArchitectHire-backend` `main`, auto-deploys on push. **1GB / 6 gunicorn workers** (2026-08-15; Django runs sync views on one thread per uvicorn worker, so workers = concurrent HTTP requests — 2 workers meant the whole app served 2 at a time and site rebuilds took it down). **HTTP health checks must point at `/healthz`** (answered in asgi.py before Django) — `/api/health/` fails the platform prober on ALLOWED_HOSTS and queues behind the sync thread; a check aimed there killed healthy containers. **No pre-deploy job** (removed 2026-08-12 to cut cost) — after pushing a change that adds migrations or new seed content, run once from the app console (DO dashboard → app → Console tab, or `doctl apps console 1e7b145c-d082-4355-95f5-b7981a587f38 architecthire-backend`): `python manage.py migrate && python manage.py seed --all`. |
| Frontend | **Vercel** — **https://architecthire.com** (canonical; `www` 308-redirects to it, `architecthire.vercel.app` still works) | Project `architecthire`, GitHub-connected to `Ejimone/Architecture-hire` `main` (push = deploy). Deployment protection disabled (public site). |
| Postgres | Dedicated DO cluster `architecthire-db` (blr1, PG 18, `db-s-1vcpu-1gb`), database `architecthire`, direct port 25060 | App-only firewall. **Must stay in blr1 with the app**: an interim move to Neon (AWS us-east-2) put ~300ms on every query — admin clicks took 5–10s and cold page composes 4.5s. Migrated back 2026-08-14 (99 tables / 2,911 rows verified against the Neon copy, which is left untouched as a fallback). |
| Redis | Shared DO Valkey `alsermon` over TLS (blr1) | Cache/queues/presence; keys prefixed `ah`. Switched back from the short-lived dedicated `db-vk-blr1-99253` on 2026-08-15 (owner's call — one shared cluster, one bill); that dedicated cluster is now unused and safe to delete. |
| Media | Shared Spaces bucket `allsermon-media` (sfo3) | `AWS_*` env set in the app spec 2026-08-15 so uploads persist in Spaces rather than the container's ephemeral disk. |

Config changes: backend env lives in the **App Platform app spec** (edit in the DO
dashboard or `doctl apps update`), frontend env in **Vercel project settings**
(`NEXT_PUBLIC_*` are baked at build — redeploy after changing them). Every
test-mode key to swap at launch is marked [LIVE-SWAP] below.

**Instant admin→site sync (added 2026-08-12):** every backend content save POSTs to
`https://architecthire.com/api/revalidate` (shared `REVALIDATE_SECRET`, set in both the
app spec and Vercel), which purges the frontend's cached pages immediately; the 60s ISR
cycle stays as a fallback. If edits ever stop appearing instantly, check that both env
values still match — a rejected ping is now logged at ERROR instead of being swallowed,
so look for `Frontend rejected revalidation: HTTP 401` in the backend logs first.

**No Celery worker, by design (2026-08-14).** Notifications and revalidation pings run on
an in-process thread pool (`apps/core/background.py`), dispatched once the transaction
commits. App Platform has no worker component, so anything handed to `.delay()` is queued
into Redis and never consumed — which is precisely how every notification and every cache
purge silently went missing before this change. Set `NOTIFY_VIA_CELERY=1` only in an
environment that genuinely runs a worker.

**Scheduled jobs run off Vercel Cron**, since there is no beat process either. Vercel
calls `https://architecthire.com/api/cron/<job>`, which re-signs the request as
`x-cron-secret` and forwards it to `POST /api/v1/internal/cron/<job>/`.

| Env var | Where | Notes |
|---|---|---|
| `CRON_SECRET` | DO app spec **and** Vercel | One random ≥16-char value, identical in both. Blank on the backend = 503, and nothing is ever swept. |
| `REVALIDATE_DEBOUNCE_SECONDS` | DO app spec (optional) | Defaults to 0.5. How long writes accumulate before one purge is sent. |

The Vercel project is on the **Hobby** plan, which permits two cron jobs firing at most
once a day — so `vercel.json` schedules a single `daily` invocation that dispatches all
three jobs (`rebuild-search-index`, `sweep-pending-payouts`, `cleanup-stale-data`) as
independent background jobs. On Pro, point `vercel.json` at the individual job names and
give the payout sweep back its hourly cadence; the endpoint already accepts them. Any job
can be triggered by hand:

```
curl -X POST -H "x-cron-secret: $CRON_SECRET" \
  https://architecthire-wkqzm.ondigitalocean.app/api/v1/internal/cron/sweep-pending-payouts/
```

---

# Alternative: single-droplet runbook (kept for reference)

One droplet runs everything: Django (web + Celery worker + beat), Next.js,
Redis, and Caddy for automatic HTTPS. **Postgres is your existing shared
managed cluster** — this deploy adds a database inside it, not a new cluster.

You are deploying in **test mode** with the current Clerk/Stripe test keys.
Every value to swap at real launch is marked `[LIVE-SWAP]` in `.env.prod`;
the switch checklist is at the bottom.

---

## 0. What you need before starting

- Your DigitalOcean account (droplet limit confirmed OK).
- The connection details of your shared Postgres cluster (host, port —
  usually `25060` — and an admin login), from *Databases → your cluster →
  Connection details* in the DO dashboard.
- Both repos pushed somewhere the droplet can pull them from, **or** willingness
  to `rsync` them up (step 3 shows both).

## 1. Create the droplet

Dashboard → *Create → Droplet*:

- **Image**: Ubuntu 24.04 LTS
- **Size**: Basic → Regular → **4 GB RAM / 2 vCPU ($24/mo)**. The frontend
  Docker build needs the RAM; 2 GB will OOM during `pnpm build`.
- **Region**: same region as your Postgres cluster (keeps DB latency ~1ms).
- **Auth**: your SSH key.

Note the droplet's public IP. With no domain yet, your site host is the
sslip.io form of it: IP `203.0.113.9` → `203-0-113-9.sslip.io` (dashes, not
dots). HTTPS works on that automatically — no DNS setup.

```bash
ssh root@<droplet-ip>
apt-get update && apt-get install -y docker.io docker-compose-v2 rsync
```

## 2. Create the app's database in your shared cluster

Dashboard → *Databases → your cluster*:

1. **Users & Databases** tab → add database `architecthire` and user
   `architecthire` (copy the generated password).
2. **Settings → Trusted sources** → add the new droplet. This is the step
   everyone forgets — without it every connection is refused.

Your `DATABASE_URL` is then:

```
postgres://architecthire:<password>@<cluster-host>:25060/architecthire?sslmode=require
```

Keep `?sslmode=require` — DO managed Postgres refuses plain connections.

## 3. Put the code on the droplet

Either clone (after you push) — or rsync straight from your Mac:

```bash
# from your Mac
rsync -az --exclude .venv --exclude node_modules --exclude .next --exclude media \
  ~/ArchitectHire-backend/ root@<droplet-ip>:/srv/architecthire/ArchitectHire-backend/
rsync -az --exclude node_modules --exclude .next \
  ~/Architecture-hire/ root@<droplet-ip>:/srv/architecthire/Architecture-hire/
```

The two directories **must** sit side by side — the prod compose file builds
the frontend from `../Architecture-hire`.

`.env.prod` is git-ignored, so if you cloned instead of rsyncing, copy it up
separately: `scp ~/ArchitectHire-backend/.env.prod root@<ip>:/srv/architecthire/ArchitectHire-backend/`

## 4. Fill the two blanks in `.env.prod`

On the droplet, edit `/srv/architecthire/ArchitectHire-backend/.env.prod`:

- `SITE_HOST=` → your sslip.io host (or your real domain).
- `DATABASE_URL=` → the connection string from step 2.

Everything else is already filled from your current test-mode setup.

## 5. Build, migrate, seed, start

```bash
cd /srv/architecthire/ArchitectHire-backend
set -a && source .env.prod && set +a     # compose interpolates SITE_HOST etc.

docker compose -f docker-compose.prod.yml build web
docker compose -f docker-compose.prod.yml up -d redis web   # backend first —
docker compose -f docker-compose.prod.yml run --rm web python manage.py migrate
docker compose -f docker-compose.prod.yml run --rm web python manage.py seed --all
docker compose -f docker-compose.prod.yml run --rm web python manage.py collectstatic --noinput

# — because the frontend build prerenders 115 pages against the live API:
docker compose -f docker-compose.prod.yml build frontend
docker compose -f docker-compose.prod.yml up -d
```

Create your admin login:

```bash
docker compose -f docker-compose.prod.yml run --rm web python manage.py createsuperuser
```

## 6. Point the outside world at it

- **Clerk** (dashboard → your test instance):
  - *Webhooks* → add endpoint `https://<SITE_HOST>/api/webhooks/clerk/`,
    subscribe to `user.created`, `user.updated`, `user.deleted`; paste the
    signing secret into `.env.prod` as `CLERK_WEBHOOK_SIGNING_SECRET` and
    `docker compose -f docker-compose.prod.yml up -d --force-recreate web`.
    (Env changes always need recreate, not restart.)
- **Stripe**: nothing — empty keys run the mock gateway. When you add test or
  live keys, also add webhook `https://<SITE_HOST>/api/webhooks/stripe/`.

## 7. Verify

```bash
curl -s https://<SITE_HOST>/api/health/          # {"status": "ok", ...}
curl -s -o /dev/null -w '%{http_code}\n' https://<SITE_HOST>/            # 200
curl -s -o /dev/null -w '%{http_code}\n' https://<SITE_HOST>/get-started # 200
curl -s -o /dev/null -w '%{http_code}\n' https://<SITE_HOST>/account     # 307 → sign-in
```

Then in a browser: sign up, land on the home page, run the quiz, open
`https://<SITE_HOST>/admin/` and change a headline — it should appear on the
site within a minute (production ISR is 60s).

## Day-2 operations

| Task | Command (from `/srv/architecthire/ArchitectHire-backend`) |
|---|---|
| Deploy new code | rsync again, then `docker compose -f docker-compose.prod.yml build && docker compose -f docker-compose.prod.yml up -d` |
| After editing `.env.prod` | `up -d --force-recreate web worker beat` (restart is NOT enough) |
| Logs | `docker compose -f docker-compose.prod.yml logs -f web` (or `frontend`, `caddy`, `worker`) |
| Django shell | `run --rm web python manage.py shell` |
| DB backup | your shared cluster's DO automatic backups already cover it |

## Attaching a real domain later

1. DNS `A` record: `yourdomain.com` → droplet IP.
2. `.env.prod`: `SITE_HOST=yourdomain.com` (and the derived lines pick it up).
3. `docker compose -f docker-compose.prod.yml build frontend && docker compose -f docker-compose.prod.yml up -d --force-recreate`
   (the frontend bakes its public URL at build time). Caddy issues the
   certificate automatically once DNS resolves.
4. Clerk dashboard → update the webhook URL.

## [LIVE-SWAP] Switching to production keys

1. **Clerk**: create the production instance, attach your domain, then swap
   `CLERK_SECRET_KEY`, `CLERK_PUBLISHABLE_KEY` (both spellings in `.env.prod`),
   `CLERK_JWKS_URL`, `CLERK_ISSUER`, and re-add the webhook + signing secret.
2. **Stripe**: live keys + live webhook secret; create the three subscription
   plan Prices and put their ids on the `SubscriptionPlan` rows in admin
   (`gateway_price_id`).
3. **Email**: swap `EMAIL_BACKEND` to SMTP with real credentials.
4. **Spaces** (recommended at launch): create the bucket, fill the `AWS_*`
   block, rerun `collectstatic`, re-upload any droplet-local media.
5. Rebuild + force-recreate everything:
   `docker compose -f docker-compose.prod.yml build && docker compose -f docker-compose.prod.yml up -d --force-recreate`
