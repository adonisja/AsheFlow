"""
Graduation quiz router.

Endpoints:
  POST /graduation-quiz/issue/{trainee_id}     management/admin — issue quiz to trainee
  GET  /graduation-quiz/my-quiz                trainee — fetch active issued quiz
  POST /graduation-quiz/submit                 trainee — submit answers
  GET  /graduation-quiz/{quiz_id}              management/admin — full quiz + responses for review
  GET  /graduation-quiz/trainee/{trainee_id}   management/admin — all quiz attempts for a trainee
  PATCH /graduation-quiz/{quiz_id}/review      management/admin — apply overrides + final verdict
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_caller_employee, RoleChecker, require_configured
from app.database import get_db
from app.models.employee import Employee
from app.models.graduation_quiz import GraduationQuiz, GraduationQuizResponse, GraduationQuizTemplate
from app.models.notification import Notification
from app.models.training import TrainingRecord
from app.services.generate_quiz_remediation import generate_quiz_remediation
from app.services.score_graduation_quiz import apply_manager_review, score_graduation_quiz

router = APIRouter(prefix="/graduation-quiz", tags=["graduation-quiz"])

_mgmt_admin = RoleChecker(["management", "admin"])
_trainee = RoleChecker(["trainee"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class QuizIssueRequest(BaseModel):
    training_record_id: UUID | None = None  # optionally link to the Phase 5 TrainingRecord


class QuizSubmitRequest(BaseModel):
    quiz_id: UUID
    responses: list[dict]   # [{"question_id": uuid, "answer_text": str}]


class QuizOverride(BaseModel):
    response_id: UUID
    correct: bool
    note: str | None = None


class QuizReviewRequest(BaseModel):
    overrides: list[QuizOverride] = []
    final_pass: bool
    send_for_training: bool = False  # if final_pass=False, generate remediation record


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_quiz(quiz: GraduationQuiz, responses: list, questions: list) -> dict:
    q_map = {str(q.id): q for q in questions}
    return {
        "id": str(quiz.id),
        "trainee_id": str(quiz.trainee_id),
        "issued_by": str(quiz.issued_by) if quiz.issued_by else None,
        "attempt_number": quiz.attempt_number,
        "issued_at": quiz.issued_at.isoformat() if quiz.issued_at else None,
        "submitted_at": quiz.submitted_at.isoformat() if quiz.submitted_at else None,
        "status": quiz.status,
        "auto_score": quiz.auto_score,
        "final_score": quiz.final_score,
        "passed": quiz.passed,
        "weak_topics": quiz.weak_topics or [],
        "manager_reviewed_at": quiz.manager_reviewed_at.isoformat() if quiz.manager_reviewed_at else None,
        "responses": [
            {
                "id": str(r.id),
                "question_id": str(r.question_id),
                "question_text": q_map[str(r.question_id)].question_text if str(r.question_id) in q_map else None,
                "question_type": q_map[str(r.question_id)].question_type if str(r.question_id) in q_map else None,
                "choices": q_map[str(r.question_id)].choices if str(r.question_id) in q_map else None,
                "correct_answer": q_map[str(r.question_id)].correct_answer if str(r.question_id) in q_map else None,
                "is_mandatory": q_map[str(r.question_id)].is_mandatory if str(r.question_id) in q_map else True,
                "answer_text": r.answer_text,
                "auto_correct": r.auto_correct,
                "manager_override": r.manager_override,
                "override_note": r.override_note,
            }
            for r in responses
        ],
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/issue/{trainee_id}", dependencies=[Depends(require_configured)])
def issue_quiz(
    trainee_id: UUID,
    body: QuizIssueRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: None = Depends(_mgmt_admin),
):
    trainee = db.query(Employee).filter(
        Employee.id == trainee_id,
        Employee.company_id == caller.company_id,
        Employee.role == "trainee",
        Employee.is_active == True,
    ).first()
    if not trainee:
        raise HTTPException(status_code=404, detail="Active trainee not found.")

    # Block if there is already an issued or pending_issue quiz for this trainee
    existing = db.query(GraduationQuiz).filter(
        GraduationQuiz.trainee_id == trainee_id,
        GraduationQuiz.company_id == caller.company_id,
        GraduationQuiz.status.in_(["pending_issue", "issued", "submitted", "under_review"]),
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Trainee already has an active quiz (status: {existing.status}).",
        )

    # Fetch active questions for this company ordered by display_order
    questions = db.query(GraduationQuizTemplate).filter(
        GraduationQuizTemplate.company_id == caller.company_id,
        GraduationQuizTemplate.is_active == True,
    ).order_by(GraduationQuizTemplate.display_order).all()
    if not questions:
        raise HTTPException(
            status_code=422,
            detail="No active quiz questions configured for this company. Add questions before issuing a quiz.",
        )

    attempt_number = (
        db.query(GraduationQuiz)
        .filter(
            GraduationQuiz.trainee_id == trainee_id,
            GraduationQuiz.company_id == caller.company_id,
        )
        .count()
    ) + 1

    quiz = GraduationQuiz(
        company_id=caller.company_id,
        trainee_id=trainee_id,
        issued_by=caller.id,
        training_record_id=body.training_record_id,
        attempt_number=attempt_number,
        issued_at=datetime.now(timezone.utc),
        status="issued",
    )
    db.add(quiz)
    db.flush()

    # Pre-create response rows so the trainee only fills in answer_text
    for question in questions:
        db.add(GraduationQuizResponse(
            company_id=caller.company_id,
            quiz_id=quiz.id,
            question_id=question.id,
        ))

    # Notify the trainee in-app
    db.add(Notification(
        company_id=caller.company_id,
        employee_id=trainee_id,
        type="quiz_issued",
        message=(
            "Your graduation quiz is ready. Open AsheFlow to complete it. "
            "Submit your answers before the end of your shift today."
        ),
    ))

    db.commit()
    return {"status": "issued", "quiz_id": str(quiz.id), "attempt_number": attempt_number}


@router.get("/my-quiz", dependencies=[Depends(require_configured)])
def get_my_quiz(
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: None = Depends(_trainee),
):
    quiz = db.query(GraduationQuiz).filter(
        GraduationQuiz.trainee_id == caller.id,
        GraduationQuiz.company_id == caller.company_id,
        GraduationQuiz.status == "issued",
    ).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="No active quiz found.")

    responses = db.query(GraduationQuizResponse).filter(
        GraduationQuizResponse.quiz_id == quiz.id
    ).all()

    questions = db.query(GraduationQuizTemplate).filter(
        GraduationQuizTemplate.id.in_([r.question_id for r in responses])
    ).order_by(GraduationQuizTemplate.display_order).all()

    # Return questions without correct_answer — trainee must not see the answer
    q_map = {str(q.id): q for q in questions}
    return {
        "quiz_id": str(quiz.id),
        "attempt_number": quiz.attempt_number,
        "questions": [
            {
                "response_id": str(r.id),
                "question_id": str(r.question_id),
                "question_text": q_map[str(r.question_id)].question_text,
                "question_type": q_map[str(r.question_id)].question_type,
                "choices": q_map[str(r.question_id)].choices,
                "is_mandatory": q_map[str(r.question_id)].is_mandatory,
            }
            for r in responses
            if str(r.question_id) in q_map
        ],
    }


@router.post("/submit", dependencies=[Depends(require_configured)])
def submit_quiz(
    body: QuizSubmitRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: None = Depends(_trainee),
):
    quiz = db.query(GraduationQuiz).filter(
        GraduationQuiz.id == body.quiz_id,
        GraduationQuiz.trainee_id == caller.id,
        GraduationQuiz.company_id == caller.company_id,
        GraduationQuiz.status == "issued",
    ).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Active quiz not found.")

    # Write answers into pre-created response rows
    response_map = {
        str(r.question_id): r
        for r in db.query(GraduationQuizResponse).filter(
            GraduationQuizResponse.quiz_id == quiz.id
        ).all()
    }

    for entry in body.responses:
        resp = response_map.get(str(entry["question_id"]))
        if resp is None:
            continue
        resp.answer_text = entry.get("answer_text", "")

    db.flush()

    score_result = score_graduation_quiz(db, quiz)

    # Notify management/admin that the quiz needs review
    recipients = db.query(Employee).filter(
        Employee.role.in_(["management", "admin"]),
        Employee.is_active == True,
        Employee.company_id == caller.company_id,
    ).all()

    preliminary = "likely passed" if score_result["passed_preliminary"] else "needs review"
    mgmt_message = (
        f"{caller.name} submitted their graduation quiz "
        f"(attempt {quiz.attempt_number}). "
        f"Preliminary score: {score_result['auto_score']:.1f}% — {preliminary}. "
        f"Please review and confirm the final result."
    )
    for recipient in recipients:
        db.add(Notification(
            company_id=caller.company_id,
            employee_id=recipient.id,
            type="quiz_submitted",
            message=mgmt_message,
        ))

    # Notify the paired trainer (confirmation only — no score details)
    if quiz.training_record_id:
        record = db.query(TrainingRecord).filter(TrainingRecord.id == quiz.training_record_id).first()
        if record and record.trainer_id:
            trainer_already_notified = any(r.id == record.trainer_id for r in recipients)
            if not trainer_already_notified:
                db.add(Notification(
                    company_id=caller.company_id,
                    employee_id=record.trainer_id,
                    type="quiz_submitted",
                    message=f"{caller.name} has submitted their graduation quiz (attempt {quiz.attempt_number}).",
                ))

    db.commit()
    return {
        "status": "under_review",
        "auto_score": score_result["auto_score"],
        "passed_preliminary": score_result["passed_preliminary"],
    }


@router.get("/{quiz_id}", dependencies=[Depends(require_configured)])
def get_quiz_for_review(
    quiz_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: None = Depends(_mgmt_admin),
):
    quiz = db.query(GraduationQuiz).filter(
        GraduationQuiz.id == quiz_id,
        GraduationQuiz.company_id == caller.company_id,
    ).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found.")

    responses = db.query(GraduationQuizResponse).filter(
        GraduationQuizResponse.quiz_id == quiz_id
    ).all()
    questions = db.query(GraduationQuizTemplate).filter(
        GraduationQuizTemplate.id.in_([r.question_id for r in responses])
    ).all()

    trainee = db.query(Employee).filter(Employee.id == quiz.trainee_id).first()
    result = _serialize_quiz(quiz, responses, questions)
    result["trainee_name"] = trainee.name if trainee else None
    return result


@router.get("/trainee/{trainee_id}", dependencies=[Depends(require_configured)])
def get_trainee_quiz_history(
    trainee_id: UUID,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: None = Depends(_mgmt_admin),
):
    trainee = db.query(Employee).filter(
        Employee.id == trainee_id,
        Employee.company_id == caller.company_id,
    ).first()
    if not trainee:
        raise HTTPException(status_code=404, detail="Employee not found.")

    quizzes = db.query(GraduationQuiz).filter(
        GraduationQuiz.trainee_id == trainee_id,
        GraduationQuiz.company_id == caller.company_id,
    ).order_by(GraduationQuiz.attempt_number).all()

    return [
        {
            "id": str(q.id),
            "attempt_number": q.attempt_number,
            "status": q.status,
            "auto_score": q.auto_score,
            "final_score": q.final_score,
            "passed": q.passed,
            "issued_at": q.issued_at.isoformat() if q.issued_at else None,
            "submitted_at": q.submitted_at.isoformat() if q.submitted_at else None,
            "manager_reviewed_at": q.manager_reviewed_at.isoformat() if q.manager_reviewed_at else None,
            "weak_topics": q.weak_topics or [],
        }
        for q in quizzes
    ]


@router.patch("/{quiz_id}/review", dependencies=[Depends(require_configured)])
def review_quiz(
    quiz_id: UUID,
    body: QuizReviewRequest,
    caller: Employee = Depends(get_caller_employee),
    db: Session = Depends(get_db),
    _: None = Depends(_mgmt_admin),
):
    quiz = db.query(GraduationQuiz).filter(
        GraduationQuiz.id == quiz_id,
        GraduationQuiz.company_id == caller.company_id,
        GraduationQuiz.status == "under_review",
    ).first()
    if not quiz:
        raise HTTPException(
            status_code=404,
            detail="Quiz not found or not in under_review status.",
        )

    apply_manager_review(
        db,
        quiz,
        overrides=[o.model_dump() for o in body.overrides],
        final_pass=body.final_pass,
        reviewer_id=caller.id,
    )

    trainee = db.query(Employee).filter(Employee.id == quiz.trainee_id).first()
    trainee_name = trainee.name if trainee else str(quiz.trainee_id)

    remediation_record_id = None
    if not body.final_pass and body.send_for_training:
        remediation = generate_quiz_remediation(db, quiz, caller.company_id)
        remediation_record_id = str(remediation.id)

    # Notify the trainee of the outcome
    if trainee:
        if body.final_pass:
            trainee_msg = (
                "Your graduation quiz result has been confirmed — you passed! "
                "You will be promoted to Walker on your next dispatch day."
            )
        else:
            trainee_msg = (
                "Your graduation quiz result has been reviewed. "
                "You have been referred for additional training on the topics that need improvement. "
                "You will be scheduled with a trainer on your next dispatch day."
            )
        db.add(Notification(
            company_id=caller.company_id,
            employee_id=quiz.trainee_id,
            type="quiz_result_confirmed",
            message=trainee_msg,
        ))

    db.commit()

    return {
        "status": quiz.status,
        "final_score": quiz.final_score,
        "passed": quiz.passed,
        "weak_topics": quiz.weak_topics or [],
        "remediation_record_id": remediation_record_id,
        "trainee_name": trainee_name,
    }
