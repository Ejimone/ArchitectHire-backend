# ArchitectHire — Backend

CMS-driven marketplace API: Django 6.1 · DRF 3.18 · Channels 4.3 · Celery 5.6 · PostgreSQL 17 · Redis 7 · Python 3.13 (uv-managed).

Every string, price, image, and section on the marketing site is owner-editable in Django admin and served through cached, composed content endpoints. The marketplace side covers estimates → matching → engagements → milestone escrow (Stripe) → payouts, plus real-time messaging with Web Push.

**Build status & stage history:** see [PLAN.md](PLAN.md). **Product spec:** `design/` (start at `design/documents/Business Wiki.dc.html`).

## Local development

```bash
docker compose up -d db redis        # Postgres on host port 5433, Redis on 6380
uv sync                              # install dependencies
cp .env.example .env                 # then fill in what you have (see below)
uv run python manage.py migrate
uv run python manage.py seed --all   # loads the design's exact content
uv run python manage.py createsuperuser
uv run uvicorn architecture_backend.asgi:application --reload   # HTTP + WebSockets
```

- Health: http://localhost:8000/api/health/ · Docs: http://localhost:8000/api/docs/ · Admin: http://localhost:8000/admin/
- Tests: `uv run pytest` · Lint: `uv run ruff check . && uv run ruff format --check .`
- Full stack in Docker instead: `docker compose up` (web + worker + beat + db + redis).
- Re-extract seed JSON after design changes: `uv run python scripts/extract_seeds.py`.

#
> **After editing `.env`, recreate the containers — don't restart them.**
> `env_file` is read when a container is *created*, so `docker compose restart`
> keeps the old environment. Use `docker compose up -d --force-recreate web worker beat`.
> Symptom if you forget: Clerk-authenticated API calls return 401 because
> `CLERK_JWKS_URL` is empty inside the container, and the auth class falls back
> to treating every request as anonymous.

## Integrations (all optional locally — mock fallbacks are built in)

| Service | Env vars | Without them |
|---|---|---|
| Clerk (auth) | `CLERK_JWKS_URL`, `CLERK_ISSUER`, `CLERK_SECRET_KEY`, `CLERK_WEBHOOK_SIGNING_SECRET` | API is anonymous-only; admin login still works |
| Stripe (money) | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | MockGateway: escrow settles instantly, payouts verify instantly |
| Web Push | `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (generate: `uv run python -c "from apps.notifications.vapid import generate; generate()"`) | Falls back to email (console backend in dev) |
| DO Spaces (media) | `AWS_*` vars | Local filesystem storage |

## Deployment (DigitalOcean)

1. **Provision**: managed Postgres + managed Redis (or the containers in `docker-compose.prod.yml`), a Spaces bucket (+ CDN) for media, and a droplet or App Platform app.
2. **Env**: copy `.env.example` → `.env.prod` and fill every value — real `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `DATABASE_URL`, `REDIS_URL`, SMTP email vars, Clerk keys, Stripe live/test keys, Spaces credentials, `SENTRY_DSN`, `FRONTEND_URL`/`CORS_ALLOWED_ORIGINS`.
3. **Release**:
   ```bash
   docker compose -f docker-compose.prod.yml build
   docker compose -f docker-compose.prod.yml run --rm web python manage.py migrate
   docker compose -f docker-compose.prod.yml run --rm web python manage.py seed --all   # idempotent
   docker compose -f docker-compose.prod.yml run --rm web python manage.py collectstatic --noinput
   docker compose -f docker-compose.prod.yml up -d
   ```
4. **Webhooks**: point Clerk → `https://<api-domain>/api/webhooks/clerk/` (user.created/updated/deleted) and Stripe → `https://<api-domain>/api/webhooks/stripe/` (payment_intent.succeeded, account.updated).
5. **Verify**: `/api/health/` returns `{"status": "ok"}`; `manage.py check --deploy` is clean; admin loads; the frontend renders CMS content.

## Architecture at a glance

13 apps under `apps/`: `core` (mixins, scope registry, cache versioning, storages) · `accounts` (Clerk auth, users) · `cms` (all site content + composed page endpoints) · `catalog` (services, pricing configs) · `jurisdictions` (52-state complexity database) · `projects` (estimates, matching) · `orders` (render/drafting checkout) · `engagements` (contracts, milestones) · `payments` (escrow ledger, Stripe) · `messaging` (threads + WebSockets) · `notifications` (in-app + Web Push + email) · `search` · plus Celery beat jobs (search reindex, payout sweep, cleanup).

Key invariants: content endpoints are cached with version-bump invalidation (any admin save busts instantly); the escrow ledger is append-only double-entry (every event balances); platform fee is snapshotted per engagement; stamped work only matches architects licensed in the project's state; contact details are redacted in messages until hire.
