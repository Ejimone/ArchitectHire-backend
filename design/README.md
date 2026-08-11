# ArchitectHire — page inventory

**Start here:** [`Business Wiki.dc.html`](Business%20Wiki.dc.html) — business context
& product brief (concept, differentiators, journey, pricing, revenue, risks).
Read it first whenever you return to this design doc. Launching in all 52 US
jurisdictions (50 states + D.C. + Puerto Rico).

Prototype pages are split by surface so the marketing site and the product app
can be handed off and built independently. All pages are self-contained
Design Components (`.dc.html`) sharing one visual system: navy `#0a1440`,
blue `#135bff`, lime `#ceff65`; Bricolage Grotesque headlines, Hanken Grotesk
body, IBM Plex Mono for figures.

## `marketing/` — public marketing site
Anonymous, SEO/conversion surface. Shared header nav across all pages:
How it works · Services · Projects · Case studies · Guides · For architects.

| File | Purpose |
|------|---------|
| `Landing.dc.html` | Homepage — hero, categories, how it works, case studies, pricing, plans |
| `Services Landing.dc.html` | Services marketing landing (hero, how it works, categories, popular services, FAQ) — entry point for non-architect services |
| `Services.dc.html` | Services hub — full three-tier catalog (Volume $50–500 · Core $500–5k · Full-project $5k+) |
| `3D Visualization.dc.html` | Service detail — renders, 3D floor plans, walkthroughs |
| `CAD Drafting.dc.html` | Service detail — CAD drafting, as-builts, PDF-to-CAD |
| `Architect Landing.dc.html` | Recruiting page for architects (its own nav) |
| `For Experts.dc.html` | Recruiting page for non-architect service experts (drafters, 3D, scanning, engineering, permits) |
| `Project Landing.dc.html` | SEO page per project type (ADU, addition, …) |
| `City Landing.dc.html` | SEO page per city/jurisdiction |
| `Blog.dc.html` | Guides index |
| `Blog Post.dc.html` | Guide article |
| `Case Studies.dc.html` | Case study index |
| `Case Study.dc.html` | Individual case study |

## `app/` — authenticated product
Signed-in experience. The funnel starts at Get Started and hands off to Matches.

| File | Purpose |
|------|---------|
| `Get Started.dc.html` | Unified adaptive quiz — one "what do you need?" fork branches into design/permitting, drafting, consult, 3D, or engineering; asks only relevant questions → instant estimate → specialist match → account. Reads `?intent=`, `?svc=`, `?state=` so service/city landing pages niche it down. |
| `Order Render.dc.html` | Redirect → `Get Started.dc.html?intent=viz` (retired standalone flow, unified into the quiz) |
| `Order Drafting.dc.html` | Redirect → `Get Started.dc.html?intent=drafting` (retired standalone flow, unified into the quiz) |
| `Matches.dc.html` | Curated architect matches + profile |
| `Engagement.dc.html` | Project dashboard, messages, review/approve flows |
| `Account.dc.html` | Homeowner portal — all projects |
| `Architect Account.dc.html` | Architect portal — leads, projects, earnings |
| `Expert Account.dc.html` | Discipline-aware expert onboarding (drafters, 3D, scanning, engineering, permits) — credential steps appear only for licensed disciplines |

## `brand/` — brand assets
| File | Purpose |
|------|---------|
| `Brand Logo.dc.html` | Logo lockups |
| `Logo Ideas.dc.html` | Logo explorations |

## Shared runtime (root)
- `support.js` — Design Component runtime (referenced as `../support.js`)
- `image-slot.js` — drop-in image placeholder web component
- `uploads/` — user-supplied images (referenced as `../uploads/`)

## Cross-surface links
- Marketing "Sign up" / CTAs → `../app/Get Started.dc.html`
- App logo → `../marketing/Landing.dc.html`
- Architect Landing "Apply" → `../app/Architect Account.dc.html`
