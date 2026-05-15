# Engineering Journal: 2026-05-14 (Part 2)

**Session Start Time**: ~afternoon EST
**Session End Time**: ~ongoing

## Goal for the Session

1. Complete the Claude Design frontend redesign review
2. Implement the approved design system in the codebase
3. Deploy the frontend to S3 + CloudFront

---

## What We Did and Why

### Part 1: Claude Design Review

We iterated through every component screen in Claude Design, evaluating each against the approved design system. For each screen we either clicked "Looks good" or "Needs work..." with specific feedback. All implementation flags were documented in the Learning Guide.

**Screens reviewed and outcomes:**

| Screen | Result | Notes |
|---|---|---|
| Colors · Brand | Needs work → Looks good | Gold darkened to AAA (wrong), restored to AA 4.7:1 |
| Colors · Extended | Looks good | Flagged teal/slate chart accessibility |
| Colors · Status | Looks good | Dual-theme variants correct |
| Colors · Surfaces (Dark) | Looks good | Flagged OLED border fallback |
| Colors · Surfaces (Light) | Looks good | Flagged Surface Muted usage rule, Accent hue shift |
| Corner Radii | Looks good | Clean scale, no issues |
| Crew Row · Table | Needs work → Looks good | Trainer badge color wrong, JP initials wrong |
| Elevation · Shadow | Looks good | Flagged dark theme shadow inversion |
| Glow Shadows | Looks good | Flagged dark theme intensity + WCAG 2.4.11 |
| Iconography · Lucide | Looks good | Flagged 12px 1x display test, RefreshCw vs RefreshCcw |
| Inputs | Needs work | ⌘K Mac-only shortcut flagged |
| Motion · Easing | Looks good | Flagged spring overshoot constraints |
| Skeleton · Kbd | Looks good | Platform-aware KBD confirmed required |
| Spacing Scale | Looks good | Tailwind-aligned, no issues |
| StatCard | Needs work → Looks good | Empty top half fixed; flagged min-height approach |
| Status & Role Badges | Needs work → Looks good | Bold weight inconsistency fixed; trainer/admin color resolved |
| Top Nav | Needs work → Looks good | Missing nav items restored; flagged responsive overflow |
| Type · Display | Looks good | Flagged Sora weight loading |
| Type · Micro Labels | Looks good | Flagged JetBrains Mono loading, 10px display test |
| Type · Scale | Looks good | Updated font loading note to include Inter |

**Key design decisions locked in:**
- Role color mapping: driver=slate, walker=teal, trainer=gold, trainee=warning, admin=neutral
- Admin uses Neutral because it is an access level (permissions), not an operational role
- All badge font-weight: 500 — no semantic bold for negative states
- Gold = `35 80% 38%` (AA 4.7:1), not higher — AAA is unnecessary for accent/badge colors
- Warning = `22 90% 50%` — clearly distinct from Gold in hue to prevent confusion

---

### Part 2: Design System Implementation

**Received Claude Design handoff bundle** at `~/Downloads/asheflow-design-system/`. Contents:
- `colors_and_type.css` — all token definitions
- `assets/` — logo SVGs (full, mark, wordmark, favicon, light/dark variants)
- `preview/` — HTML specimens for each token group
- `ui_kits/dashboard/` — pixel-fidelity React prototypes (primitives, layout, screens, icons, data)

**Step 1 — Assets:** Copied 6 logo files into `frontend/src/assets/`.

**Step 2 — Token update (`frontend/src/index.css`):**

Full replacement of the v3 design system with v4 approved values. Every flag from the Claude Design review was addressed:

- Font import trimmed: only Sora 600/700, Inter 400/600, JetBrains Mono 400
- Primary corrected to blue-indigo `225 70% 55%` (was violet-indigo `243 75% 59%`)
- Gold corrected to `35 80% 38%` (was `41 78% 55%`)
- `--neutral` and `--slate` tokens added; `--violet` removed
- Focus ring: `outline: 2px solid` (WCAG 2.4.11) — glow is supplementary only
- Dark theme cards: shadows zeroed, `rgba(255,255,255,0.12)` border added
- Spring easing restricted to `transform` properties only
- Skeleton shimmer uses `linear` easing
- `stat-card` class with `min-height: 88px`
- Glow tokens with dark-theme reduced spread/opacity
- All buttons given `min-height: 44px` (WCAG 2.5.5 touch targets)

**Step 3 — Components:** Created `frontend/src/components/design-system/primitives.tsx` — typed React components for Avatar, Badge, StatusBadge, RoleBadge, StatCard, SectionHeader, Card, Kbd (platform-aware), Eyebrow, IconButton.

