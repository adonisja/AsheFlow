# Proposal: AsheFlow — Automated Dispatch & Operations Platform

**To:** [Manager / Operations Director Name]  
**From:** [Author]  
**Date:** [Date]  
**Re:** Proposal for Automated Daily Dispatch, Crew Management, and Operations Tooling

---

## The Problem

Every morning, our dispatch process requires solving a staffing puzzle under time pressure. Between 7:40 and 8:10 AM, someone must manually:

- Cross-reference availability across 30–70+ staff members accounting for scheduled off-days and approved PTO
- Staff 5–7 trucks each requiring exactly 1 Driver, the correct number of Trainers, and available Walkers
- Enforce rotation rules so no employee repeats the same truck on consecutive days
- Apply interpersonal constraints — keeping incompatible pairings apart, prioritizing high-performing partnerships
- Publish assignments and field individual confirmation responses before the 8:20 AM driver deadline
- React to no-shows, declined assignments, and last-minute changes before the 9:00 AM crew deadline

This process is done entirely by hand, creating a daily bottleneck during the most time-critical window of our operations. It is slow, error-prone, and entirely dependent on one person holding all the context in their head.

---

## The Solution

I have designed and developed **AsheFlow** — a purpose-built dispatch and crew management platform — entirely outside of my standard working hours as an independent software developer. The system automates the dispatch algorithm, manages the full morning confirmation workflow, and provides operational visibility to management and dispatch coordinators in real time.

This is not a generic scheduling tool adapted to our needs. It was built around the exact constraints, rules, and workflows of our operation.

---

## What AsheFlow Does

### 1. Automated Dispatch Algorithm

The system generates a complete, rule-compliant daily crew assignment in under one second. The algorithm enforces:

- **Availability filtering** — automatically excludes staff on approved PTO, recurring off-days, or marked unavailable for the date
- **Truck staffing requirements** — correct Driver / Trainer / Walker ratios per truck, configurable per dispatch run
- **Consecutive assignment prevention** — no employee is assigned to the same truck on back-to-back days
- **Ban list enforcement** — specific Driver / Walker pairings flagged as incompatible are never assigned together
- **Fan boost prioritization** — high-performing and compatible pairings are actively favored, which directly supports route completion rates and helps in reducing RTS (Return to Station) packages
- **Training debt tracking** — trainees who have not yet completed required training sessions are escalated and prioritized for assignment
- **Multi-pass weighted selection** — the algorithm runs multiple optimization passes to maximize the quality of the assignment, not just its legality

The dispatcher reviews the proposed assignment before it is published. Nothing goes out automatically without human sign-off.

### 2. Discord Confirmation Workflow

Once the dispatcher publishes, the system handles the entire morning confirmation window:

- Each crew member receives a personalized Discord DM with their truck assignment, role, and crew roster
- Confirm and Decline buttons are presented directly in the DM — no commands to memorize
- The driver confirmation deadline (8:20 AM) and crew deadline (9:00 AM) are enforced by the system
- Declined or unconfirmed assignments generate an immediate alert to the dispatcher
- At 9:05 AM, finalized crew rosters are posted to each truck's Discord channel and the master list is posted to the Drivers' Chat

### 3. Real-Time Operations Dashboard

Management and dispatch coordinators have a live view of the day's operations:

- **Fleet status board** — which trucks are planned, currently active (departed), or completed (returned)
- **Confirmation tracker** — live counts of confirmed, pending, and declined crew members per truck
- **Staff availability panel** — who is off today and why (PTO, off-day, etc.)
- **Pending change requests** — schedule changes, assignment swaps, and time-off requests awaiting approval

### 4. Field Operations Tracking

Drivers and field staff interact with the system directly from their phones:

- **Check-in** — records the driver's arrival on site
- **Pre-trip vehicle inspection** — structured checklist submitted before departure; failures generate an immediate alert to dispatch
- **Departure recording** — timestamps when the truck leaves, activating the truck's status in real time
- **Return recording** — timestamps when the truck returns, closing out the shift
- **Walker attendance and ratings** — drivers submit attendance and performance ratings for their walkers within a configurable post-departure window

### 5. Management Tooling

- **Employee lifecycle management** — create, invite, and manage staff accounts; bulk import from CSV, Excel, or JSON for large onboarding batches
- **Incident reporting** — structured incident submission with severity classification; management and dispatch are notified immediately
- **Training management** — track training assignments, session completion, and trainee progression
- **Audit log** — every approval, rejection, and role change is recorded with actor, timestamp, and before/after state
- **Walker performance analytics** — aggregate ratings, attendance trends, and route reliability data per walker

---

## Technical Overview

AsheFlow is a production-ready web application. It is not a prototype or a script.

| Component | Technology |
|---|---|
| Backend API | Python / FastAPI |
| Database | PostgreSQL with full schema migrations |
| Authentication | AWS Cognito — role-based access control (Driver, Walker, Trainer, Trainee, Dispatch, Management, Admin) |
| Discord Bot | Python / discord.py — integrated with the backend via secure internal webhook |
| Frontend | React / TypeScript — responsive web app |
| Infrastructure | Docker — all services containerized and portable |
| Scheduled Jobs | Celery Beat — for deadline enforcement, cleanup tasks, and future automated scheduling |

The system is designed to scale. Adding a second company's workforce is a configuration change, not a rebuild.

---

## Proposed Pilot Program

I propose a **two-week shadow pilot** with zero disruption to current operations.

**How it works:**
- Current manual dispatch continues exactly as it does today
- AsheFlow runs in parallel, generating its own assignment each morning
- At the end of each day, we compare the algorithmic assignment to the manual one on speed, constraint compliance, and pairing quality
- No crew member, driver, or manager interacts with the system unless they choose to

**What this proves:**
- The algorithm produces valid, constraint-compliant assignments every time
- The time saved on daily dispatch (estimated 45–90 minutes per morning)
- The reduction in reassignment events caused by missed constraints
- The system's reliability before any operational dependency is placed on it

At the end of two weeks, the data speaks for itself. There is no obligation to proceed.

---

## Engagement Model

I designed, architected, and developed AsheFlow independently, outside of work hours, as a proprietary software project. I am offering to deploy and maintain it for our operations under a formal licensing or service agreement.

**What I am proposing:**
- A licensing agreement for use of the AsheFlow platform by our operation
- Ongoing maintenance, updates, and support as part of the agreement
- Customization and feature additions commissioned separately as needs evolve

I am fully open to discussing the structure of this arrangement — whether that takes the form of a monthly license fee, a one-time deployment fee plus retainer, or another model that works for the organization.

**What this is not:**
- This is not a request to build something. The system is already built and running.
- This is not a request for company resources, infrastructure, or budget to develop anything.
- This is not a modification to my current employment terms.

---

## Next Step

I would like to schedule a **15-minute live demo** at your convenience. I can walk through the dispatch algorithm generating a real assignment, show the Discord confirmation flow end-to-end, and demonstrate the management dashboard.

There is no pressure and no commitment required from this meeting. I simply want you to see what it does.

Please let me know what time works best.

---

[Author]  
[Your Title] / Independent Software Developer & Solutions Architect  
[Email] | [Phone]
