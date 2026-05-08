# ADR-067: Infrastructure — Domain Registration, SES, and CAPTCHA Selection

**Date:** 2026-05-07
**Status:** Implemented (SES production access pending AWS approval)

## Context

Phase 2 of the multi-tenant roadmap includes a public `/recruit` page for driver
applicants and an `/register` page for invited employees. Both require:

1. A branded domain for email sends and public URLs
2. A verified email sender so SES can send invite and registration emails
3. A CAPTCHA on the public `/recruit` page to block bot submissions

## Domain: `asheflow.com` via Route 53

Registered through **AWS Route 53 Registrar** (not Cloudflare Registrar).

**Why Route 53 over Cloudflare:**
Cloudflare Registrar locks nameservers to Cloudflare's NS servers, removing the
ability to delegate to another provider without transferring the domain first.
Route 53 keeps all DNS management inside AWS, where the rest of the infrastructure
lives, and avoids the two-step transfer process if DNS ever needs to move.

A hosted zone was created automatically on registration. All DNS records
(DKIM CNAMEs, SPF TXT, future A records for the web app) live here.

## SES: `noreply@asheflow.com`

SES was configured in **us-east-2** to match all other AWS infrastructure.

Steps completed:
- Domain identity `asheflow.com` verified with three DKIM CNAME records added to Route 53
- SPF TXT record added: `v=spf1 include:amazonses.com ~all`
- SES production access request submitted with justification:
  - Invite emails to new employees (admin-triggered, not bulk)
  - Password reset / account verification emails
  - Transactional only; opt-out and bounce handling described
- Cognito new pool wired to send from `AsheFlow <noreply@asheflow.com>`

**Known limitation:** SES remains in sandbox until AWS approves production access.
During sandbox, emails only reach verified addresses. This does not affect Cognito
auth emails (Cognito has its own SES sending quota allocation).

## CAPTCHA: Cloudflare Turnstile

Selected for the public `/recruit` page over hCaptcha and reCAPTCHA v3.

**Why Turnstile:**
- Near-zero user friction — solves silently in most cases, no image grids
- Free tier covers the applicant volume expected at launch
- Privacy-friendly — no Google tracking pixel
- JS embed is straightforward; backend just calls the Turnstile verify endpoint

**Implementation deferred to Phase 2** when the `/recruit` page is built.

## Files changed

- `backend/.env` — `AWS_REGION` confirmed `us-east-2`
- Route 53 hosted zone for `asheflow.com` — DKIM + SPF records added (console only, no code)
- `bot/.env` — no changes for this item
