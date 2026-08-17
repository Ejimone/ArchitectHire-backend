# ArchitectHire — Stage Tracker

Single source of truth for the "make the whole platform walk" programme across all three
repos. One section per stage; update the status line and check off deliverables as work
lands. **No stage is marked DONE without its verification passing**, and the passing output
is recorded under the stage.

Repos:

| Repo | Path | Deploys to |
|---|---|---|
| Backend (Django) | `ArchitectHire-backend` | DO App Platform — `architecthire-wkqzm.ondigitalocean.app` |
| Marketing + app (Next) | `Architecture-hire` | Vercel — `architecthire.com` |
| Studio (Next) | `architecthire-studio` | Vercel — `architecthire-studio.vercel.app` |

**How to run the backend locally**

```bash
docker compose up -d db redis     # Postgres on host port 5433, Redis on 6380
uv sync
uv run python manage.py migrate
uv run python manage.py seed --all
uv run uvicorn architecture_backend.asgi:application --reload
uv run pytest                     # 100% coverage enforced
```

---

## Why this programme exists

The platform failed a live investor demo. Diagnosed against **production**, not just source:

1. **Zero images render on architecthire.com.** 112 `<ImgSlot>` placeholders site-wide, 2
   ever filled — and both of those 400 at `/_next/image` because Django emits *path-style*
   Spaces URLs while the frontends allowlist only the *virtual-hosted* host.
2. **Nothing is shareable.** 4 meta tags total; no OG/Twitter/canonical, no JSON-LD.
   `seo.og_image` is served by the backend and never read by the frontend.
3. **Clerk's development instance runs in production**, loading a third-party SDK on all
   ~116 marketing pages.
4. **The studio is non-functional as deployed** — the Vercel project has no env vars at all,
   so every page shows "Backend unavailable".
5. **`/healthz` returns 200 unconditionally** — the heartbeat cannot detect an unhealthy app.

Full diagnosis and rationale: `~/.claude/plans/i-want-to-build-magical-kitten.md`.

---

## Stage map

| Stage | Name | Status |
|---|---|---|
| 0 | Groundwork | DONE 2026-08-17 |
| 1 | Backend — media pipeline | DONE 2026-08-17 |
| 2a | Backend — health probe, pooling, throttles, root URL | DONE 2026-08-17 |
| 2b | Backend — CMS write gaps, og_image, missing admin models | TODO |
| 3 | Content — fill the image inventory | TODO |
| 4a | Deploy the image fix — **live and verified** | DONE 2026-08-17 |
| 4b | Prod content drift, worker count, pre-deploy job | TODO |
| 5 | Frontend — images, sharing, speed | TODO |
| 6 | Studio — make it genuinely good | TODO |
| 7 | Final pass | TODO |

---

## Stage 0 — Groundwork

**Status: DONE 2026-08-17**
Goal: a working local stack, an honest baseline, and this tracker.

- [x] `STAGES.md` created with the full stage map
- [x] Docker daemon started; `db` + `redis` healthy (5433 / 6380)
- [x] `migrate` clean — applied `engagements.0003_engagement_unique_engagement_per_project_provider`
- [x] `seed --all` green — 52 states, 12 cities, 27 services, 9 project types, 1320 copy
      blocks, **169 media slots**, 23 SEO rows, patches applied (1024 copy / 390 blocks /
      68 records / 42 removed)
- [x] Baseline `uv run pytest` green — **992 passed, 12 skipped, 100% coverage**
- [x] `.env.prod` repaired — 1,097 lines of docker-compose log output had been pasted into
      the middle of it (112 KB → 5 KB, 83 lines). All 31 values verified byte-for-byte
      identical afterwards; the file stays git-ignored.
- [ ] DEPLOY.md records the studio (currently zero mentions) and the true App Platform
      spec — deferred to Stage 6, where the studio deployment is actually configured

**Verification**

```bash
docker compose up -d db redis && docker ps         # both healthy
uv run python manage.py migrate && uv run python manage.py seed --all
uv run pytest                                      # 100%, no failures
```

---

## Stage 1 — Backend: the media pipeline

**Status: DONE 2026-08-17**
Goal: an uploaded image reaches the browser, fast, on every surface.

