from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_current_user, get_caller_employee
from app.models.trainer_continuation_request import TrainerContinuationRequest
from app.models.training import TrainingRecord
from app.models.employee import Employee
from app.models.notification import Notification
from app.schemas.continuation_request import ContinuationRequestCreate, ContinuationRequestResponse, PriorityUpdate

router = APIRouter(prefix="/continuation-requests", tags=["continuation-requests"])

allow_trainee = RoleChecker(["trainee", "admin"])
allow_trainer = RoleChecker(["trainer", "admin"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def submit_continuation_request(
    payload: ContinuationRequestCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_trainee),
    caller: Employee = Depends(get_caller_employee),
):
    """Trainee submits a silent request to continue with the same trainer.

    - Only one active (pending or accepted) request is allowed at a time.
      Submitting a new one nullifies any existing active request first.
    - No response is shown to the trainee beyond a 201 — the process is silent.
    - A notification is sent to the trainer so it surfaces on their dashboard.
    """
    # Ownership — trainees can only submit for themselves; admins can submit for any trainee
    caller_groups = current_user.get("cognito_groups", [])
    if "admin" not in caller_groups and caller.id != payload.trainee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit continuation requests for yourself.",
        )

    # Verify trainee exists
    trainee = db.query(Employee).filter(
        Employee.id == payload.trainee_id,
        Employee.role == "trainee",
    ).first()
    if not trainee:
        raise HTTPException(status_code=404, detail="Trainee not found.")

    # Verify target trainer exists
    trainer = db.query(Employee).filter(
        Employee.id == payload.trainer_id,
        Employee.role == "trainer",
    ).first()
    if not trainer:
        raise HTTPException(status_code=404, detail="Trainer not found.")

    # Guard: trainee can only request their most recent trainer.
    # This prevents requests to arbitrary trainers the trainee has never worked with.
    most_recent_record = (
        db.query(TrainingRecord)
        .filter(TrainingRecord.trainee_id == payload.trainee_id)
        .order_by(TrainingRecord.record_date.desc())
        .first()
    )
    if not most_recent_record or most_recent_record.trainer_id != payload.trainer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can only request continuation with your most recent trainer.",
        )

    # Nullify any existing active request for this trainee
    existing = db.query(TrainerContinuationRequest).filter(
        TrainerContinuationRequest.trainee_id == payload.trainee_id,
        TrainerContinuationRequest.status.in_(["pending", "accepted"]),
    ).first()
    if existing:
        existing.status = "nullified"
        existing.resolved_at = datetime.now(timezone.utc)

    # Create new request
    new_request = TrainerContinuationRequest(
        trainee_id=payload.trainee_id,
        trainer_id=payload.trainer_id,
    )
    db.add(new_request)
    db.flush()

    # Notify the trainer — shows on their dashboard notification feed
    db.add(Notification(
        employee_id=payload.trainer_id,
        type="continuation_request",
        message=f"{trainee.name} has requested to continue training with you on their next assigned day.",
    ))

    db.commit()
    # Silent 201 — no body content returned to the trainee
    return {}


@router.get("/trainer/{trainer_id}", response_model=List[ContinuationRequestResponse])
def get_pending_requests_for_trainer(
    trainer_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_trainer),
    caller: Employee = Depends(get_caller_employee),
):
    """Return all pending continuation requests addressed to this trainer.

    Used by the trainer dashboard to surface incoming requests.
    Trainers can only read their own requests; admins can read any.
    """
    caller_groups = current_user.get("cognito_groups", [])
    if "admin" not in caller_groups and caller.id != trainer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own continuation requests.",
        )
    return db.query(TrainerContinuationRequest).filter(
        TrainerContinuationRequest.trainer_id == trainer_id,
        TrainerContinuationRequest.status == "pending",
    ).all()


@router.patch("/{request_id}/accept", response_model=ContinuationRequestResponse)
def accept_continuation_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_trainer),
    caller: Employee = Depends(get_caller_employee),
):
    """Trainer accepts a pending continuation request.

    Status moves to 'accepted'. On the trainee's next dispatch day,
    training_injection will honour this and pair them if the trainer is available.
    No notification is sent to the trainee — the process remains silent.
    Only the trainer addressed by the request can accept it; admins may accept any.
    """
    req = db.query(TrainerContinuationRequest).filter(
        TrainerContinuationRequest.id == request_id,
        TrainerContinuationRequest.status == "pending",
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Pending request not found.")

    caller_groups = current_user.get("cognito_groups", [])
    if "admin" not in caller_groups and caller.id != req.trainer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only accept requests addressed to you.",
        )

    req.status = "accepted"
    req.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(req)
    return req


@router.patch("/{request_id}/priority", response_model=ContinuationRequestResponse)
def set_request_priority(
    request_id: UUID,
    payload: PriorityUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_trainer),
    caller_employee: Employee = Depends(get_caller_employee),
):
    """Trainer sets or clears their priority ranking for a specific accepted request.

    Priority is used to resolve conflicts when multiple accepted requests from the
    same trainer collide on the same dispatch day. Lower integer = higher priority.
    NULL = unranked (lowest priority, resolved by LIFO tiebreaker).

    Rules enforced:
    - No two accepted requests for the same trainer may share the same priority integer.
    - Setting priority=None clears the ranking (reverts to unranked).
    - Only the trainer who owns this request can set its priority (enforced by
      verifying the request's trainer_id matches the caller's employee record).
    - Only pending or accepted requests can be ranked.
    """
    req = db.query(TrainerContinuationRequest).filter(
        TrainerContinuationRequest.id == request_id,
        TrainerContinuationRequest.status.in_(["pending", "accepted"]),
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Active request not found.")

    # Admins bypass the ownership check; all others must own the request.
    caller_groups = current_user.get("cognito_groups", [])
    if "admin" not in caller_groups:
        if caller_employee.id != req.trainer_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only set priority on your own requests.",
            )

    # Enforce no duplicate priority integers among this trainer's active requests
    if payload.priority is not None:
        duplicate = (
            db.query(TrainerContinuationRequest)
            .filter(
                TrainerContinuationRequest.trainer_id == req.trainer_id,
                TrainerContinuationRequest.status.in_(["pending", "accepted"]),
                TrainerContinuationRequest.priority == payload.priority,
                TrainerContinuationRequest.id != request_id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Priority {payload.priority} is already assigned to another request. Choose a different rank.",
            )

    req.priority = payload.priority
    db.commit()
    db.refresh(req)
    return req


@router.patch("/{request_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_continuation_request(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(allow_trainer),
    caller: Employee = Depends(get_caller_employee),
):
    """Trainer rejects a pending continuation request.

    Status moves to 'nullified'. The trainee is paired normally on their next
    dispatch day. No notification is sent to the trainee.
    Only the trainer addressed by the request can reject it; admins may reject any.
    """
    req = db.query(TrainerContinuationRequest).filter(
        TrainerContinuationRequest.id == request_id,
        TrainerContinuationRequest.status == "pending",
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Pending request not found.")

    caller_groups = current_user.get("cognito_groups", [])
    if "admin" not in caller_groups and caller.id != req.trainer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only reject requests addressed to you.",
        )

    req.status = "nullified"
    req.resolved_at = datetime.now(timezone.utc)
    db.commit()
    return
