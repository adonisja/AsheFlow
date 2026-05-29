from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.graduation_quiz import GraduationQuiz, GraduationQuizResponse, GraduationQuizTemplate

PASS_THRESHOLD = 90.0


def score_graduation_quiz(db: Session, quiz: GraduationQuiz) -> dict:
    """
    Score a submitted graduation quiz.

    Scoring rules (mirrors Phase 4 — ADR-046 §6 extended):
    - Score = (mandatory questions correct / total mandatory questions) × 100
    - Pass (auto) = score >= 90.0 AND every mandatory question individually correct
    - Short-answer questions: always go to under_review; preliminary auto_correct
      set via keyword matching but never treated as definitive.
    - Status is always set to under_review after scoring so manager confirms.
      Exception: if all questions are MC (fully auto-scoreable) and pass threshold
      is met, status is still under_review — manager confirmation is always required.

    Returns:
        {
            "auto_score": float,
            "passed_preliminary": bool,
            "failed_mandatory_topics": list[str],
            "total_mandatory": int,
            "passed_mandatory": int,
            "has_short_answer": bool,
        }

    Caller is responsible for commit.
    """
    responses = (
        db.query(GraduationQuizResponse, GraduationQuizTemplate)
        .join(GraduationQuizTemplate, GraduationQuizResponse.question_id == GraduationQuizTemplate.id)
        .filter(GraduationQuizResponse.quiz_id == quiz.id)
        .all()
    )

    mandatory_results: list[tuple[str, bool]] = []  # (question_text, correct)
    has_short_answer = False

    for response, question in responses:
        if question.question_type == "multiple_choice" and question.correct_answer is not None:
            # correct_answer may be pipe-separated for multi-select questions
            # (e.g. "Option A|Option B|Option C"). The trainee's answer_text
            # stores their selected options in the same pipe-separated format.
            # Order-insensitive comparison.
            expected = sorted(s.strip().lower() for s in question.correct_answer.split("|"))
            actual = sorted(s.strip().lower() for s in (response.answer_text or "").split("|") if s.strip())
            correct = expected == actual
            response.auto_correct = correct
        elif question.question_type == "short_answer":
            has_short_answer = True
            keywords: list[str] = question.keywords or []
            answer_lower = (response.answer_text or "").lower()
            preliminary = any(kw.lower() in answer_lower for kw in keywords) if keywords else False
            response.auto_correct = preliminary
        else:
            response.auto_correct = None

        if question.is_mandatory:
            effective_correct = response.auto_correct if response.auto_correct is not None else False
            mandatory_results.append((question.question_text, effective_correct))

    db.flush()

    total = len(mandatory_results)
    passed_count = sum(1 for _, c in mandatory_results if c)
    failed_topics = [q for q, c in mandatory_results if not c]
    all_mandatory_passed = len(failed_topics) == 0

    auto_score = (passed_count / total * 100.0) if total > 0 else 0.0
    passed_preliminary = auto_score >= PASS_THRESHOLD and all_mandatory_passed

    quiz.auto_score = round(auto_score, 2)
    quiz.submitted_at = datetime.now(timezone.utc)
    quiz.status = "under_review"
    quiz.weak_topics = failed_topics

    db.flush()

    return {
        "auto_score": quiz.auto_score,
        "passed_preliminary": passed_preliminary,
        "failed_mandatory_topics": failed_topics,
        "total_mandatory": total,
        "passed_mandatory": passed_count,
        "has_short_answer": has_short_answer,
    }


def apply_manager_review(
    db: Session,
    quiz: GraduationQuiz,
    overrides: list[dict],
    final_pass: bool,
    reviewer_id,
) -> None:
    """
    Apply manager per-question overrides and record the final pass/fail decision.

    overrides: list of {"response_id": uuid, "correct": bool, "note": str | None}
    final_pass: manager's definitive verdict (True = graduate, False = further training)
    reviewer_id: employee id of the reviewing manager/admin

    Caller is responsible for commit.
    """
    response_map = {
        str(r.id): r
        for r in db.query(GraduationQuizResponse).filter(
            GraduationQuizResponse.quiz_id == quiz.id
        ).all()
    }

    for override in overrides:
        resp = response_map.get(str(override["response_id"]))
        if resp is None:
            continue
        resp.manager_override = override["correct"]
        if override.get("note"):
            resp.override_note = override["note"]

    # Recompute final score from overrides (fall back to auto_correct where no override)
    all_responses = (
        db.query(GraduationQuizResponse, GraduationQuizTemplate)
        .join(GraduationQuizTemplate, GraduationQuizResponse.question_id == GraduationQuizTemplate.id)
        .filter(GraduationQuizResponse.quiz_id == quiz.id)
        .all()
    )

    mandatory_correct = 0
    mandatory_total = 0
    weak_topics = []
    for resp, question in all_responses:
        if not question.is_mandatory:
            continue
        effective = resp.manager_override if resp.manager_override is not None else resp.auto_correct
        effective = effective if effective is not None else False
        mandatory_total += 1
        if effective:
            mandatory_correct += 1
        else:
            weak_topics.append(question.question_text)

    final_score = (mandatory_correct / mandatory_total * 100.0) if mandatory_total > 0 else 0.0

    quiz.final_score = round(final_score, 2)
    quiz.passed = final_pass
    quiz.status = "passed" if final_pass else "failed"
    quiz.weak_topics = weak_topics
    quiz.manager_reviewed_by = reviewer_id
    quiz.manager_reviewed_at = datetime.now(timezone.utc)

    db.flush()
