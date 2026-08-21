"""
Seed the 4-phase training curriculum for AsheFlow (walker + driver tracks).

Run after the 83e4cd66249c migration is applied:
    docker compose exec backend python scripts/seed_training_curriculum.py

Idempotent — checks for existing topics by (company_id, day_number, topic_title).
Safe to re-run. On re-run it UPDATES `roles`, `description` and `category` on
existing rows rather than skipping them, so the ADR-263 role backfill and the
ADR-262 DSB reframes reach companies that were seeded before those changes.
Identity is (day_number, topic_title) — everything else is an attribute.

Source: NYCD walker training Google Form + ADP timekeeping compliance email;
driver track from docs/TRAINING_MODULE_DRIVER.md.
Design: ADR-046 (phases), ADR-263 (role scoping), ADR-262 (thresholds).

NOTE (ADR-262): do not write numeric scorecard thresholds into any description.
Targets are per-DSP and live on CompanyConfig — a literal here is wrong for every
tenant that is not the one it was written for.
"""

import sys
import os

# Allow running from repo root or from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models.training import TrainingCurriculum
from _seed_guard import assert_seedable, seed_targets

# ---------------------------------------------------------------------------
# Curriculum data
# (phase, topic_title, description, category, is_mandatory, roles)
#
# `roles` (ADR-263) is multi-valued: a shared item is ONE row carrying both
# tracks, not two rows that drift apart. ["walker"] reaches walkers/trainees,
# ["driver"] reaches drivers, ["walker", "driver"] reaches both.
#
# Phase 4 is NOT seeded — it is auto-generated at dispatch time from mandatory
# Phase 1–3 items as demonstration tasks. Every mandatory item added here becomes
# an observed demonstration, so mark conceptual items is_mandatory=False where a
# trainer cannot physically watch the trainee perform them.
# ---------------------------------------------------------------------------
CURRICULUM: list[tuple[int, str, str | None, str, bool, list[str]]] = [
    # ── Phase 0 — the ORE day (ADR-281) ─────────────────────────────────────
    # ORE itself is Amazon's course on AtoZ; AsheFlow neither hosts nor tracks
    # its content, and the certificate upload is what evidences completion.
    # These three are the only things a TRAINER does on this day, which is why
    # the phase is short: everything else that day happens inside AtoZ.
    #
    # WALKER TRACK ONLY. ORE is the walker onboarding course; the driver track
    # does not have a phase 0, and a driver_trainee starts at phase 1. Marking
    # these ["walker", "driver"] would give every new driver an ORE day they
    # can never complete — no certificate exists for them to upload, so the
    # phase would never close and they would be stuck before phase 1.
    (0, "AsheFlow app: install and first login",
     "Install the AsheFlow app and confirm the new hire can log in with their "
     "own credentials. Covers password reset if the invite has expired.",
     "app_setup", True, ["walker"]),
    (0, "Website access",
     "Show where the web app lives and confirm the new hire can reach it and "
     "sign in. Covers which surfaces are web-only versus in the app.",
     "app_setup", True, ["walker"]),
    (0, "Procedure walkthrough",
     "Walk through the procedures on the page with the new hire — what they "
     "will be asked to do each day and where each action lives.",
     "policy", True, ["walker"]),


    # -----------------------------------------------------------------------
    # PHASE 1 — Orientation & Setup
    # -----------------------------------------------------------------------
    (1, "Discord: tagging and usage, assignment posting time (8:00–8:20 AM)",
     "Trainer walks through the Discord server: how to tag correctly, when "
     "daily assignments are posted (between 8:00–8:20 AM), and how to read "
     "your assignment notification.",
     "app_setup", True, ["walker", "driver"]),

    (1, "Amazon AZ: schedule is sent out Thursday weekly",
     "The DA's weekly schedule is published via Amazon AZ every Thursday. "
     "Ensure the DA knows how to access and read their schedule.",
     "app_setup", True, ["walker", "driver"]),

    (1, "ADP: payroll is submitted Monday weekly",
     "Payroll is processed every Monday. DA must ensure their timecard is "
     "complete and accurate before the Monday cutoff.",
     "app_setup", True, ["walker", "driver"]),

    (1, "Amazon Flex: transportation settings (walker vs. driver)",
     "Walk through the Amazon Flex app transportation settings. Walkers must "
     "be set to 'walker' mode, not driver mode. Show the DA where this setting "
     "is and confirm it is correct.",
     "app_setup", True, ["walker"]),

    (1, "ADP: clock in/out using badge number",
     "DA clocks in and out using their badge number — not a PIN or username. "
     "Walk through the clock-in process on the ADP terminal.",
     "policy", True, ["walker", "driver"]),

    (1, "ADP: all timecard edits submitted via ADP Mobile App or web portal only",
     "Any punch corrections or timecard edits must be submitted through the "
     "ADP Mobile App or web portal. Edits cannot be submitted verbally or via "
     "text message.",
     "policy", True, ["walker", "driver"]),

    (1, "ADP: timecard must be 100% accurate and submitted by Sunday midnight",
     "The DA's timecard must be fully accurate and submitted by Sunday midnight. "
     "The official ADP payroll cutoff is Monday at 8 AM, but Sunday midnight is "
     "taught as the cutoff to prevent last-minute human errors. Missing or "
     "incorrect entries (no lunch break, wrong times) will result in removal "
     "from the schedule.",
     "policy", True, ["walker", "driver"]),

    (1, "ADP: review timecard daily for accuracy",
     "DA should check their timecard each day to catch missing punches or "
     "incorrect times before they accumulate. Instruct DA on where to find "
     "their daily timecard in ADP.",
     "policy", True, ["walker", "driver"]),

    (1, "ADP: missing punches or incorrect times result in schedule removal",
     "Company policy: incomplete or inaccurate timecards prevent payroll "
     "processing. Consequences include removal from the schedule. This is "
     "non-negotiable.",
     "policy", True, ["walker", "driver"]),

    (1, "ADP: use 'Forgot username/password' immediately if credentials are lost",
     "If the DA cannot log in to ADP, they must use the self-service recovery "
     "option immediately — do not wait until payday. Show the DA the recovery "
     "flow.",
     "policy", True, ["walker", "driver"]),

    (1, "Discord: immediate communication for shift issues (replaced Amazon Chime)",
     "Discord is the company's primary real-time communication tool for the shift. "
     "Amazon Chime was the previous platform and is no longer used. All delivery "
     "issues, truck room alerts, and dispatch notifications happen in Discord. "
     "DAs must have Discord installed and notifications enabled.",
     "app_setup", True, ["walker", "driver"]),

    (1, "Contact: Dispatch for delivery/route issues, HR for HR issues",
     "For any delivery or route-related problems during the shift, contact "
     "Dispatch via Discord. For HR matters (payroll, scheduling, policy), email "
     "hr@yourdsp.com.",
     "policy", True, ["walker", "driver"]),

    (1, "Attendance policy: 24-hour notice required for callout via HR email",
     "If the DA cannot work their scheduled shift, they must email HR at "
     "hr@yourdsp.com at least 24 hours in advance.",
     "policy", True, ["walker", "driver"]),

    (1, "Attendance policy: 2 no-call-no-shows = schedule removal (job abandonment)",
     "Two no-call-no-show incidents results in removal from the schedule, "
     "which is treated as job abandonment.",
     "policy", True, ["walker", "driver"]),

    (1, "Flex activation: request work block from Driver / Driver activates from station",
     "To get activated in Amazon Flex so the DA can begin scanning, they must "
     "request a work block from their assigned Driver, or the Driver activates "
     "them from the station.",
     "policy", True, ["walker"]),

    (1, "Bonus hours: eligibility, disqualifiers, and shift time",
     "Bonus hours are discretionary and based on performance and attendance. "
     "Disqualifiers: poor attendance, leaving early, low package count, poor "
     "scorecard. Standard shift: 10:30 AM – 5:30 PM with mandatory 30-minute "
     "unpaid lunch from 1:00–1:30 PM.",
     "policy", True, ["walker", "driver"]),

    (1, "NY State law: mandatory 30-min unpaid lunch when working 6+ hours",
     "New York State law requires a mandatory 30-minute unpaid lunch break when "
     "working 6 or more hours. This must be recorded in the DA's time card "
     "between 11 AM and 2 PM in both Flex and ADP.",
     "policy", True, ["walker", "driver"]),

    # -----------------------------------------------------------------------
    # PHASE 2 — Delivery Standards
    # -----------------------------------------------------------------------
    (2, "Keys to Success: always verify address and check the GeoPin before delivery",
     "Before delivering, always confirm the physical address matches what is "
     "shown in the app and that the GeoPin is at the correct location.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: what to do when GeoPin is wrong",
     "If the GeoPin is in the wrong location, use the physical address on the "
     "label. Enable Airplane mode as needed to prevent the GeoPin from "
     "overriding the correct delivery location.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: always check labels in a group stop for mixed packages",
     "In a group stop, scan each label carefully — packages from other addresses "
     "may be mixed in. Delivering a package to the wrong address is a controlled "
     "DNR.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: knock on door and ring bell to alert customer",
     "Always knock and ring the bell. This alerts the customer to the delivery "
     "and reduces the chance of a missed-delivery complaint.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: direct-to-customer protocol (name, Flex entry, signature)",
     "When delivering directly to a customer, verify their name. If someone "
     "other than the customer accepts the package, get their first and last name, "
     "enter it in the Amazon Delivery App, and obtain a signature.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: deliver to physical location — do not deliver beyond GeoPin",
     "Delivering to the best option means delivering to the physical location. "
     "Do not deliver to a location that is beyond the GeoPin — this triggers a "
     'Delivered >50m DNR.',
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: unsecure location — call and text the customer to confirm",
     "If asked to leave a package in an unsecure location, call and text the "
     "customer first to confirm. Document the interaction.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: NEVER deliver to a customer's mailbox",
     "Delivering to a mailbox is a federal offense. Always deliver to the "
     "door, a secure location, or directly to the customer.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: scan delivered packages with correct reason codes",
     "Use the correct reason code when marking a package as delivered or "
     "undeliverable. Incorrect codes affect scorecard metrics and can generate "
     "customer complaints.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: take a clear POD photo including surroundings",
     "Take a clear photo showing the package and its surroundings so the "
     "customer can locate it. Retake if the first photo is poor quality. "
     "This is the DA's best proof of delivery.",
     "delivery_standards", True, ["walker"]),

    (2, "Keys to Success: avoid marking 'household member' where an alternative exists",
     "Marking a delivery as 'household member' arms a DSB defect: if the customer "
     "later claims the package was never received, you take a DSB defect on top of "
     "the DNR. Avoid it wherever a valid alternative exists. It is NOT universally "
     "forbidden — some packages (one-time-password deliveries) REQUIRE it. When "
     "someone other than the customer accepts, follow the direct-to-customer "
     "protocol: get their first and last name, enter it in the Amazon app, and get "
     "a signature. That record is what defends you later.",
     "delivery_standards", True, ["walker"]),

    (2, "Delivery priority hierarchy: Front Door → Safe Location → Receptionist → Contact Customer → Customer Support → RTS",
     "Always attempt the customer's preferred delivery method first (usually Front Door). "
     "If unavailable, attempt in this order: (1) Front Door, (2) Another Secure/Safe Location, "
     "(3) Receptionist. If all physical options fail: (4) Contact the customer to arrange "
     "a delivery method — check notes for any guidance first. (5) Contact Customer Support "
     "if the customer cannot be reached or cannot resolve the issue. (6) RTS (Return to Station) "
     "is the absolute last resort after all other options are exhausted. Never skip steps.",
     "delivery_standards", True, ["walker"]),

    (2, "Scorecard overview: DSB, POD, CDF, CC — what each metric is and why it matters",
     "DSB (Delivery Success Behaviors): risky behaviors that convert a customer's "
     "not-received claim into a SECOND defect. "
     "POD (Photo on Delivery): photo quality and defect avoidance. "
     "CDF (Customer Delivery Feedback): customer ratings triggered at Swipe to Finish. "
     "CC (Contact Compliance): required on every delivery attempt that triggers it.",
     "scorecard", True, ["walker", "driver"]),

    (2, "DSB: Delivery Success Behaviors — the conditional metric, and why it is not 'don't do X'",
     "DSB is the most misunderstood line on the card because it is CONDITIONAL. "
     "Four risky behaviors are tracked: (1) marking multiple deliveries at the same "
     "time, (2) delivering more than 50m from the GeoPin, (3) marking delivered to "
     "household member, (4) delivering with no POD. None of these is a defect on "
     "its own. They score against you ONLY IF a customer later claims the package "
     "was not received (a DNR). Behavior alone = nothing. DNR alone = a DNR defect. "
     "Behavior PLUS a DNR claim = a DSB defect on top of it — one customer claim, "
     "two defects. The right mental model is EVIDENCE, not rules: each risky "
     "behavior destroys the proof that would have defended you when the claim "
     "arrives. You cannot control whether a customer files a claim. You can only "
     "control whether you are defensible when they do.",
     "scorecard", True, ["walker", "driver"]),

    (2, "DSB: the three controllable levers",
     "Outside the unfair cases, three habits control your entire DSB score. "
     "(1) DO NOT select multiple deliveries at once at grouped stops — scan and "
     "complete each package individually, even though batching feels faster. "
     "(2) SWIPE TO FINISH AT THE DELIVERY LOCATION — not walking back to the cart, "
     "not at the truck, not at the next stop. This single habit controls the >50m "
     "trigger and is the highest-yield DSB behavior you have. (3) AVOID marking "
     "delivered to household member wherever a valid alternative exists. Confirm "
     "the DA can state all three from memory.",
     "scorecard", True, ["walker", "driver"]),

    (2, "DSB: the three unfair cases — when you did everything right and still take the hit",
     "Tell new DAs this honestly and early. Three situations produce a DSB defect "
     "even when the DA follows procedure correctly. (1) WRONG GEOPIN: you deliver "
     "to the correct physical address, but Amazon's GeoPin is in the wrong place "
     "and the real location is >50m from it — this counts against you EVEN IF the "
     "GeoPin is corrected later. (2) OTP TO HOUSEHOLD MEMBER: the package requires "
     "a one-time password and delivery to a household member is REQUIRED, you "
     "comply correctly — still counts. (3) CUSTOMER DISABLED POD: the customer "
     "turned photo-on-delivery off for their address so you were never prompted — "
     "still counts. These are not the DA's fault, they are the strongest appeal "
     "candidates on the card, and the DA should flag them the day they happen "
     "rather than discovering them on a scorecard weeks later. Say this out loud "
     "in training: a DA who hits one of these after being told 'just follow the "
     "rules' stops believing the rest of the training.",
     "scorecard", True, ["walker", "driver"]),

    # -----------------------------------------------------------------------
    # PHASE 3 — Delivery Types & Edge Cases
    # -----------------------------------------------------------------------
    (3, "DSB: delivered >50 meters — swipe at the door, and the wrong-GeoPin case",
     "Marking a package delivered more than 50m from the GeoPin arms a DSB defect "
     "that fires if the customer later claims non-receipt. THE CONTROLLABLE FIX "
     "COMES FIRST: swipe to finish AT the delivery location. Most >50m events are "
     "not bad GeoPins — they are DAs swiping after walking back toward the cart or "
     "truck. Second, the genuine wrong-GeoPin case: deliver to the physical address "
     "on the label, not to the pin. Airplane mode prevents a bad GeoPin from "
     "pulling you off the correct location. If the pin was wrong and a DNR is "
     "claimed anyway, that is one of the three unfair cases — flag it for appeal "
     "the same day.",
     "scorecard", True, ["walker", "driver"]),

    (3, "POD: photo requirements — no totes, wheels, humans, up-close shots; adequate lighting",
     "POD photos must not include: totes, wheels/carts/racks, humans, or "
     "up-close shots where the package fills the frame. Adequate lighting is "
     "required. The photo must show the package and its surroundings clearly.",
     "scorecard", True, ["walker"]),

    (3, "POD: 8 primary photo defect types",
     "The 8 defect types are: Blurry, Package Too Close, Package Not Clearly "
     "Visible, No Package, Package in Photo Wrong Orientation, Vehicle in Photo, "
     "Photo Too Dark, Package Not Present. Walk through examples of each.",
     "scorecard", True, ["walker"]),

    (3, "POD: bypass bucket flow — '?' → Help → Unable to take photo → reason → Submit",
     "If the DA genuinely cannot take a photo: tap '?' in the delivery screen, "
     "select Help, select 'Unable to take photo', enter the reason, and tap "
     "Submit. Do NOT bypass POD without using this flow.",
     "scorecard", True, ["walker"]),

    (3, "CDF: customer delivery notification trigger and DA-attributable feedback categories",
     "At Swipe to Finish, the customer receives a notification and can rate the "
     "DA. Positive attributable feedback: Friendly, Delivered with care, Above & "
     "beyond, Followed instructions, Respectful of property, On time. Negative "
     "attributable feedback: Late, Wrong address, Didn't follow instructions, "
     "Never received, Mishandled, Unprofessional.",
     "scorecard", True, ["walker"]),

    (3, "Contact Compliance: NEVER close the 'Having trouble?' prompt — call then text",
     "When the 'Having trouble with your delivery?' prompt appears, NEVER close "
     "it. The required workflow is: Call customer → wait at least 3 rings → "
     "Text customer → then proceed. Closing the prompt skips Contact Compliance "
     "and affects the CC metric.",
     "scorecard", True, ["walker"]),

    (3, "Contact Compliance: no phone / disconnected / LAN line — driver support workflow",
     "If there is no phone number, the number is disconnected, or it is a LAN "
     "line: contact Driver Support → wait at least 3 rings → open a support "
     "chat → send a message. Always call Driver Support if having issues.",
     "scorecard", True, ["walker"]),

    (3, "Locker delivery: how to deliver and mark, common issues (full/broken locker)",
     "Walk through the complete locker delivery flow in Amazon Flex. Common "
     "issues: locker full (select the correct reason code and reattempt or "
     "return), locker broken (contact Driver Support, document the issue).",
     "delivery_types", True, ["walker"]),

    (3, "Floor walk-up buildings: mark in Flex, contact customer, common issues, lobby dumping",
     "Walk through floor walk-up delivery: how to mark correctly in Flex, when "
     "and how to contact the customer, common issues (locked lobby, no answer). "
     "Lobby dumping (leaving packages in the lobby without delivering to the "
     "door) is prohibited.",
     "delivery_types", True, ["walker"]),

    (3, "Secure delivery location: how to mark a secure delivery location",
     "A secure delivery location is a pre-approved spot designated by the "
     "customer. Walk through how to identify it in the delivery notes and how "
     "to mark it correctly in Flex.",
     "delivery_types", True, ["walker"]),

    (3, "Bulk building drops: doorman and mailroom as bulk-drop methods, PODs required",
     "Doorman and Mailroom are bulk-drop delivery methods used when delivering "
     "multiple packages to a building at once — they are not primary walker delivery "
     "methods. Doorman: always get the doorman's name and record it in Flex (e.g. "
     "'Paul - doorman, accepted delivery'). If doorman denies access, record that too. "
     "Mailroom: hand packages directly to mailroom staff; get a name if possible. "
     "POD photos are required for all bulk drops. Other delivery methods: Front Door, "
     "Another Secure Location, Receptionist, and direct to customer.",
     "delivery_types", True, ["walker"]),

    (3, "RTS (Return to Station): definition, procedure, and when it applies",
     "RTS means returning an undelivered package to the station. It is the last resort "
     "after all delivery attempts and escalations have failed. Procedure: (1) Attempt "
     "preferred delivery method (e.g. Front Door). (2) If access is unavailable and no "
     "Safe Location exists, attempt Contact Compliance — message customer first, then "
     "call until voicemail (do NOT hang up before 2 rings). (3) Contact Driver Support "
     "if customer cannot be reached. (4) If Driver Support cannot resolve the issue, "
     "they authorize the RTS procedure. (5) Reattempt delivery at a later time during "
     "the route if possible before returning to station. Mark with correct reason code.",
     "delivery_types", True, ["walker"]),

    (3, "RTS: Not Deliverable — when and how to determine",
     "A package is Not Deliverable after calling AND texting the customer and "
     "reattempting delivery at least 2 more times. Ringing the doorbell once with "
     "no answer is NOT sufficient. Attempting delivery 1 time and getting no response "
     "is NOT sufficient. All Contact Compliance steps must be completed before marking "
     "Not Deliverable.",
     "delivery_types", True, ["walker"]),

    (3, "DNR (Did Not Reattempt): definition and how to avoid one",
     "DNR means the associate did not follow the full delivery attempt procedure before "
     "marking a package undeliverable. A DNR is triggered when: the DA skips Contact "
     "Compliance, marks Not Deliverable after only 1 attempt, or fails to reattempt "
     "delivery later in the route when it was possible to do so. Prevention: always "
     "follow the full delivery hierarchy (Front Door → Safe Location → Receptionist → "
     "Contact Customer → Customer Support → RTS), complete all Contact Compliance steps, "
     "and reattempt before marking final.",
     "scorecard", True, ["walker"]),

    (3, "Business closed: procedure when you cannot deliver to a closed business",
     "If a business is closed and you cannot complete the delivery: (1) Mark 'Business "
     "Closed' as the reason code in the Amazon Flex app. (2) Send an alert in the DS "
     "Chime/Discord truck room notifying Dispatch and your Driver. (3) Return the package "
     "to the truck. Do not leave the package outside or in an unsecured location.",
     "delivery_types", True, ["walker"]),

    (3, "Mailroom full: procedure when the mailroom cannot accept more packages",
     "If the mailroom is full and cannot accept the delivery: (1) Contact the customer "
     "to arrange an alternative delivery location. (2) Check delivery notes for any "
     "guidance. (3) Attempt an available alternative (e.g. receptionist, Front Door). "
     "(4) If no alternative is available, contact Customer Support. (5) If unresolved, "
     "begin RTS procedure. Never leave packages in a full or unattended mailroom.",
     "delivery_types", True, ["walker"]),

    (3, "Stolen vs. missing package: how to handle each",
     "Missing package: mark the package as missing in Amazon Flex and send an alert "
     "in the Discord truck room to notify Dispatch and your Driver immediately. "
     "Stolen package: complete an incident report (detailed in the Incidents section "
     "of company procedure), mark the package as missing in Amazon Flex, and notify "
     "Dispatch and Driver via the Discord truck room. The incident report is required "
     "for stolen packages — it is not required for missing packages.",
     "delivery_types", True, ["walker"]),

    # =======================================================================
    # DRIVER TRACK (ADR-263) — docs/TRAINING_MODULE_DRIVER.md
    #
    # Shared Phase 1 policy (ADP, Discord, attendance, NY lunch law) and the
    # Phase 2 scorecard-literacy/DSB block already carry ["walker", "driver"]
    # above and are NOT repeated here.
    #
    # is_mandatory=False on items a trainer cannot physically observe — they are
    # covered and quizzed (Phase 5) rather than mirrored into Phase 4
    # demonstrations. See "Phase 4 caveat" in the module doc.
    # =======================================================================

    # ---- PHASE 1 — credentials & vehicle basics ---------------------------
    (1, "Driver credentials: license class, MVR standard, and reporting a citation",
     "Confirm the DA holds a valid license appropriate to the vehicle, that their "
     "record meets the company and Amazon MVR standard, and that they understand "
     "the obligation to self-report any citation, suspension, or accident — on or "
     "off duty — to HR and Dispatch immediately. A license issue discovered on the "
     "day is a cancelled route; one discovered by an audit is a compliance breach.",
     "policy", True, ["driver"]),

    (1, "Netradyne: what the camera is, what it records, and how it is used",
     "Set expectations honestly on day one — this is the topic that most damages "
     "new driver trust when it is discovered rather than explained. The Driveri "
     "unit records continuously and uploads footage to Amazon's safety review team "
     "when any of roughly 16 signal categories trigger (speeding, distraction, "
     "seatbelt, sign/signal, following distance, harsh braking, and others). "
     "Onboard AI recognises speed-limit signs, stop signs, traffic lights and "
     "pedestrians, so it adds context rather than just detecting motion. It also "
     "awards positive recognition for clean driving. Frame it accurately: the "
     "footage that clears a driver in a not-at-fault collision is the same footage "
     "that flags a rolling stop.",
     "vehicle_safety", False, ["driver"]),

    (1, "FICO Safe Driving Score: what it is and what moves it",
     "A 100–850 score (higher is better) derived from telematics: acceleration, "
     "braking, cornering, phone distraction, and speeding — weighted by both how "
     "OFTEN an event happens and how SEVERE it is. Your company's target is set in "
     "AsheFlow config; ask your manager for the current number. The severity "
     "weighting is the practical lesson: one hard emergency stop hurts less than a "
     "persistent habit of late braking at every light.",
     "vehicle_safety", False, ["driver"]),

    (1, "Vehicle familiarisation: your assigned van, EV handling, and blind spots",
     "Before the first route: seat and mirror setup, where the DVIC checklist "
     "lives, fuel or charge procedure, and the vehicle's blind spots walked "
     "physically from outside. For electric vans, cover regenerative braking feel "
     "and the range behaviour that differs from a gas vehicle. A driver who has "
     "never sat in the van before dispatch morning will adjust mirrors on the road.",
     "vehicle_safety", True, ["driver"]),

    # ---- PHASE 2 — safety & DVIC ------------------------------------------
    (2, "DVIC: pre-trip inspection — the full checklist, every day, before departure",
     "Required before leaving the station, every driver, every day. Covers: tires "
     "(condition, inflation, tread depth), lights (headlights, brake lights, turn "
     "signals, hazards), visible fluid levels, an initial brake function test, "
     "windshield and mirrors, seatbelts, horn, and any dashboard warning lights. "
     "Complete it honestly and sign off. A tire flagged at 06:00 costs five "
     "minutes; the same tire discovered mid-route is a roadside failure, a rescue, "
     "late stops, and undelivered packages — one skipped check damages On-Time, "
     "DCR, and Safety & Compliance simultaneously.",
     "vehicle_safety", True, ["driver"]),

    (2, "DVIC: post-trip inspection — the one everyone skips",
     "Required on return, and the commonly-skipped one because of end-of-shift "
     "fatigue. It documents what developed DURING the route: new warning lights, "
     "delivery-related body damage, fluid leaks, changes in brake feel. The timing "
     "is the whole point — a defect logged at 19:00 gives maintenance all night to "
     "fix it; the same defect found at 06:00 tomorrow costs a route. Never sign off "
     "a post-trip you did not actually perform: a false inspection discovered in an "
     "audit is a compliance finding, not a paperwork error.",
     "vehicle_safety", True, ["driver"]),

    (2, "Safety metrics: speeding, sign/signal, seatbelt, distraction, following distance",
     "The named Netradyne-fed rates and what triggers each. SPEEDING: typically "
     "triggers at roughly 20% over the limit sustained for 60+ seconds — this is "
     "why brief passing is rarely flagged but cruising 15 over on an arterial "
     "always is. SIGN/SIGNAL: stop-sign violations and illegal U-turns count once; "
     "STOP-LIGHT violations are weighted about TEN TIMES heavier — running a red is "
     "worth ten rolling stops, and you should be told that asymmetry explicitly. "
     "SEATBELT: any detected unfastened instance while moving; the belt goes on "
     "before the vehicle does, at every single stop. DISTRACTION: phone or handheld "
     "use while the vehicle is in motion, the most severely weighted of all. "
     "FOLLOWING DISTANCE: sustained tailgating. Confirm the driver can state what "
     "triggers each.",
     "vehicle_safety", True, ["driver"]),

    (2, "Safety: the three-in-one pattern — speeding, braking, and following distance",
     "A driver flagged for harsh braking AND following distance AND speeding does "
     "not have three problems. It is one driving style — following too closely "
     "forces late braking, and rushing causes both. Coaching all three separately "
     "fails; the fix is a single behaviour change: increase following distance, and "
     "the braking and speeding events fall away with it. Teach the pattern so the "
     "driver can self-diagnose from their own event list.",
     "vehicle_safety", False, ["driver"]),

    (2, "Safety: parking, reversing, and the urban delivery stop",
     "Reversing is a top exposure risk and much of it is avoidable by choosing the "
     "stop. Prefer a pull-through or a position that does not require backing. When "
     "backing is unavoidable: get out and look before reversing, use a spotter when "
     "one is available, and go slow. In dense NYC conditions also cover: never block "
     "a hydrant, bus stop, or crosswalk; hazards on and engine off when leaving the "
     "vehicle; secure the cargo area every time; and the fact that an illegally "
     "parked van generates customer escalations from residents, not just tickets.",
     "vehicle_safety", True, ["driver"]),

    (2, "Scorecard literacy: the DSP card, the categories, and the Safety cap",
     "Show the driver an actual weekly card. Categories and weights: Safety & "
     "Compliance 40%, Quality 30%, Team 30%. Tiers best to worst: Fantastic+, "
     "Fantastic, Great, Good, Fair, At Risk. THE CAPPING RULE IS THE KEY LESSON: if "
     "Safety & Compliance grades 'Great', the overall standing CANNOT exceed 'Great' "
     "no matter how perfect Quality and Team are. Safety is a ceiling, not one "
     "average input among several. A driver who understands this stops treating "
     "safety as the category they can trade away for speed.",
     "scorecard", False, ["driver"]),

    # ---- PHASE 3 — load custody, crew custody, on-road --------------------
    (3, "Load custody: dock assignment, staging, and the pre-load walk",
     "Dispatch assigns your dock zone before the pre-trip inspection; you see it on "
     "your FieldOps page. Walk the assigned zone before loading: confirm the totes "
     "staged there are yours, and raise a mismatch with Dispatch in Discord BEFORE "
     "loading rather than after departure. A tote loaded onto the wrong truck is "
     "not a driver inconvenience — it strands a walker's packages and becomes DCR "
     "defects across every customer in that tote.",
     "crew_ops", True, ["driver"]),

    (3, "Load custody: tote check-off and load confirmation",
     "Check each tote onto the truck deliberately — this is a custody record, not a "
     "formality. Confirm the load when and only when the truck is actually "
     "complete. Partial confirmation is supported when it is genuinely partial; "
     "what is not acceptable is confirming a load you have not verified. Once "
     "confirmed, the check-off locks and reopening requires an explicit unconfirm — "
     "so confirm carefully rather than confirming early and correcting later.",
     "crew_ops", True, ["driver"]),

    (3, "Load custody: the manifest, package counts, and reporting a discrepancy",
     "Record the package/tote counts at station load time accurately. A count "
     "entered wrong at load time makes every downstream reconciliation wrong and "
     "turns a recoverable missing-package investigation into an unresolvable one. "
     "If the count does not match, say so at the dock, in the app, in Discord — "
     "before you leave. A discrepancy reported at the station is an operations "
     "problem; the same discrepancy reported from the route is a loss.",
     "crew_ops", True, ["driver"]),

    (3, "Crew custody: activating walkers in Flex and starting the crew's day",
     "Walkers cannot scan until they are activated. You either activate them from "
     "the station or respond to their work-block request. This is a blocking "
     "dependency — an unactivated walker is a walker standing still, and their idle "
     "time becomes your truck's late stops. Cover the mechanics and the expectation "
     "that activation happens promptly, not when convenient.",
     "crew_ops", True, ["driver"]),

    (3, "Crew custody: crew status through the day and the mid-route check-in",
     "You are the field supervisor for your truck. Know where your crew is, whether "
     "they are progressing, and whether anyone is struggling before it becomes a "
     "late truck. Cover: reading crew status, when to redistribute work, when to "
     "escalate to Dispatch rather than absorbing the problem, and the fact that a "
     "walker who goes quiet is an incident until proven otherwise. Contact them.",
     "crew_ops", True, ["driver"]),

    (3, "Crew custody: RTS collection, clearance, and confirming all crew are aboard",
     "At end of route: collect RTS from every walker, verify the count, and confirm "
     "crew clearance before departing the AP. Confirming that all crew are back on "
     "the truck is a one-way safety stamp — never confirm it without physically "
     "verifying. Leaving a crew member behind is the most serious operational "
     "failure available to a driver, and it is entirely prevented by a headcount "
     "you actually performed.",
     "crew_ops", True, ["driver"]),

    (3, "Station handoff: returning RTS and totes at end of shift",
     "Submit the station handoff after physically returning RTS packages and totes "
     "— in that order, physical first, record second. The handoff is one record per "
     "driver per day and it closes the custody chain that began at the dock. An RTS "
     "package recorded as returned but sitting in the van is a package that will be "
     "reported missing, investigated, and charged against the walker who correctly "
     "handed it to you.",
     "crew_ops", True, ["driver"]),

    (3, "On-road: rescue routes — receiving help and giving it",
     "A rescue is another DA taking part of your route to get it finished. "
     "Receiving one is not a failure — requesting it EARLY is the professional "
     "behaviour, because a rescue requested at 15:00 saves the stops that a rescue "
     "requested at 18:00 cannot. Cover how to signal you are behind, how rescues "
     "are dispatched, and the reciprocal expectation when you are the one with "
     "capacity. Undelivered packages hit DCR regardless of whose route they were on.",
     "delivery_standards", False, ["driver"]),

    (3, "On-road: the rushing paradox — why time pressure is usually not your fault",
     "Nearly every defect on the card is downstream of rushing, and rushing is "
     "usually an operations problem — late dispatch, an overloaded route, a missing "
     "crew member — not a driver problem. Two things follow. For the driver: the "
     "correct response to being behind is to ESCALATE, not to drive faster; "
     "speeding to recover 10 minutes generates safety events that cost far more "
     "than the 10 minutes. For the trainer: if several drivers show the same defect "
     "on the same day, coach Dispatch, not the drivers.",
     "vehicle_safety", False, ["driver"]),

    (3, "Incidents: collisions, property damage, injuries, and the first 10 minutes",
     "Cover the sequence: stop, ensure safety, call emergency services if anyone is "
     "hurt, notify Dispatch and Driver Support immediately, do not admit or assign "
     "fault, photograph everything, collect the other party's information, and file "
     "the incident report the same day. Emphasise that the Netradyne footage exists "
     "and frequently EXONERATES the driver — which is exactly why your own account "
     "must be accurate and prompt rather than defensive. Also cover the "
     "non-collision incidents that must be reported: property damage, a dog bite, a "
     "hostile customer, a theft from the van.",
     "policy", False, ["driver"]),

    (3, "Compliance: hours of service, breaks, and why the clock is not negotiable",
     "Working Hours Compliance is a pass/fail gate on the DSP scorecard — it is not "
     "tiered and there is no partial credit. Cover daily and weekly limits, "
     "required rest, and the NY State mandatory 30-minute unpaid lunch on 6+ hour "
     "shifts recorded in both Flex and ADP. A driver who works through lunch to "
     "finish the route has not helped: they have created a compliance breach that "
     "outweighs the stops they saved.",
     "policy", True, ["driver"]),
]


