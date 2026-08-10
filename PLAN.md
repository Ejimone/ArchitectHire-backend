# ArchitectHire — Build Progress Tracker

The single source of truth for what is built, verified, and next across the platform.
Backend repo: `ArchitectHire-backend` (Django 6.1 CMS + marketplace API) · Frontend repo: `Architecture-hire` (Next.js 16, pixel-accurate to `design/`, zero placeholders).

**Product spec**: `design/` — start at `design/documents/Business Wiki.dc.html` and `design/README.md`.

## Locked decisions
- Platform fee: **10% flat**, admin-configurable (`payments.FeePolicy`), snapshotted per engagement.
- Hourly rates: **providers set their own**; admin min/max caps.
- Payments: **Stripe test mode** — PaymentIntents (escrow funding) + Connect Express (payouts); platform-ledger escrow (append-only double-entry).
- Auth: **Clerk** (email + Google) — backend verifies session JWTs via JWKS, JIT-provisions local users, webhooks sync profiles. Django admin stays password-based for the owner.
- Infra: Docker Compose locally → DigitalOcean (managed Postgres/Redis, Spaces + CDN for media).
- Estimate/order pricing: exact formulas from the design prototypes (see backend `apps/projects`/`apps/orders` tests).

## Backend stages

- [x] **Stage 1 — Foundation** *(2026-08-10)*
  Django 6.1 + DRF 3.18 on Python 3.13 (uv-managed) · settings split base/dev/prod (django-environ) · 13-app modular layout started (`core`, `accounts`) · custom email-login `User` (+ Clerk `clerk_id`, roles) at migration zero · `NotificationPreference` auto-created · Clerk JWT authentication class (JWKS/RS256, azp check, JIT provisioning) · page-scope registry · version-key cache utils · DO Spaces storage backends (public/private) · health endpoint (db+redis) · Dockerfile (multi-stage, non-root) + docker-compose (web/worker/beat/postgres17/redis7) · Celery app with in-code beat schedule · ruff + pytest + GitHub Actions CI (Postgres+Redis services).
  **Verified**: 19 tests green · ruff clean · `check --deploy` zero issues · migrations applied on Postgres 17.
  Note: host port **5433** → container Postgres (native Postgres owns 5432 on the dev machine).

- [x] **Stage 2 — Accounts & auth (Clerk)** *(2026-08-10)*
  Clerk webhook `POST /api/webhooks/clerk/` (svix-verified; user.created/updated → upsert + JIT-user linking by email, user.deleted → deactivate) · `GET/PATCH /api/v1/auth/me/` (role self-selection, staff blocked, email read-only) · `GET/PATCH /api/v1/auth/me/preferences/` · OpenAPI bearer scheme for Clerk tokens.
  **Verified**: 32 tests green (signed-webhook simulation incl. bad-signature 400, unconfigured 503) · ruff clean.

- [x] **Stage 3 — CMS foundation** *(2026-08-10)*
  SiteSettings singleton (promo banner, trust bar, hero media Image/Video/Carousel, contact emails) · MediaAsset named slots · NavGroup/NavItem (3 mega-menus, price hints, featured cards) · FooterColumn/Link + SocialLink · HeroCarouselSlide · 10 scoped block types (FAQ/Stat/Step/Testimonial/ValueProp/TrustLogo/CredentialBadge/UseCase/Persona/Principle) with draft/publish + validated page scopes · admin UX pass #1 (inlines, list_editable, publish actions, thumbnails) · composed `GET /api/v1/content/pages/{key}/` + `nav/` `footer/` `settings/` `media/` · Redis payload cache with version-bump invalidation on every CMS save + ETag/304 + CDN-friendly Cache-Control.
  **Verified**: 43 tests green (publish filtering, ordering, cache-bust-on-save, ETag 304 + rotation) · fixed a first-build ETag race (singleton creation bumping version mid-request).

- [x] **Stage 4 — Catalog + jurisdictions + estimate engine** *(2026-08-10)*
  `scripts/extract_seeds.py` parses the design's JS literals → `seeds/*.json` (re-runnable) · State (52 with exact scores + derived band/multiplier/timeline + the design's deterministic factor formula) / City (12) · ServiceCategory (8) / Service (27, stamp-line flagged) / Addon (4) / Plan (2) / ProjectType (9) / RenderDeliverable (5×3 matrix) / DraftingConfig + EstimateConfig singletons (owner-tunable engine constants) · CopyBlock model (every string/button CMS-editable) · idempotent `manage.py seed --all` (also nav 9 groups/40 items + footer 5 cols + 4 socials) · cached endpoints: `catalog/*`, `jurisdictions/states|cities(+detail)` · `POST /api/v1/estimates/` (anonymous, throttled, frozen UUID snapshot + shareable GET).
  **Verified**: 61 tests green incl. exact-value pins (2,400sf CA structural+viz → base $12,750, ×1.337 = $22,662.15 ±8%; ND ×1.1795; rate curve $8.11→$3.44/sf; base rounds to $50) · seed idempotency · seeded API diffs vs design data.

