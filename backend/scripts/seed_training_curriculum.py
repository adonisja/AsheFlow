"""
Seed the 4-phase walker training curriculum for AsheFlow.

Run once after the a1b2c3d4e5f6 migration is applied:
    docker compose exec backend python scripts/seed_training_curriculum.py

Idempotent — checks for existing topics by (day_number, topic_title) before
inserting. Safe to re-run if partially applied.

Source: NYCD walker training Google Form + ADP timekeeping compliance email.
Design: ADR-046, docs/TRAINING-SYSTEM-IMPLEMENTATION-PLAN.md
"""

import sys
import os

# Allow running from repo root or from backend/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models.training import TrainingCurriculum

# ---------------------------------------------------------------------------
# Curriculum data
# (phase, topic_title, description, category, is_mandatory)
# Phase 4 is NOT seeded — it is auto-generated at dispatch time from mandatory
# Phase 1–3 items as demonstration tasks.
# ---------------------------------------------------------------------------
CURRICULUM: list[tuple[int, str, str | None, str, bool]] = [

    # -----------------------------------------------------------------------
    # PHASE 1 — Orientation & Setup
    # -----------------------------------------------------------------------
    (1, "Discord: tagging and usage, assignment posting time (8:00–8:20 AM)",
     "Trainer walks through the Discord server: how to tag correctly, when "
     "daily assignments are posted (between 8:00–8:20 AM), and how to read "
     "your assignment notification.",
     "app_setup", True),

    (1, "Amazon AZ: schedule is sent out Thursday weekly",
     "The DA's weekly schedule is published via Amazon AZ every Thursday. "
     "Ensure the DA knows how to access and read their schedule.",
     "app_setup", True),

    (1, "ADP: payroll is submitted Monday weekly",
     "Payroll is processed every Monday. DA must ensure their timecard is "
     "complete and accurate before the Monday cutoff.",
     "app_setup", True),

    (1, "Amazon Flex: transportation settings (walker vs. driver)",
     "Walk through the Amazon Flex app transportation settings. Walkers must "
     "be set to 'walker' mode, not driver mode. Show the DA where this setting "
     "is and confirm it is correct.",
     "app_setup", True),

    (1, "ADP: clock in/out using badge number",
     "DA clocks in and out using their badge number — not a PIN or username. "
     "Walk through the clock-in process on the ADP terminal.",
     "policy", True),

    (1, "ADP: all timecard edits submitted via ADP Mobile App or web portal only",
     "Any punch corrections or timecard edits must be submitted through the "
     "ADP Mobile App or web portal. Edits cannot be submitted verbally or via "
     "text message.",
     "policy", True),

    (1, "ADP: timecard must be 100% accurate and submitted by Sunday night",
     "The DA's timecard must be fully accurate and submitted every Sunday night "
     "for payroll. Missing or incorrect entries (no lunch break, wrong times) "
     "will result in removal from the schedule.",
     "policy", True),

    (1, "ADP: review timecard daily for accuracy",
     "DA should check their timecard each day to catch missing punches or "
     "incorrect times before they accumulate. Instruct DA on where to find "
     "their daily timecard in ADP.",
     "policy", True),

    (1, "ADP: missing punches or incorrect times result in schedule removal",
     "Company policy: incomplete or inaccurate timecards prevent payroll "
     "processing. Consequences include removal from the schedule. This is "
     "non-negotiable.",
     "policy", True),

    (1, "ADP: use 'Forgot username/password' immediately if credentials are lost",
     "If the DA cannot log in to ADP, they must use the self-service recovery "
     "option immediately — do not wait until payday. Show the DA the recovery "
     "flow.",
     "policy", True),

    (1, "Contact: Dispatch for delivery/route issues, HR for HR issues",
     "For any delivery or route-related problems during the shift, contact "
     "Dispatch. For HR matters (payroll, scheduling, policy), email "
     "TEAM@NYCDeliveryLLC.com.",
     "policy", True),

    (1, "Attendance policy: 24-hour notice required for callout via HR email",
     "If the DA cannot work their scheduled shift, they must email HR at "
     "TEAM@NYCDeliveryLLC.com at least 24 hours in advance.",
     "policy", True),

    (1, "Attendance policy: 2 no-call-no-shows = schedule removal (job abandonment)",
     "Two no-call-no-show incidents results in removal from the schedule, "
     "which is treated as job abandonment.",
     "policy", True),

    (1, "Flex activation: request work block from Driver / Driver activates from station",
     "To get activated in Amazon Flex so the DA can begin scanning, they must "
     "request a work block from their assigned Driver, or the Driver activates "
     "them from the station.",
     "policy", True),

    (1, "Bonus hours: eligibility, disqualifiers, and shift time",
     "Bonus hours are discretionary and based on performance and attendance. "
     "Disqualifiers: poor attendance, leaving early, low package count, poor "
     "scorecard. Standard shift: 10:30 AM – 5:30 PM with mandatory 30-minute "
     "unpaid lunch from 1:00–1:30 PM.",
     "policy", True),

    (1, "NY State law: mandatory 30-min unpaid lunch when working 6+ hours",
     "New York State law requires a mandatory 30-minute unpaid lunch break when "
     "working 6 or more hours. This must be recorded in the DA's time card "
     "between 11 AM and 2 PM in both Flex and ADP.",
     "policy", True),

    # -----------------------------------------------------------------------
    # PHASE 2 — Delivery Standards
    # -----------------------------------------------------------------------
    (2, "Keys to Success: always verify address and check the GeoPin before delivery",
     "Before delivering, always confirm the physical address matches what is "
     "shown in the app and that the GeoPin is at the correct location.",
     "delivery_standards", True),

    (2, "Keys to Success: what to do when GeoPin is wrong",
     "If the GeoPin is in the wrong location, use the physical address on the "
     "label. Enable Airplane mode as needed to prevent the GeoPin from "
     "overriding the correct delivery location.",
     "delivery_standards", True),

    (2, "Keys to Success: always check labels in a group stop for mixed packages",
     "In a group stop, scan each label carefully — packages from other addresses "
     "may be mixed in. Delivering a package to the wrong address is a controlled "
     "DNR.",
     "delivery_standards", True),

    (2, "Keys to Success: knock on door and ring bell to alert customer",
     "Always knock and ring the bell. This alerts the customer to the delivery "
     "and reduces the chance of a missed-delivery complaint.",
     "delivery_standards", True),

    (2, "Keys to Success: direct-to-customer protocol (name, Flex entry, signature)",
     "When delivering directly to a customer, verify their name. If someone "
     "other than the customer accepts the package, get their first and last name, "
     "enter it in the Amazon Delivery App, and obtain a signature.",
     "delivery_standards", True),

    (2, "Keys to Success: deliver to physical location — do not deliver beyond GeoPin",
     "Delivering to the best option means delivering to the physical location. "
     "Do not deliver to a location that is beyond the GeoPin — this triggers a "
     'Delivered >50m DNR.',
     "delivery_standards", True),

    (2, "Keys to Success: unsecure location — call and text the customer to confirm",
     "If asked to leave a package in an unsecure location, call and text the "
     "customer first to confirm. Document the interaction.",
     "delivery_standards", True),

    (2, "Keys to Success: NEVER deliver to a customer's mailbox",
     "Delivering to a mailbox is a federal offense. Always deliver to the "
     "door, a secure location, or directly to the customer.",
     "delivery_standards", True),

    (2, "Keys to Success: scan delivered packages with correct reason codes",
     "Use the correct reason code when marking a package as delivered or "
     "undeliverable. Incorrect codes affect scorecard metrics and can generate "
     "customer complaints.",
     "delivery_standards", True),

    (2, "Keys to Success: take a clear POD photo including surroundings",
     "Take a clear photo showing the package and its surroundings so the "
     "customer can locate it. Retake if the first photo is poor quality. "
     "This is the DA's best proof of delivery.",
     "delivery_standards", True),

    (2, "Keys to Success: NEVER mark 'household member'",
     "Marking a delivery as 'household member' is a controlled DNR. Never "
     "use this option regardless of who answers the door.",
     "delivery_standards", True),

    (2, "Scorecard overview: DSB, POD, CDF, CC — what each metric is and why it matters",
     "DSB (Delivery Success Behavior): controlled DNRs to avoid. "
     "POD (Photo on Delivery): photo quality and defect avoidance. "
     "CDF (Customer Delivery Feedback): customer ratings triggered at Swipe to Finish. "
     "CC (Contact Compliance): 100% required on every delivery attempt.",
     "scorecard", True),

    (2, "DSB: simultaneous deliveries — what it means, when to use, when NOT to use",
     "Simultaneous deliveries means scanning and delivering multiple packages "
     "at the same time. Explain when this is appropriate (same building, same "
     "stop) and when it is NOT (different addresses, different customers).",
     "scorecard", True),

    (2, "DSB: delivered to household member — what it means, why invalid, what to do instead",
     "Delivered to Household Member is not a valid delivery method and triggers "
     "a controlled DNR. If someone other than the customer answers, follow the "
     "direct-to-customer protocol: get their name, enter in Flex, get signature.",
     "scorecard", True),

    # -----------------------------------------------------------------------
    # PHASE 3 — Delivery Types & Edge Cases
    # -----------------------------------------------------------------------
    (3, "DSB: delivered >50 meters — GeoPin wrong location, Airplane mode explained",
     "A Delivered >50m DNR means the package was marked delivered more than "
     "50 meters from the GeoPin. Cause: GeoPin is in the wrong location. "
     "Fix: always deliver to the physical address. Airplane mode prevents the "
     "GeoPin from pulling the DA to the wrong location during delivery.",
     "scorecard", True),

    (3, "POD: photo requirements — no totes, wheels, humans, up-close shots; adequate lighting",
     "POD photos must not include: totes, wheels/carts/racks, humans, or "
     "up-close shots where the package fills the frame. Adequate lighting is "
     "required. The photo must show the package and its surroundings clearly.",
     "scorecard", True),

    (3, "POD: 8 primary photo defect types",
     "The 8 defect types are: Blurry, Package Too Close, Package Not Clearly "
     "Visible, No Package, Package in Photo Wrong Orientation, Vehicle in Photo, "
     "Photo Too Dark, Package Not Present. Walk through examples of each.",
     "scorecard", True),

    (3, "POD: bypass bucket flow — '?' → Help → Unable to take photo → reason → Submit",
     "If the DA genuinely cannot take a photo: tap '?' in the delivery screen, "
     "select Help, select 'Unable to take photo', enter the reason, and tap "
     "Submit. Do NOT bypass POD without using this flow.",
     "scorecard", True),

    (3, "CDF: customer delivery notification trigger and DA-attributable feedback categories",
     "At Swipe to Finish, the customer receives a notification and can rate the "
     "DA. Positive attributable feedback: Friendly, Delivered with care, Above & "
     "beyond, Followed instructions, Respectful of property, On time. Negative "
     "attributable feedback: Late, Wrong address, Didn't follow instructions, "
     "Never received, Mishandled, Unprofessional.",
     "scorecard", True),

    (3, "Contact Compliance: NEVER close the 'Having trouble?' prompt — call then text",
     "When the 'Having trouble with your delivery?' prompt appears, NEVER close "
     "it. The required workflow is: Call customer → wait at least 3 rings → "
     "Text customer → then proceed. Closing the prompt skips Contact Compliance "
     "and affects the CC metric.",
     "scorecard", True),

    (3, "Contact Compliance: no phone / disconnected / LAN line — driver support workflow",
     "If there is no phone number, the number is disconnected, or it is a LAN "
     "line: contact Driver Support → wait at least 3 rings → open a support "
     "chat → send a message. Always call Driver Support if having issues.",
     "scorecard", True),

    (3, "Locker delivery: how to deliver and mark, common issues (full/broken locker)",
     "Walk through the complete locker delivery flow in Amazon Flex. Common "
     "issues: locker full (select the correct reason code and reattempt or "
     "return), locker broken (contact Driver Support, document the issue).",
     "delivery_types", True),

    (3, "Floor walk-up buildings: mark in Flex, contact customer, common issues, lobby dumping",
     "Walk through floor walk-up delivery: how to mark correctly in Flex, when "
     "and how to contact the customer, common issues (locked lobby, no answer). "
     "Lobby dumping (leaving packages in the lobby without delivering to the "
     "door) is prohibited.",
     "delivery_types", True),

    (3, "Secure delivery location: how to mark a secure delivery location",
     "A secure delivery location is a pre-approved spot designated by the "
     "customer. Walk through how to identify it in the delivery notes and how "
     "to mark it correctly in Flex.",
     "delivery_types", True),

    (3, "Bulk building drops: doorman protocol, mailroom vs. receptionist, PODs",
     "Bulk building drops require specific protocols: always get the doorman's "
     "name and mark it per standard (e.g. 'Paul-doorman denied access to front "
     "door'). Understand the difference between mailroom and receptionist "
     "delivery. POD photos are required for bulk drops.",
     "delivery_types", True),
]


def seed(db) -> None:
    inserted = 0
    skipped = 0

    for phase, title, description, category, is_mandatory in CURRICULUM:
        exists = db.query(TrainingCurriculum).filter(
            TrainingCurriculum.day_number == phase,
            TrainingCurriculum.topic_title == title,
        ).first()

        if exists:
            skipped += 1
            continue

        item = TrainingCurriculum(
            day_number=phase,
            topic_title=title,
            description=description,
            category=category,
            is_mandatory=is_mandatory,
            record_type="coverage",  # all static curriculum items are coverage
        )
        db.add(item)
        inserted += 1

    db.commit()
    print(f"Curriculum seed complete: {inserted} inserted, {skipped} skipped (already existed).")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
