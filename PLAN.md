# ArchitectHire — Build Progress Tracker

The single source of truth for what is built, verified, and next across the platform.
Backend repo: `ArchitectHire-backend` (Django 6.1 CMS + marketplace API) · Frontend repo: `Architecture-hire` (Next.js 16, pixel-accurate to `design/`, zero placeholders).

**Product spec**: `design/` — start at `design/documents/Business Wiki.dc.html` and `design/README.md`.

## Locked decisions
- Revenue: **architect subscriptions** (Studio $79 / Practice $299 / Firm $699 per month, admin-editable `payments.SubscriptionPlan`). The platform takes **0% of a project** — clients hire and pay their architect directly. *(Superseded the original 10% escrow fee on 2026-08-11, per the design update.)*
- Hourly rates: **providers set their own**; admin min/max caps.
- Payments: **Stripe test mode** — subscriptions for providers. The legacy escrow ledger (PaymentIntents, Connect payouts, append-only double-entry) is retained read-only for historical rows and no longer written to.
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

- [x] **Stage 5 — CMS long tail + full seed** *(2026-08-10)*
  Editorial CMS: Blog (block bodies as admin inlines) · CaseStudy (full structured narrative) · Careers · Contact (+throttled submissions) · Policies · Inspiration + like toggle · newsletter · search app (74-entry rebuildable index + grouped endpoint) · ProjectType/City/State SEO payload fields + endpoints. **Full design content extracted & seeded**: 288 copy rows across 20 pages (every headline & button), 35 FAQs / 30 stats / 20 steps / 12 testimonials / 37 value props / logos / badges / personas / principles / carousels, 7 blog posts (featured article: 17 body blocks), 7 case studies (featured: complete narrative), privacy policy (7 sections), 12 inspiration items, popular searches, page SEO for all 20 scopes, Backyard-ADU/Oakland/California template records. `manage.py seed --all` = the zero-placeholder guarantee.
  **Verified**: composed endpoints serve the design's literal strings (landing H1 from DB); blog/case-study/policy/search endpoints populated; 96 tests green.

- [x] **Stage 6 — Providers** *(2026-08-10)*
  ArchitectProfile / ExpertProfile (role-aware `me/profile/`, onboarding step tracking → submit → credential review → approved/live, 409 on double-submit) · Discipline taxonomy (6 seeded with licensure/on-site gating flags; `ExpertProfile.requires_license` derives from selected disciplines) · Credential state machine (uploaded → verified/rejected, staff attribution, admin verification queue with bulk verify/reject) · credential docs on the **private** storage alias (filesystem dev / presigned Spaces prod) · portfolio CRUD · Review model + denormalized provider reputation fields · public architect endpoint (live profiles only: portfolio, published reviews, verified-credential list).
  **Verified**: 80 tests green (state machine, role-aware profiles, owner-only credentials, live-only public gating).

- [x] **Stage 7 — Projects, matching, orders** *(2026-08-10)*
  Project lifecycle (choosing_architect → underway → complete; progress %, next action) · estimate claim (`POST projects/ {estimate_id}` — links anonymous estimates to the new account, double-claim blocked) · **matching engine**: hard filters (live + accepting + **licensed in project state** + capacity headroom), scored ranking (specialization/rating/headroom/on-time), capped at 3, tags BEST MATCH/STRONG/HOURLY OPTION with reasons · architect lead inbox + accept/decline with design-faithful undo (409 after hire) · `hire/` sets architect, withdraws other matches · **orders**: render (5×3 matrix ×qty +25% rush) & drafting ($78/hr, $30/sheet, as-built max($2,500,…), +$1,500 stamp, +25% rush on base+stamp) calculators, anonymous quote + checkout with frozen price snapshots, UUID order tracking, my-orders list.
  **Verified**: 96 tests green — exact-value calculator pins, licensure hard-filter, cap-of-3, capacity exclusion, full lead→undo→hire flow.