# Titles that were REPLACED by a retitled item rather than edited in place.
# The identity key is (day_number, topic_title), so a retitled correction is
# inserted as a NEW row and the superseded one survives unless it is deleted
# here — leaving both live at once. Migration 86b2aec7998f removes them from
# existing databases; this list stops the seed re-creating them, and keeps the
# seed self-sufficient for a fresh database that never ran that migration.
RETIRED_TITLES: list[str] = [
    "DSB: simultaneous deliveries — what it means, when to use, when NOT to use",
    "DSB: delivered to household member — what it means, why invalid, what to do instead",
    "DSB: delivered >50 meters — GeoPin wrong location, Airplane mode explained",
    "Keys to Success: NEVER mark 'household member'",
]


def seed(db, company_id) -> None:
    """Seed the static curriculum for ONE company.

    company_id is nullable=False on TrainingCurriculum, so it must be supplied —
    the curriculum is per-tenant. The existence check is company-scoped too, or a
    second company would be skipped because company A already has the row.
    """
    inserted = 0
    updated = 0

    # Remove superseded rows first, so a re-seed converges on the current set
    # rather than accumulating both the old and the retitled version.
    retired = db.query(TrainingCurriculum).filter(
        TrainingCurriculum.company_id == company_id,
        TrainingCurriculum.topic_title.in_(RETIRED_TITLES),
    ).all()
    for row in retired:
        db.delete(row)

    for phase, title, description, category, is_mandatory, roles in CURRICULUM:
        exists = db.query(TrainingCurriculum).filter(
            TrainingCurriculum.company_id == company_id,
            TrainingCurriculum.day_number == phase,
            TrainingCurriculum.topic_title == title,
        ).first()

        if exists:
            # UPDATE rather than skip. Identity is (day_number, topic_title);
            # roles/description/category are attributes that change as the
            # curriculum is corrected. Skipping would strand every already-seeded
            # company on the pre-ADR-263 roles and the pre-ADR-262 DSB text —
            # which is exactly the wrong framing this seed exists to replace.
            exists.description  = description
            exists.category     = category
            exists.is_mandatory = is_mandatory
            exists.roles        = list(roles)
            updated += 1
            continue

        item = TrainingCurriculum(
            company_id=company_id,
            day_number=phase,
            topic_title=title,
            description=description,
            category=category,
            is_mandatory=is_mandatory,
            roles=list(roles),
            record_type="coverage",  # all static curriculum items are coverage
        )
        db.add(item)
        inserted += 1

    db.commit()
    print(f"  {company_id}: {inserted} inserted, {updated} updated, {len(retired)} retired.")


if __name__ == "__main__":
    from app.models.company import Company

    db = SessionLocal()
    try:
        # ADR-280 D3: default is every SEEDABLE company, not every company.
        # This previously read `db.query(Company).all()` — on a database with a
        # live tenant that wrote a curriculum straight into real customer data.
        if len(sys.argv) > 1:
            # An explicit company id must still pass the guard — otherwise the
            # one path a human types by hand is the one with no protection.
            targets = [str(assert_seedable(db, sys.argv[1]).id)]
        else:
            targets = [str(c.id) for c in seed_targets(db)]
        if not targets:
            print("No seedable company — run seed_demo.py first.")
        for cid in targets:
            seed(db, cid)
        print("Curriculum seed complete.")
    finally:
        db.close()
