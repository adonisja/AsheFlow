"""
Seed the graduation quiz question bank for a company.

Usage:
    docker compose exec backend python scripts/seed_graduation_quiz.py <company_id>

Idempotent — skips questions that already exist by (company_id, question_text).
Safe to re-run.

Source: Company A training quiz (walker onboarding evaluation form).
Design: ADR-107, docs/decisions/ADR-107-graduation-quiz.md
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models.graduation_quiz import GraduationQuizTemplate

# ---------------------------------------------------------------------------
# Question bank
# (question_text, question_type, choices, correct_answer, is_mandatory,
#  auto_scoreable, keywords, display_order)
#
# For multiple_choice:
#   correct_answer is the exact string that must be selected.
#   choices lists all options exactly as they appear in the question.
#
# For short_answer:
#   correct_answer is None.
#   keywords is a list of terms; the auto-scorer flags the answer as
#   preliminary-correct if at least one keyword appears (case-insensitive).
#   A manager review is always required for short_answer regardless.
#
# All questions are is_mandatory=True — every mandatory question must pass
# individually (mirrors Phase 4 rule). Non-mandatory questions do not affect
# the pass/fail gate but are still shown and recorded for audit/metrics.
# ---------------------------------------------------------------------------

QUESTIONS = [
    # ------------------------------------------------------------------
    # Q1 — 4 required work apps (multi-select checkbox in the form,
    # modeled as a single MC question requiring all 4 correct choices listed)
    # ------------------------------------------------------------------
    (
        "What are the 4 work apps that you must have downloaded?",
        "multiple_choice",
        [
            "Amazon AZ - schedule",
            "Discord - shift assignments and immediate communication",
            "ADP - weekly payroll",
            "Amazon Flex - transportation settings are on \"walker\"",
        ],
        # All 4 are correct — trainee must select all of them.
        # Stored as a pipe-separated string; scoring engine checks all are present.
        "Amazon AZ - schedule|Discord - shift assignments and immediate communication|ADP - weekly payroll|Amazon Flex - transportation settings are on \"walker\"",
        True, True,
        None,
        1,
    ),

    # ------------------------------------------------------------------
    # Q2 — Who to contact for schedule changes / HR / callouts
    # ------------------------------------------------------------------
    (
        "Who do you contact for schedule changes, HR, call outs and any general work issues?",
        "multiple_choice",
        [
            "Email hr@yourdsp.com to have an official documentation",
            "You can show up the next day to work if you missed your assigned shift",
            "Send a supervisor or driver a Chime message",
        ],
        "Email hr@yourdsp.com to have an official documentation",
        True, True,
        None,
        2,
    ),

    # ------------------------------------------------------------------
    # Q3 — Flex activation
    # ------------------------------------------------------------------
    (
        "How and who do you ask to be activated on Amazon Flex (when you are at work and your Flex does not show your shift)?",
        "multiple_choice",
        [
            "Refresh the Amazon Flex app",
            "Ask your driver to activate",
            "Email hr@yourdsp.com",
            "Wait until it works",
        ],
        "Ask your driver to activate",
        True, True,
        None,
        3,
    ),

    # ------------------------------------------------------------------
    # Q4 — 4 scorecard categories (all-correct multi-select)
    # ------------------------------------------------------------------
    (
        "What are the 4 scorecard categories?",
        "multiple_choice",
        [
            "DSB (Delivery Success Behavior)",
            "POD (Photo on Delivery)",
            "CDF (Customer Delivery Feedback)",
            "CC (Contact Compliance)",
        ],
        "DSB (Delivery Success Behavior)|POD (Photo on Delivery)|CDF (Customer Delivery Feedback)|CC (Contact Compliance)",
        True, True,
        None,
        4,
    ),

    # ------------------------------------------------------------------
    # Q5 — When and why to take a photo (short answer)
    # ------------------------------------------------------------------
    (
        "When and why should you take a photo during deliveries?",
        "short_answer",
        None,
        None,
        True, False,
        ["every delivery", "proof", "pod", "photo on delivery", "customer", "surroundings", "evidence"],
        5,
    ),

    # ------------------------------------------------------------------
    # Q6 — Multiple packages, same address, different customer name (short answer)
    # ------------------------------------------------------------------
    (
        "What happens if multiple packages need to be delivered to the same address with a different customer name?",
        "short_answer",
        None,
        None,
        True, False,
        ["check label", "scan each", "verify", "different customer", "separate", "correct address"],
        6,
    ),

    # ------------------------------------------------------------------
    # Q7 — Mailroom full (short answer)
    # ------------------------------------------------------------------
    (
        "What should I do if I had to deliver multiple packages to the mailroom that is full?",
        "short_answer",
        None,
        None,
        True, False,
        ["contact customer", "alternative", "customer support", "driver support", "rts", "return", "do not leave"],
        7,
    ),

    # ------------------------------------------------------------------
    # Q8 — Secure delivery location (short answer)
    # ------------------------------------------------------------------
    (
        "What is a secure delivery location?",
        "short_answer",
        None,
        None,
        True, False,
        ["pre-approved", "designated", "customer", "notes", "secure", "safe location", "specified"],
        8,
    ),

    # ------------------------------------------------------------------
    # Q9 — Timecard edit deadline
    # ------------------------------------------------------------------
    (
        "When is the last day for time card edits to be submitted for payroll?",
        "multiple_choice",
        [
            "By Sunday midnight",
            "At the beginning of every shift",
            "Whenever you have time",
        ],
        "By Sunday midnight",
        True, True,
        None,
        9,
    ),

    # ------------------------------------------------------------------
    # Q10 — 2 delivery methods walkers must use
    # ------------------------------------------------------------------
    (
        "What are the 2 bulk-drop delivery methods that walkers must use for building deliveries?",
        "multiple_choice",
        [
            "Mailroom & Household Member",
            "Front Door & Doorman",
            "Doorman & Mailroom",
            "Another Secure Location & Front Door",
        ],
        "Doorman & Mailroom",
        True, True,
        None,
        10,
    ),

    # ------------------------------------------------------------------
    # Q11 — 30-minute lunch break
    # ------------------------------------------------------------------
    (
        "When do you clock out for a mandatory unpaid 30 minute lunch break?",
        "multiple_choice",
        [
            "If working 6+ hours",
            "No lunch breaks are required",
            "Between 11 AM - 2 PM",
        ],
        "If working 6+ hours",
        True, True,
        None,
        11,
    ),

    # ------------------------------------------------------------------
    # Q12 — Business closed
    # ------------------------------------------------------------------
    (
        "What do you do when a business is closed and you cannot deliver?",
        "multiple_choice",
        [
            "Leave it outside of the building",
            "Call and text the customer",
            "Tell your driver",
            "Mark \"business closed\" in the Flex App and Discord truck room and return the package to the truck",
        ],
        "Mark \"business closed\" in the Flex App and Discord truck room and return the package to the truck",
        True, True,
        None,
        12,
    ),

    # ------------------------------------------------------------------
    # Q13 — What is an RTS (short answer)
    # ------------------------------------------------------------------
    (
        "What is an RTS?",
        "short_answer",
        None,
        None,
        True, False,
        ["return to station", "return to sender", "undeliverable", "last resort", "all attempts failed"],
        13,
    ),

    # ------------------------------------------------------------------
    # Q14 — Not Deliverable criteria
    # ------------------------------------------------------------------
    (
        "How do you know when an RTS is Not Deliverable?",
        "multiple_choice",
        [
            "After attempting 1 time and no one responds",
            "After ringing the customer's doorbell and no one answers",
            "After calling & texting the customer and reattempting it 2 more times",
            "When you cannot get inside the delivery location",
        ],
        "After calling & texting the customer and reattempting it 2 more times",
        True, True,
        None,
        14,
    ),

    # ------------------------------------------------------------------
    # Q15 — Stolen vs. missing (short answer)
    # ------------------------------------------------------------------
    (
        "Briefly explain how to deal with a stolen package vs. missing?",
        "short_answer",
        None,
        None,
        True, False,
        ["incident report", "stolen", "missing", "mark missing", "flex", "discord", "notify", "dispatch", "driver"],
        15,
    ),

    # ------------------------------------------------------------------
    # Q16 — DNR (short answer)
    # ------------------------------------------------------------------
    (
        "What is a DNR and how do you prevent from getting one?",
        "short_answer",
        None,
        None,
        True, False,
        ["did not reattempt", "contact compliance", "call", "text", "reattempt", "procedure", "follow steps"],
        16,
    ),

    # ------------------------------------------------------------------
    # Q17 — Simultaneous delivery (multi-select: yes + explanation)
    # Modeled as a short_answer so the trainee justifies their choice.
    # ------------------------------------------------------------------
    (
        "Should packages be marked as \"simultaneous delivery\"? Explain why or why not.",
        "short_answer",
        None,
        None,
        True, False,
        ["same building", "same stop", "same address", "not different addresses", "not different customers",
         "when appropriate", "multiple packages"],
        17,
    ),
]


def seed(db, company_id: str) -> None:
    inserted = 0
    skipped = 0

    for (question_text, question_type, choices, correct_answer,
         is_mandatory, auto_scoreable, keywords, display_order) in QUESTIONS:

        exists = db.query(GraduationQuizTemplate).filter(
            GraduationQuizTemplate.company_id == company_id,
            GraduationQuizTemplate.question_text == question_text,
        ).first()

        if exists:
            skipped += 1
            continue

        item = GraduationQuizTemplate(
            company_id=company_id,
            question_text=question_text,
            question_type=question_type,
            choices=choices,
            correct_answer=correct_answer,
            is_mandatory=is_mandatory,
            auto_scoreable=auto_scoreable,
            keywords=keywords,
            display_order=display_order,
            is_active=True,
        )
        db.add(item)
        inserted += 1

    db.commit()
    print(f"Quiz seed complete: {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/seed_graduation_quiz.py <company_id>")
        sys.exit(1)

    company_id = sys.argv[1]
    db = SessionLocal()
    try:
        seed(db, company_id)
    finally:
        db.close()
