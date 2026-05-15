# ADR-087: Frontend Deployment — S3 + CloudFront

**Date:** 2026-05-14  
**Status:** Accepted

## Context

The AsheFlow frontend is a Vite/React SPA. It needs to be hosted somewhere that:
- Serves it over HTTPS at `asheflow.com` and `www.asheflow.com`
- Handles client-side routing (all paths must return `index.html`)
- Is cost-effective for a small-scale application
- Integrates with the existing AWS infrastructure (Route 53, ACM, us-east-2 backend)

## Decision

Host the frontend on **S3 + CloudFront**:
- S3 bucket `asheflow-frontend` (us-east-2) stores the static build output
- CloudFront distribution `E22NJCS9JDU8FG` serves it globally over HTTPS
- ACM certificate `f19b4975...` (us-east-1) covers `asheflow.com` and `www.asheflow.com`
- Route 53 Alias A records point both domains at CloudFront

## Consequences

**Cache strategy:**
- `index.html` — `no-cache,no-store,must-revalidate` — always revalidated
- All other assets — `public,max-age=31536000,immutable` — 1-year cache, safe because Vite appends content hashes to filenames

**SPA routing:** CloudFront custom error response maps 404 → `/index.html` with HTTP 200, enabling client-side routing for all paths.

**Redeployment process:**
```bash
cd frontend && npm run build
aws s3 sync dist/ s3://asheflow-frontend/ --region us-east-2 --delete \
  --cache-control "public,max-age=31536000,immutable" --exclude "index.html"
aws s3 cp dist/index.html s3://asheflow-frontend/index.html \
  --region us-east-2 --cache-control "no-cache,no-store,must-revalidate"
aws cloudfront create-invalidation --distribution-id E22NJCS9JDU8FG --paths "/index.html"
```

**ACM note:** CloudFront certificates must always be in `us-east-1` — a hard AWS requirement regardless of where other infrastructure lives.

## Alternatives Considered

- **Amplify Hosting** — simpler CI/CD but less control over caching headers, more expensive at scale, and adds another service to manage.
- **EC2 (serve from the same instance as the API)** — adds resource pressure to a t3.small already running 6 containers, and couples frontend and backend deployments unnecessarily.