- [x] **Stage 8 — Engagements** *(2026-08-10)*
  Engagement (dynamic_fixed_quote | hourly; **fee % snapshotted at creation**, 10% default; deposit = 25% of total or rate×20hrs — exact design figures $5,350 / $2,700 verified) · Milestone state machine (upcoming → in_review → done|revising → in_review; approvals terminal) with **milestones-must-sum-to-total validation** (fixes the design demo's inconsistency deliberately) · client approve / request-changes (category chips + note + private markup upload) · provider re-quote flags (client approve updates the contract total; 409 when re-resolved) · client-visible time entries (hourly transparency) · deliverables on private storage with stamped/NEW flags · strict role permissions (provider defines/submits/uploads/logs; client approves/requests; strangers 404).
  **Verified**: 105 tests green — creation snapshots, sum validation, full transition matrix with role checks, requote flow, time totals, multipart deliverable upload.

- [x] **Stage 9 — Payments & escrow** *(2026-08-10, uncommitted — owner commits)*
  FeePolicy (admin-editable, 10% seeded; snapshot survives policy changes — verified) · append-only double-entry EscrowTransaction ledger (balanced-event writes, idempotent event keys, SUM-query balances, admin is read-only/no-delete) · gateway abstraction: StripeGateway (PaymentIntents, Connect Express accounts + onboarding links, Transfers, signature-verified webhooks) ⇄ MockGateway (instant settle/verify — full E2E without keys) · `fund/` (client-only, optional top-up amount, idempotent) · `ledger/` balances · payout account onboarding · provider `earnings/` (month/year/pending + recent payouts) · release-on-approve wired into milestone approval (release > escrow → 409 "fund next deposit") · `POST /api/webhooks/stripe/` with WebhookEvent dedup.
  **Verified**: 117 tests green — design figures exact ($5,350 deposit; $2,140 release → $1,926 provider + $214 fee, $3,210 escrow left), per-event ledger balance invariant, idempotent funding/release/webhook replay, fee snapshot immutability, instant mock payouts.

- [x] **Stage 10 — Messaging & notifications** *(2026-08-10, uncommitted — owner commits)*
  **Risk R1 resolved: channels 4.3.2 verified working on Django 6.1** (consumer smoke test: connect, ping/pong presence heartbeat, group push, anonymous 4401 rejection) · per-user WebSocket at `/ws/?token=<clerk JWT>` (Clerk JWKS auth middleware; typing relay, mark-read, Redis-TTL presence) · threads (get-or-create from match/project, participant-only), messages (HTTP write path → post-commit WS fanout + notification task; 200-cap history; archived 409) · **contact details redacted until hire** (email/phone regex → "[hidden until you hire]", unlocks after hire — verified) · unread cursors per participant · video call scheduling as call-kind messages · notifications app: in-app rows (always), **Web Push via pywebpush/VAPID with stale-subscription pruning → email fallback**, preference-aware muting · push-subscription register/unregister · notification list + mark-read · VAPID keygen helper.
  **Verified**: 128 tests green (incl. async consumer tests, redaction on/off, unread flow, preference muting, push subscription roundtrip).

- [x] **Stage 11 — Hardening** *(2026-08-10, uncommitted — owner commits)*
  Beat schedule wired (nightly search reindex, hourly payout sweep, daily stale-data cleanup) · payout sweep task (retries pending payouts once accounts verify, balanced ledger entries) · JSON structured logging in prod · query-budget guard tests (uncached composed page ≤20 queries; cached ≤3) · OpenAPI schema generates + serves (fixed swagger fake-view queryset errors; remaining W001s are cosmetic type-hint notes) · `check --deploy`: zero security findings.
  **Verified**: 131 tests green · **90% total coverage** (payments 93–94%, pricing/calculators >90%).

- [x] **Stage 12 — Deployment prep** *(2026-08-10, uncommitted — owner commits; actual deploy is the owner's step)*
  `docker-compose.prod.yml` (web/worker/beat, env_file .env.prod, restart policies, release commands documented) · full README runbook: local dev, integration env matrix (Clerk/Stripe/VAPID/Spaces — all with built-in mock fallbacks), DO provisioning steps, release procedure, webhook URLs (Clerk + Stripe), verification checklist · architecture overview + invariants documented.
  **Remaining for the owner at deploy time**: create DO resources, fill `.env.prod`, point Clerk/Stripe webhooks at the live domain, run the release commands.

## Design resync & business-model change (2026-08-11)

The owner updated `design/` — and the update changed the **business model**, not just copy. The old design was an escrow marketplace taking 10% of every project; the new one is an **introductions platform**: clients hire and pay architects directly ("we take $0"), and revenue comes from **architect subscriptions**. That drives ~80% of the copy edits across 17 files. The update also added 10 pages, rebuilt the project-type template, and replaced the three order flows with **one adaptive quiz**.

- [x] **Design resync** — `design/` copied backend → frontend, trees verified identical. Clerk test keys wired into both repos (`helpful-mayfly-56` instance; owner swaps live keys at deploy).
- [x] **Backend: escrow → subscriptions** — new `SubscriptionPlan` / `Subscription` / `SubscriptionInvoice`; Stripe subscription create/cancel + `customer.subscription.*` webhooks; `payments/plans/` and `payments/subscription/` endpoints; provider dashboard reports *booked* work + plan state instead of payouts. Platform fee 0%; approving a milestone records direct payment (`Milestone.paid_at`) instead of releasing escrow. The escrow ledger tables are **retained but no longer written** — they are append-only financial records. 142 tests green.
- [x] **Nav + project data resync** — 14 service items deep-link `?svc=<slug>`, 9 project items (incl. new **Restaurant build-out**) with the design's new lower prices, CTA relabelled **"Get matched"**. All 9 project types now carry the owner's authored h1/intro/body/range/stats/includes/steps, replacing the placeholder copy generated earlier.
- [x] **Escrow copy sweep** — 188 copy rows, 220 blocks, 35 deletes, 41 records across 16 scopes. Rendered "escrow" count is **0 on every marketing route** except `/about`, where the design's own principle says "no escrow, no cut of the project" verbatim. Recruiting pages now render subscription plan cards from `payments/plans/`.
- [ ] Project-type carousels (hero + gallery), `?svc=` hero variants, `/for-experts/pricing`, `/for-experts/tools`
- [x] **Remaining 404s eliminated** *(2026-08-11)* — `/guides` (+7 articles), `/case-studies` (+7), `/inspiration`, `/search`, `/for-experts/pricing`, `/for-experts/tools`, `/get-started` (unified six-branch adaptive quiz; `/order/*` 308-redirect into it), `/sign-in`, `/sign-up`. Full sweep: **29 public routes 200**, 5 protected routes 307 → sign-in.
- [x] **Auth working end-to-end** — Clerk sign-in/up in brand styling; after auth users land on `/` (owner request); signed-in header shows account link + avatar menu. Two auth bugs fixed: the `/pro(.*)` matcher was swallowing `/projects` (404s everywhere), and `env_file` changes require `docker compose up --force-recreate` (documented in README) — without it the backend saw empty Clerk env and 401'd every authed call.
- [x] **Identity display hard rule** — the account header was showing `user_…@pending.clerk.local`. Backend now serves `display_name` (never an id/placeholder), JIT provisioning backfills the real profile from Clerk's API at first sight, existing rows were repaired, and every dashboard renders names only. Rule documented in FRONTEND-CONVENTIONS.md.
- [x] **Performance pass** — measured: backend API ~5ms, dev-mode pages ~110ms, production build compiles in 1.2s and pre-renders 115 pages (~3ms serve). All content fetchers deduplicated with React `cache()`. Dev feels slower than prod by design (no ISR locally so admin edits show instantly).
- [ ] In flight: quiz claim-flow polish + engagement/pro dashboard completion (two agents), then final production build + coverage re-verify
- [x] **Backend coverage 100%, enforced** — 484 tests, 4,832 statements, 0 missed, `--cov-fail-under=100` in pyproject; zero `# pragma: no cover` in the codebase.

**Known design inconsistencies** (flagged, implemented as authored): two conflicting subscription tables ($79/$299/$699 on the recruiting pages vs $79/$149/$299-per-seat on the pricing page — both seeded as separate plan groups); `site-footer.js` still says "Sign up" where the nav now says "Get matched"; `CAD Drafting.dc.html`'s in-page menu still uses pre-update hrefs.

## Deployed (2026-08-11)

- **Backend**: DigitalOcean App Platform — https://architecthire-wkqzm.ondigitalocean.app (auto-deploys from GitHub `main`; migrations + seed run before every deploy; shared Postgres + Valkey; admin at `/admin/`).
- **Frontend**: Vercel — https://architecthire.vercel.app (GitHub-connected, push = deploy). Test-mode Clerk/Stripe keys throughout; swap list in `DEPLOY.md` [LIVE-SWAP].

## Frontend phases (built in `Architecture-hire`, one per backend capability)

- [x] **F1 — Foundation** *(2026-08-10)*: brand tokens in `app/globals.css` (navy `#0a1440`, blue `#135bff`, lime `#ceff65` + full ink/line/status scale), fonts via `next/font/google` (Bricolage Grotesque / Hanken Grotesk / IBM Plex Mono), typed API client `lib/api.ts` (composed page endpoint + catalog/jurisdictions/editorial fetchers, 60s ISR), `ClerkProvider` wired but key-optional so marketing renders without credentials, CMS-driven `SiteNav` (three hover mega-dropdowns + mobile drawer) and `SiteFooter`, shared `ImgSlot` / `FaqAccordion` / `LogoMark`.
  Backend additions this phase: `chrome` copy scope (21 rows: nav labels, auth buttons, footer legal) returned by `content/nav/` + `content/footer/`; `CaseCard` and `EstimateTeaserOption` scoped-block models (+ admin, serializers, seeds) so landing case tiles and the estimate teaser are owner-editable.
  Local infra fix: Docker Redis moved to host port **6380** — a native Homebrew Redis owns 6379, which silently split cache invalidation between host tooling and the containers (same class of issue as Postgres on 5433).
- [ ] **F2 — Marketing pages** (22): Landing → Services → service details → recruiting → SEO templates (ProjectType/City/State) → Blog → Case Studies → About/Careers/Contact/Legal → Inspiration → Search. All content from `content/pages/{key}`.
  - [x] `/` Landing — hero (image/carousel modes), promo banner, trust bar, 8 category tiles, how-it-works with the design's SVG step art, case-study cards, instant-estimate teaser (client island), plans from `catalog/plans/`, testimonials, trust & safety, final CTA.
  - [x] `/services-landing` Services Landing — hero, how-it-works, 8 category tiles, popular services, benefits, stamp-vs-no-stamp split, testimonials, FAQ accordion, final CTA.
  - [x] `/services` Services hub — breadcrumb, hero with 3-slide crossfade, `#catalog` (8 categories × 27 services from `catalog/categories/`), stamp-vs-no-stamp split, final CTA.
  - [x] `/services/3d-visualization` — hero, use cases, 6 deliverables, work gallery, specialists, 3 quality-tier price cards, how-it-works, FAQ, CTA.
  - [x] `/services/cad-drafting` — hero, use cases, 4 deliverables, work gallery, specialists, 3 pricing cards, 4 steps, FAQ, CTA.
  - [x] `/for-architects` (scope `architect-landing`) — hero with live matched-lead + payout cards, credential trust bar, 6 value props, 3 steps with SVG art, control split, escrow/fee breakdown, 4 tools, stories, verification, FAQ, CTA.
  - [x] `/for-experts` — hero with matched-order + payout cards, 6 disciplines with licence tags, 6 value props, 3 steps, control split, $1,200 escrow breakdown, 4 tools, stories, FAQ, CTA.
  - [x] SEO templates (projects/cities/jurisdictions with `generateStaticParams`), editorial (`/guides`, `/case-studies` + details), utility pages (`/about`, `/careers`, `/contact`, `/privacy`, `/inspiration`, `/search`), `/for-experts/pricing`, `/for-experts/tools`. *(status reconciled 2026-08-11 — these were built but never ticked here; see BUILD-UPDATES.md)*

  Conventions established (see `FRONTEND-CONVENTIONS.md`): marketing pages render the design's advertised **ranges** from CMS rows the owner can edit; order/quote flows use the live pricing config and backend math. Substituting one for the other silently changes the design.
- [x] **F3 — Funnel**: Get Started adaptive quiz (6 goals) + instant estimate + Clerk signup handoff + `/get-started/claim` → `/matches`. *(built; reconciled 2026-08-11)*
- [x] **F4 — Orders**: retired by the design resync — `/order/render` and `/order/drafting` permanently redirect into the quiz (`?intent=viz|drafting`), matching the design's retired `Order *.dc.html` pages.
- [x] **F5 — Matches & profiles**: `/matches` list + architect profile view + hire action. *(built; reconciled 2026-08-11)*
- [x] **F6 — Engagement dashboard**: `/engagements/[id]` scoping → contract → hire → dashboard (milestones, approve/request-changes, files, requotes). *(built; live updates land in F8)*
- [x] **F7 — Accounts**: `/account` (projects/messages/settings) + `/pro` & `/pro/expert` (onboarding wizards + dashboards). *(built; settings save + live data land in F8)*
- [x] **F8 — Real-time completion** *(2026-08-11 — full log in BUILD-UPDATES.md)*: working message composer + optimistic send, WebSocket client (`lib/realtime/`), presence, typing, notifications bell, live dashboard refresh, settings save, service worker + Web Push, loading/error boundaries, `/terms`. Backend: `uvicorn[standard]` (real-server WS was silently broken), psycopg pool (build-time connection exhaustion), notification fanout + per-action notify calls, fee fallback → 0%, presence counter, `is_mine` fanout fix. Verified: two-user live E2E, 490 tests @ 100% coverage, 116-page clean build.
- [ ] **F9 — SEO & performance pass**: sitemaps, structured data, image optimization audit.

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