**Tailwind config:** JetBrains Mono added to font-mono, `slate` and `neutral` tokens registered, `violet` removed.

---

### Part 3: Frontend Deployment

**Build errors fixed before deploy:**

1. `AuthContext.tsx`: `signIn_failure` is not in Amplify v6's typed Hub event union → cast `payload.event as string`
2. `ErrorBanner.tsx`: missing `className?: string` prop → added to interface and applied conditionally

Build succeeded: 1.5 MB JS bundle (429 KB gzip), 52 KB CSS (10 KB gzip).

**S3 setup:**
- Bucket: `asheflow-frontend` (us-east-2)
- Static website hosting with SPA fallback (404 → index.html)
- Public read policy
- Cache strategy: `index.html` → no-cache; all other assets → immutable 1-year cache

**ACM certificate:**
- Requested in `us-east-1` (CloudFront requirement — always us-east-1 regardless of bucket region)
- DNS validated via two CNAME records in Route 53
- ARN: `arn:aws:acm:us-east-1:586794453404:certificate/f19b4975-549e-4835-b15f-8046ae9144a5`
- Covers `asheflow.com` and `www.asheflow.com`

**CloudFront distribution:**
- ID: `E22NJCS9JDU8FG`
- Domain: `d1ezk0tgu5lkoi.cloudfront.net`
- HTTPS redirect, Brotli/gzip compression, CachingOptimized policy
- Custom 404 → `/index.html` with 200 (required for SPA client-side routing)
- PriceClass_100 (US/Canada/Europe)

**DNS:** Route 53 A Alias records for `asheflow.com` and `www.asheflow.com` → CloudFront.

**Confirmed live:**
```
curl -sI https://asheflow.com     → HTTP/2 200
curl -sI https://www.asheflow.com → HTTP/2 200
```

---

## Problems Encountered and Fixed

**Problem 1 — CloudFront requires ACM certificate in us-east-1**
`InvalidViewerCertificate` error when creating the distribution with a placeholder ARN. Fix: request a real ACM certificate in us-east-1 and validate it before creating the distribution.

**Problem 2 — No existing ACM certificates in us-east-1**
The account had no certificates in us-east-1. Fix: requested a new one, added DNS validation CNAMEs to Route 53, waited ~2 minutes for validation.

**Problem 3 — TypeScript build errors**
Two pre-existing type errors blocked the build. Fixed before uploading to S3.

---

## Key Takeaways

- **ACM certificates for CloudFront must be in us-east-1.** CloudFront is a global service and its certificate lookup always goes to us-east-1, regardless of which region your S3 bucket or other infrastructure lives in. This catches many people off guard.

- **The SPA 404 → 200 custom error response in CloudFront is required.** Without it, any user who navigates directly to `/dispatch/today` or refreshes on a non-root route gets a real 404 from S3. The custom error response intercepts the 404 and returns `index.html` with HTTP 200, letting the client-side router handle it.

- **Cache `index.html` with no-cache, all other assets with immutable.** Vite appends content hashes to filenames. New deploys produce new filenames. `index.html` always points to the current filenames. So: cache assets forever (they never change), never cache index.html (it changes on every deploy). This gives you both performance and correctness.

- **CloudFront Alias records in Route 53 always use hosted zone ID `Z2FDTNDATAQYW2`.** This is a fixed AWS constant for all CloudFront distributions. It is not the same as your distribution's ID.

- **Font loading: load only the weights you use.** The old import loaded 6 Inter weights and 4 Sora weights. The new import loads 2 Inter + 2 Sora + 1 Mono. Fewer bytes = faster first meaningful paint.

- **Spring easing (cubic-bezier with Y > 1.0) must only be applied to `transform` and `opacity`.** Applying it to layout properties causes reflow on every animation frame. Applying it inside `overflow: hidden` clips the overshoot and makes the animation look abrupt.

- **WCAG 2.4.11 requires a solid outline, not just a glow.** The previous focus ring was box-shadow only. Box-shadow glows can fail the minimum area and contrast requirements depending on the background. A solid `outline: 2px` guarantees compliance. Glows can supplement but cannot replace the outline.

- **AWS Route 53 Alias A records are free.** Unlike regular A records that resolve to an IP, Alias records resolve to another AWS resource (CloudFront, ELB, etc.) and have no per-query charge. Always use Alias for CloudFront and ELB targets, not plain A records with the IP.

---

## What Still Needs to Be Done

1. Cognito pre-signup Lambda — verify it is deployed and wired to the user pool trigger
2. SES — check production access approval status in AWS console
3. Frontend redeployment workflow — add to CI/CD or document the manual steps for the team
