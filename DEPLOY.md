# Deploying ArchitectHire — runbooks

## As deployed (2026-08-11)

| Piece | Where | Notes |
|---|---|---|
| Backend API + admin | DigitalOcean **App Platform** — https://architecthire-wkqzm.ondigitalocean.app | Docker build from `Ejimone/ArchitectHire-backend` `main`, auto-deploys on push. 512MB / 2 gunicorn workers (--workers 2 in the Dockerfile; 4 workers measured 435MB = 85% of the instance under load, 2 measures 230MB = 45%); static manifest baked into the image. **No pre-deploy job** (removed 2026-08-12 to cut cost) — after pushing a change that adds migrations or new seed content, run once from the app console (DO dashboard → app → Console tab, or `doctl apps console 1e7b145c-d082-4355-95f5-b7981a587f38 architecthire-backend`): `python manage.py migrate && python manage.py seed --all`. |
| Frontend | **Vercel** — **https://architecthire.com** (canonical; `www` 308-redirects to it, `architecthire.vercel.app` still works) | Project `architecthire`, GitHub-connected to `Ejimone/Architecture-hire` `main` (push = deploy). Deployment protection disabled (public site). |
| Postgres | Dedicated DO cluster `architecthire-db` (blr1, PG 18, `db-s-1vcpu-1gb`), database `architecthire`, direct port 25060 | App-only firewall. **Must stay in blr1 with the app**: an interim move to Neon (AWS us-east-2) put ~300ms on every query — admin clicks took 5–10s and cold page composes 4.5s. Migrated back 2026-08-14 (99 tables / 2,911 rows verified against the Neon copy, which is left untouched as a fallback). |
| Redis | Dedicated DO Valkey `db-vk-blr1-99253` over TLS (blr1) | Cache/queues/presence. Switched 2026-08-14 from the shared `alsermon` cluster — do not delete `alsermon`; other hobby projects may still use it. |
| Media | Shared Spaces bucket `allsermon-media` (sfo3) | Uploads under `cms/`; consider a dedicated bucket at launch. |

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