- [ ] **Stage 5 — CMS long tail + full seed**
  Blog (block bodies) · CaseStudy · ProjectType/City/State SEO payloads · Careers · Contact · Policies · Inspiration + likes · PageSEO · search index + endpoint · newsletter · `manage.py seed --all` (zero-placeholder guarantee).

- [x] **Stage 6 — Providers** *(2026-08-10)*
  ArchitectProfile / ExpertProfile (role-aware `me/profile/`, onboarding step tracking → submit → credential review → approved/live, 409 on double-submit) · Discipline taxonomy (6 seeded with licensure/on-site gating flags; `ExpertProfile.requires_license` derives from selected disciplines) · Credential state machine (uploaded → verified/rejected, staff attribution, admin verification queue with bulk verify/reject) · credential docs on the **private** storage alias (filesystem dev / presigned Spaces prod) · portfolio CRUD · Review model + denormalized provider reputation fields · public architect endpoint (live profiles only: portfolio, published reviews, verified-credential list).
  **Verified**: 80 tests green (state machine, role-aware profiles, owner-only credentials, live-only public gating).

- [x] **Stage 7 — Projects, matching, orders** *(2026-08-10)*
  Project lifecycle (choosing_architect → underway → complete; progress %, next action) · estimate claim (`POST projects/ {estimate_id}` — links anonymous estimates to the new account, double-claim blocked) · **matching engine**: hard filters (live + accepting + **licensed in project state** + capacity headroom), scored ranking (specialization/rating/headroom/on-time), capped at 3, tags BEST MATCH/STRONG/HOURLY OPTION with reasons · architect lead inbox + accept/decline with design-faithful undo (409 after hire) · `hire/` sets architect, withdraws other matches · **orders**: render (5×3 matrix ×qty +25% rush) & drafting ($78/hr, $30/sheet, as-built max($2,500,…), +$1,500 stamp, +25% rush on base+stamp) calculators, anonymous quote + checkout with frozen price snapshots, UUID order tracking, my-orders list.
  **Verified**: 96 tests green — exact-value calculator pins, licensure hard-filter, cap-of-3, capacity exclusion, full lead→undo→hire flow.

- [ ] **Stage 8 — Engagements**
  Contract + fee snapshot · milestone state machine · approve/request-changes with markup attachments + undo · requote flags · time entries · deliverables (signed URLs).

- [ ] **Stage 9 — Payments & escrow**
  FeePolicy · double-entry EscrowTransaction ledger · Stripe PaymentIntents + Connect transfers · webhook dedup · payout sweep · balance property tests.

- [ ] **Stage 10 — Messaging & notifications**
  Channels WebSocket consumer (JWT auth) · threads/messages · presence/typing/unread · contact gating until hire · video call scheduling · Web Push (VAPID) + email fallback — updates reach users with the site closed.

- [ ] **Stage 11 — Hardening**
  Security headers · Sentry · structured logging · N+1 audit · OpenAPI complete · cached p95 < 50ms on content endpoints · coverage ≥85% money paths.

- [ ] **Stage 12 — Deployment (DigitalOcean)**
  Managed Postgres/Redis · Spaces + CDN · app spec/runbook · migrate + seed · DNS/TLS · Stripe + Clerk webhooks live.

## Frontend phases (built in `Architecture-hire`, one per backend capability)

- [ ] **F1 — Foundation**: brand tokens (navy `#0a1440`, blue `#135bff`, lime `#ceff65`; Bricolage Grotesque/Hanken Grotesk/IBM Plex Mono), API client, Clerk provider, layout + nav/footer from CMS.
- [ ] **F2 — Marketing pages** (22): Landing → Services → service details → recruiting → SEO templates (ProjectType/City/State) → Blog → Case Studies → About/Careers/Contact/Legal → Inspiration → Search. All content from `content/pages/{key}`.
- [ ] **F3 — Funnel**: Get Started questionnaire + instant estimate + Clerk signup handoff.
- [ ] **F4 — Orders**: render + drafting configurators with live pricing.
- [ ] **F5 — Matches & profiles**.
- [ ] **F6 — Engagement dashboard**: milestones, approvals, escrow, files.
- [ ] **F7 — Accounts**: homeowner + architect + expert portals, onboarding wizards.
- [ ] **F8 — Messaging**: real-time threads, presence, service worker + Web Push.
- [ ] **F9 — SEO & performance pass**: metadata, sitemaps, structured data, ISR, image optimization.

## How to run (backend)

```bash
docker compose up -d db redis     # infra (Postgres on host port 5433)
uv sync                           # install deps
uv run python manage.py migrate
uv run python manage.py runserver # or: docker compose up web worker beat
# health:  http://localhost:8000/api/health/
# docs:    http://localhost:8000/api/docs/
# admin:   http://localhost:8000/admin/
uv run pytest                     # tests
```