- [x] **Virtual-hosted addressing** (`AWS_S3_ADDRESSING_STYLE=virtual`, `base.py`). This is
      *the* fix for "no images on the site". With no custom domain, botocore defaults to
      path-style against a custom endpoint and emitted
      `https://sfo3.digitaloceanspaces.com/<bucket>/…`, whose hostname is the shared
      regional endpoint — not in either frontend's `remotePatterns`, so `/_next/image`
      answered **400 INVALID_IMAGE_OPTIMIZE_REQUEST** for every CMS image.
      `AWS_S3_CUSTOM_DOMAIN` still overrides it for the CDN host.
- [x] `AWS_S3_REGION_NAME` now defaults to `sfo3`, not `nyc3` (wrong region = SigV4 rejects
      every upload while reads keep working); `AWS_S3_ADDRESSING_STYLE` added; both
      documented in `.env.example` with the failure mode spelled out
- [x] Prod **refuses to boot** without storage credentials rather than silently falling
      back to `FileSystemStorage`, which serves 404 for 100% of media on App Platform and
      loses every upload on the next deploy. Dockerfile passes dummies for the build-time
      `collectstatic`, which only touches the whitenoise backend.
- [x] **Upload normalisation** — `apps/core/images.py` + `ProcessedImageField`, applied to
      all 18 `ImageField`s (migrations `cms.0008`, `providers.0002`; column-compatible).
      Caps the long edge at 2560px, strips EXIF (**GPS included** — an agency uploading
      photos of clients' houses would otherwise publish their coordinates), re-encodes to
      WebP, and keeps the original whenever the result would be larger or the image is
      animated/unreadable. `og_image` targets **JPEG** instead: link-preview crawlers do
      not reliably render WebP, and a blank preview card is the failure we are fixing.
      Measured on the two images actually in production:
      `1101 KB (3378×614) → 17 KB (2560×465)` — **98% smaller**; `228 KB → 169 KB` — 26%.
- [x] Slot inventory completed — the 25 missing service-gallery slots
      (`cad-drafting:cad-g1..5`/`cad-s1..3`, `3d-visualization:viz-d1..6`/`viz-g1..5`/`viz-s1..6`)
      are now derived from their rows. Inventory **169 → 194 slots**. `HeroCarouselSlide`
      and `Persona` added to the sync signals, without which the inventory only ever grew.
- [x] `manage.py sync_media_slots` (with `--dry-run`) — safe to run on production after a
      deploy, unlike `seed`, because it touches nothing but slot rows
- [x] **Media cache invalidation fixed.** `/content/media/` cached under slug
      `_media:<prefix>`, which matched no tag, so its counter never moved past 1 (live ETag
      `"3.1-_media:"`): an upload stayed invisible for the full 15-minute TTL, and the
      frozen ETag meant `If-None-Match` clients were told 304 against the empty body
      *indefinitely*. Cache key and version slug are now separable
      (`CachedContentView.get_version_slug`); one `cms:media` tag versions every prefix.
- [x] Media endpoint ordered and bounded — it was an unordered `[:500]` slice, so *which*
      rows survived truncation was whatever the planner returned; now `order_by("slot_key")`
      with an explicit `truncated` flag
- [x] `MediaAssetAdmin` — `notes` editable by all staff, `slot_key` repairable by a
      superuser. A *filled* row under a wrong key renders nowhere and is never pruned, so
      locking the field permanently left it stuck forever.

**Verification** *(run 2026-08-17)*

```
uv run pytest            -> 1019 passed, 12 skipped, 100.00% coverage
sync_media_slots --dry-run -> 25 to create, 0 to prune, 194 slots expected
PublicMediaStorage().url("cms/hero/example.webp")
  -> https://allsermon-media.sfo3.digitaloceanspaces.com/media/cms/hero/example.webp
     hostname in both frontends' remotePatterns: True
```

---

## Stage 2a — Backend: the heartbeat, pooling and the front door

**Status: DONE 2026-08-17**

- [x] **`/healthz` is a real readiness probe** (`apps/core/health.py`). It returned a
      literal `200` without touching anything, so a container whose psycopg pool had died
      — handing out dead connections, every request failing with `PoolTimeout` — still
      reported itself healthy and kept taking traffic until someone restarted it by hand.
      Three constraints shaped the replacement: it runs on its **own dedicated thread**
      (never Django's shared sync thread, which a request burst saturates — that is what
      got healthy containers killed before), its result is **memoised for 5s** so probe
      frequency is irrelevant, and it is **deliberately asymmetric** — a dead database
      fails the probe (a per-container fault only a restart clears) while a dead Redis is
      reported but does not, because failing the fleet on a shared dependency turns a blip
      into a total outage.
- [x] **`DB_POOL_MAX` default 8 → 3, `DB_POOL_MIN` 2 → 1.** The defaults were chosen for
      2 gunicorn workers; the Dockerfile then went to 6, making the real ceiling 48 against
      a 22-connection cluster. It held at rest and failed under load, as
      "sorry, too many clients already" — locking out `migrate` and psql at exactly the
      moment they were needed. 3 × 6 = 18 leaves 4 spare. Dockerfile comment reconciled.
- [x] **`NOTIFY_POOL` derived from `DB_POOL_MAX`** instead of a flat 4 justified by a
      comment claiming `max_size=20`. Four background threads against a pool of three can
      hold every connection a worker has, leaving the request thread to wait out the 10s
      pool timeout — which presents as an unexplained stall.
- [x] **Studio throttles.** `studio-login` 10/hour → 30/hour (ten mistyped passwords locked
      the owner out of their own CMS for an hour); new `studio` scope at 600/min, because
      the canvas issues ~4 authenticated calls per render and refreshes after every save,
      so the default `user: 120/min` was reachable within minutes of normal editing.
- [x] **The deployment URL no longer 404s.** Opening the bare API host landed on Django's
      unstyled "Not Found" — the server had routes for `/admin/` and `/api/` and nothing at
      the root. `/` now 302s to `/admin/` (302, not 301: a permanent redirect is cached by
      browsers effectively forever). Unknown paths still 404, so genuine routing mistakes
      stay visible.

**Verification** *(run 2026-08-17, against a live local server)*

```
uv run pytest              -> 1035 passed, 12 skipped, 100.00% coverage
ruff check + format --check -> clean

GET /healthz  (Host: 10.0.0.7, as a platform prober sends)  -> 200  db=ok cache=ok  (70ms)
  repeated x5                                               -> ~0.3ms each (memoised)
docker compose stop db; GET /healthz                        -> 503  db=timeout cache=unknown
docker compose start db; GET /healthz                       -> 200  db=ok cache=ok
GET /                                                       -> 302 -> /admin/ -> 200
GET /nope, /api/v1/bogus/                                   -> 404 (unchanged)
```

## Stage 2b — Backend: CMS completeness

**Status: TODO**
Goal: everything the site renders is owner-editable.

- [ ] Studio write allowlist extended to catalog (`Service`, `ProjectType`, plans, pricing),
      jurisdictions (`City`/`State` prose), editorial detail (`BlogPost`, `CaseStudy`,
      `InspirationItem`), careers/contact/policy — with field schemas, publish and revisions
- [ ] `SeoView` stops silently dropping `og_image`; site-wide default OG image added
- [ ] `apps/studio_api/admin.py` added (`ContentDraft`, `ContentRevision`, `StudioSession`);
      `cms.InspirationLike` registered

**Verification**

```bash
uv run pytest                                  # 100%
uv run python manage.py check --deploy         # clean
# a test asserts the studio write allowlist covers every model the site registry renders
```

---

## Stage 3 — Content: fill the image inventory

**Status: TODO**
Goal: the site is never a wireframe again, on any deploy.

Demand: 46 static slots + 12 cities + 9 project types (with galleries) + 7 blog posts +
7 case studies + 12 inspiration items + testimonials, trust logos, steps, case cards
≈ **200+ images** (169 `MediaAsset` slots seeded locally, plus record-level images).

- [ ] Seeded stock floor — curated, correctly-licensed architectural photography committed
      as seed data, attribution stored on the record
- [ ] AI-generated set for slots where stock reads generic (quiz style tiles, product
      screenshots, step art)
- [ ] Every image carries meaningful alt text

**Verification**

```bash
# zero img-slot placeholder elements across every sitemap URL
# (today: 7 on /, 10 on /services/3d-visualization, 15 on /inspiration,
#  8 on /cities/austin, 4-8 elsewhere)
```

---

## Stage 4a — Deploy the image fix

**Status: DONE 2026-08-17** — merged to `main`, deployed, verified against production.

What the live app spec actually said (worth recording, because two of my earlier
suspicions were wrong):

- `AWS_S3_REGION_NAME=sfo3` and `DB_POOL_MIN/MAX=1/3` were **already correct** in the app
  spec. The code defaults were wrong (`nyc3`, `8`), which matters for any environment that
  does not override them — but these were never live bugs.
- `AWS_S3_CUSTOM_DOMAIN` and `AWS_S3_ADDRESSING_STYLE` were both unset, which is the
  entire cause. The new code default (`virtual`) fixes it **with no env var change at all**.
- The spec's `run_command` **overrides the Dockerfile CMD** and pins `--workers 2`. The
  6-worker change in `1ca5bd6` therefore never took effect in production. Carried to 4b.

**Verification** *(against production, 2026-08-17)*

```
GET /healthz                          -> db=ok cache=ok        (was: unconditional "ok")
GET /                                 -> 302 -> /admin/        (was: bare "Not Found")
GET /api/v1/content/pages/landing/    -> hero_image now
     https://allsermon-media.sfo3.digitaloceanspaces.com/media/cms/hero/...
     (was: https://sfo3.digitaloceanspaces.com/allsermon-media/...)

/_next/image with the NEW url  -> 200  image/jpeg  164 KB   <- the fix
/_next/image with the OLD url  -> 400                       <- what every image did
```

Frontend data cache purged via `POST /api/revalidate` (tags: `cms`); the live homepage now
serves the new URL and the image loads.

**Remaining zeros are content, not code** — 194 slots with nothing uploaded:

```
/                          images=1  empty-slots=7
/about                     images=0  empty-slots=5
/services/3d-visualization images=0  empty-slots=10
/cities/austin             images=0  empty-slots=8
/inspiration               images=0  empty-slots=15
```

That is Stage 3.

## Stage 4b — Prod content drift, worker count, release process

**Status: TODO**

- [ ] **[owner]** CDN enabled on the `allsermon-media` Space — the `.cdn.` host currently
      refuses connections
- [ ] **[owner]** App Platform spec updated: `AWS_S3_CUSTOM_DOMAIN`, `AWS_S3_REGION_NAME=sfo3`,
      `DB_POOL_MAX=3`, `CRON_SECRET`; `REVALIDATE_SECRET` confirmed to match Vercel
- [ ] Push, then `migrate && seed --all` from the app console
- [ ] **Seed-patch drift fixed.** Proof it is real: production's footer and nav still link
      "Terms of Service" to the dead `/privacy#terms` anchor although `seeds/patches/terms.json`
      repointed it to `/terms` — the patch only ever reached the local dev DB. Every file in
      `seeds/patches/` audited for the same drift.
- [ ] Pre-deploy job (or release script) reinstated so the manual step cannot be forgotten
- [ ] Post-deploy smoke test that fetches `/_next/image` with a real production media URL.
      Local dev cannot reproduce the image bug by construction
      (`dangerouslyAllowLocalIP: !isProd` + localhost media), which is how it shipped green.

**Verification**

```bash
curl -s https://<api>/healthz            # reflects real health
curl -s https://<api>/api/health/        # 200
curl -s https://<api>/api/v1/content/media/ | jq '.slots | length'   # > 0
# every media URL 200s from the CDN host; 8-way concurrency stays under 500ms
```

---

## Stage 5 — Frontend: images, sharing, speed

**Status: TODO**
Repo: `Architecture-hire`.

- [ ] Responsive `sizes`, `preload` on above-the-fold heroes, blur placeholders,
      aspect-ratio reservation so filling slots introduces no layout shift
- [ ] Full `openGraph`/`twitter` metadata from CMS `PageSEO` (`og_image` and `canonical` are
      already in the payload and simply unused)
- [ ] `/opengraph-image`, `/manifest.json`, `favicon.ico`, `apple-touch-icon.png` — all 404
      today; `public/` contains exactly one file (`sw.js`)
- [ ] JSON-LD: `Organization`, `WebSite`+`SearchAction`, `Service`, `BreadcrumbList`,
      `Article` on guides, `FAQPage` where FAQ blocks exist
- [ ] `ClerkProvider` mounted only on authed segments, and swapped to a production Clerk
      instance — the largest single perceived-speed win available
- [ ] CMS fields that are fetched and thrown away now render: `NavItem.image`,
      `NavItem.sublabel`, `NavItem.is_featured`, `trust_logos[].image`
- [ ] `cities/[slug]` hardened — its `notFound()` sits inside a `try` around a 3-way
      `Promise.all` including the *shared* `getPage("cities")` hub, so one hub failure would
      404 all 12 city pages
- [ ] Caching **verified, not rebuilt** — tag-based `revalidateTag` behind a timing-safe
      secret is already correct and live (a bad-secret ping returns 401, not 503)
- [ ] Real-time verified against production `wss://…/ws/`
- [ ] CSP promoted from report-only where prerendering allows

**Verification**

```bash
# every sitemap URL 200, zero img-slot placeholders
# link-preview debugger renders a card
# Lighthouse >= 95 perf/SEO/a11y/best-practices on the homepage + 3 templates
```

---

## Stage 6 — Studio: make it genuinely good

**Status: TODO**
Repo: `architecthire-studio`. Architecture note: there is **no iframe** — the real site
components render in the same React tree via a path alias, with copy keys carried through
invisible Unicode stega markers. That design is sound and stays.

**P0 — make it run**
- [ ] Vercel env set: `STUDIO_API_URL`, `NEXT_PUBLIC_SITE_URL`, `SPACES_MEDIA_HOST`,
      `NEXT_PUBLIC_API_URL`. `STUDIO_API_URL` must be an `https://` origin **at build time**
      for the image allowlist to be generated.
- [ ] `not-found.tsx`, `error.tsx`, `global-error.tsx`, `loading.tsx` in studio styling
- [ ] Layout stops reporting genuine 500s as "Backend unavailable"

**P1 — no dead ends**
- [ ] ~25 unwrapped page keys wrapped in `site/registry.tsx` (`get-started`, `service:*`,
      `project-type:*`, `blog-post:*`, `case-study:*`)
- [ ] Placeholder chips for unauthored copy — `mark("")` returns `""`, so a copy key with no
      row renders nothing and can never be clicked into existence (343 seeded strings vs
      ~1,800 rendered)
- [ ] Sign-out wired (the endpoint exists and is unreachable)
- [ ] `landing:hero-arch` missing `slot=` prop; `services-landing` and `order-*` "View live"
      routes; canvas nav-search CORS failure
- [ ] Bulk media uploader — drag many files, auto-match to slots, inline crop and alt text

**P2 — speed**
- [ ] Optimistic updates + targeted revalidation (today: 8–10 uncached round trips per
      render, all re-run by `router.refresh()` after every single save)
- [ ] Page tree and field schema cached (currently 6 unpaginated scans + 23 model schemas
      rebuilt per request)
- [ ] Canvas selection tracker throttled — it walks `querySelectorAll("*")` over the whole
      document on every scroll and resize
- [ ] 544 KB first-load JS on `/edit/[key]` trimmed

**P3 — durability**
- [ ] `pnpm sync:check` wired into CI so wrapped pages cannot silently drift from the site
- [ ] Studio documented in DEPLOY.md

**Verification**

```bash
# every page-tree entry opens a working editor
# edit -> publish -> live site updates
# image upload -> renders
# no route produces an unstyled 404; save-to-repaint under 300ms
```

---

## Stage 7 — Final pass

**Status: TODO**

- [ ] Two-user live E2E — messaging, presence, notifications
- [ ] Full route sweep across all three apps
- [ ] `uv run pytest` at 100%; clean production builds for both Next apps
- [ ] Demo script walked start to finish

**End-state proof the owner can run**

1. `uv run pytest` — 100%, green
2. Every sitemap URL returns 200 with **zero** `img-slot` placeholders
3. Paste `architecthire.com` into Slack — a real preview card appears
4. Edit a headline in the studio, publish — it appears on the live site within seconds
5. Upload a photo into any image slot — it renders on the site
6. Lighthouse ≥ 95 across the board
