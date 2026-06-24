import logging

import boto3

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from datetime import date, datetime, timezone
from app.services.audit import write_audit

from app.api.deps import RoleChecker, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.adp_integration import ADPIntegration
from app.models.employee import Employee
from app.models.timecard_adjustments import TimeCardAdjustment
from app.models.adp_pay_period import ADPPayPeriod
from app.services.adp import patch_adp_timecard
from app.models.notification import Notification
from app.services.adp_exceptions import ADPClientError, ADPServerError


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/adp", tags=["adp"])

allow_admin = RoleChecker(["admin"])
allow_manager_or_admin = RoleChecker(["admin", "manager"])

class ADPConfigureRequest(BaseModel):
    adp_client_id: str
    adp_client_secret: str
    adp_certificate: str
    adp_environment: str = "sandbox"

    @field_validator("adp_environment")
    @classmethod
    def validate_environment(cls, v: str) -> str:
        if v not in ("sandbox", "production"):
            raise ValueError("environment must be 'sandbox' or 'production'")
        return v
    
    
class FlexTimesheetRow(BaseModel):
    employee_id: str
    work_date: str
    break_start_at: str
    break_end_at: str


class FlexTimesheetUploadRequest(BaseModel):
    rows: list[FlexTimesheetRow]
    
@router.post("/configure", status_code=status.HTTP_200_OK)
async def configure_adp(
    payload: ADPConfigureRequest,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: bool = Depends(allow_admin),
):
    """Store ADP RUN credentials for this company and upsert the integration row.

    Credentials (client secret + mTLS certificate) are written to AWS Secrets
    Manager; only the ARN paths are persisted in the database. The integration
    is created in a disabled state — use POST /adp/enable to activate it.

    Enforces:
    - Admin-only access
    - adp_environment must be 'sandbox' or 'production'
    - AWS write failures surface as 502 (never expose raw boto3 errors)
    """
    sm = boto3.client("secretsmanager", region_name=settings.aws_region)
    secret_arn = f"asheflow/{caller.company_id}/adp/client-secret"
    cert_arn   = f"asheflow/{caller.company_id}/adp/certificate"

    try:
        sm.put_secret_value(SecretId=secret_arn, SecretString=payload.adp_client_secret)
        sm.put_secret_value(SecretId=cert_arn,   SecretString=payload.adp_certificate)
    except ClientError as e:
        logger.warning("Secrets Manager write failed for company %s: %s", caller.company_id, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to store ADP credentials")

    integration = db.query(ADPIntegration).filter(
        ADPIntegration.company_id == caller.company_id
    ).first()

    if integration is None:
        integration = ADPIntegration(company_id=caller.company_id)
        db.add(integration)

    integration.adp_client_id        = payload.adp_client_id
    integration.adp_client_secret_arn = secret_arn
    integration.adp_certificate_arn   = cert_arn
    integration.adp_environment       = payload.adp_environment

    db.commit()
    return {"detail": "ADP integration configured"}


@router.post("/flex-timesheets", status_code=status.HTTP_201_CREATED)
async def upload_flex_timesheets(
    payload: FlexTimesheetUploadRequest,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: bool = Depends(allow_admin),
):
    """Bulk-upsert Amazon Flex break records for one or more employees.

    Each row must reference an active employee belonging to the caller's company.
    Duplicate rows (same employee_id + work_date) are upserted — existing records
    are overwritten so re-uploads are idempotent.

    Enforces:
    - Admin-only access
    - employee_id must be a valid UUID belonging to this company
    - work_date must be a valid ISO date string (YYYY-MM-DD)
    - break_start_at and break_end_at must be valid ISO datetime strings
    """
    from uuid import UUID
    from datetime import date, datetime, timezone
    from app.models.flex_timesheets import FlexTimesheet

    created = 0
    updated = 0

    for row in payload.rows:
        try:
            emp_id = UUID(row.employee_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid employee_id: {row.employee_id}")
        
        employee = db.query(Employee).filter(
            Employee.id == emp_id,
            Employee.company_id == caller.company_id,
            Employee.is_active == True
        ).first()

        if not employee:
            raise HTTPException(status_code=404, detail=f"Employee {row.employee_id} not found")
        
        try:
            work_date = date.fromisoformat(row.work_date)
            break_start = datetime.fromisoformat(row.break_start_at)
            break_end = datetime.fromisoformat(row.break_end_at)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Invalid date/time for employee {row.employee_id}: {e}")
        
        existing = db.query(FlexTimesheet).filter(
            FlexTimesheet.company_id == caller.company_id,
            FlexTimesheet.employee_id == emp_id,
            FlexTimesheet.work_date == work_date,
        ).first()

        if existing:
            existing.break_start_at = break_start
            existing.break_end_at = break_end
            existing.uploaded_by = caller.id
            existing.uploaded_at = datetime.now(timezone.utc)
            updated += 1
        else:
            db.add(FlexTimesheet(
                company_id = caller.company_id,
                employee_id = emp_id,
                work_date = work_date,
                break_start_at = break_start,
                break_end_at = break_end,
                uploaded_by = caller.id,
            ))
            created += 1
    
    db.commit()
    return {"created": created, "updated": updated}


@router.post("/adjustments/{adjustment_id}/employee-signoff", status_code=status.HTTP_201_CREATED)
async def employee_signoff(
    adjustment_id: str,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
):
    adjustment = db.query(TimeCardAdjustment).filter(
        TimeCardAdjustment.company_id == caller.company_id,
        TimeCardAdjustment.id == adjustment_id
    ).first()

    if not adjustment:
        logger.warning(f"Could not find adjustment ID: {adjustment_id}")
        raise HTTPException(status_code=404, detail=f"Adjustment ID {adjustment_id} not found!")

    if caller.id != adjustment.employee_id:
        raise HTTPException(status_code=403, detail="You are not authorized to access this page")
    
    if adjustment.status != "pending_employee":
        raise HTTPException(status_code=409, detail="Adjustment is not awaiting employee sign-off")
    
    adjustment.status = "pending_manager"
    adjustment.employee_signed_off_at = datetime.now(timezone.utc)
    db.commit()
    write_audit(
        db, actor_id=str(caller.id),
        company_id=caller.company_id,
        action_type="timecard_adjustment.employee_signed_off",
        target_table="timecard_adjustments",
        target_id=str(adjustment.id),
        before={"status": "pending_employee"}, after={"status": "pending_manager"}
    )

    managers_and_admins = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.role.in_(["admin", "manager"]),
        Employee.is_active == True
    ).all()
    for person in managers_and_admins:
        db.add(Notification(
            company_id = caller.company_id,
            employee_id = person.id,
            type = "timecard_pending_manager",
            message = (
                f"{caller.name.title()} has signed off on a timecard adjustment for "
                f"{adjustment.work_date}. Manager approval required."
            )
        ))
    db.commit()

    return {"detail": "Employee successfully signed off on adjustment"}

@router.post("/adjustments/{adjustment_id}/manager_approve", status_code=status.HTTP_201_CREATED)
async def manager_sign_off(
    adjustment_id: str,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee),
    _: bool = Depends(allow_manager_or_admin)
):
    adjustment = db.query(TimeCardAdjustment).filter(
        TimeCardAdjustment.company_id == caller.company_id,
        TimeCardAdjustment.id == adjustment_id
    ).first()

    if not adjustment:
        raise HTTPException(status_code=404, detail="Adjustment not found")

    if adjustment.status != "pending_manager":
        raise HTTPException(status_code=409, detail="Adjustment status is not awaiting manager approval")
    
    adjustment.status = "approved"
    adjustment.manager_id = caller.id
    adjustment.manager_approved_at = datetime.now(timezone.utc)
    db.commit()

    integration = db.query(ADPIntegration).filter(
        ADPIntegration.company_id == caller.company_id
    ).first()

    employee = db.query(Employee).filter(
        Employee.company_id == caller.company_id,
        Employee.id == adjustment.employee_id,
    ).first()

    pay_period = db.query(ADPPayPeriod).filter(
        ADPPayPeriod.company_id == caller.company_id,
        ADPPayPeriod.id == adjustment.pay_period_id
    ).first()

    try:
        adp_response = await patch_adp_timecard(
            integration,
            employee.hr_system_id_adp,
            pay_period.adp_pay_period_id,
            adjustment.proposed_break_start_at,
            adjustment.proposed_break_end_at
        )

        adjustment.status = "applied"
        adjustment.adp_applied_at = datetime.now(timezone.utc)
        adjustment.adp_response_payload = adp_response
    
    except ADPClientError as e:
        notif_message = (
            f"ADP timecard update to failed due to malformed "
            f"payload, please review before retrying: {e.body}\n"
            f"Employee: {employee.name}\n"
            f'Break: {adjustment.proposed_break_start_at.strftime("%I:%M %p")} - {adjustment.proposed_break_end_at.strftime("%I:%M %p")}'
        )
        adjustment.status = "write_failed"
        adjustment.write_attempt_count += 1
        managers_and_admins = db.query(Employee).filter(
            Employee.company_id == caller.company_id,
            Employee.role.in_(["admin", "manager"]),
            Employee.is_active == True
        ).all()
        for person in managers_and_admins:
            db.add(Notification(
                company_id = caller.company_id,
                employee_id = person.id,
                type = "timecard_update_failed",
                message = notif_message
            ))
        adjustment.is_retryable = False
     
    except ADPServerError as e:
        adjustment.status = "write_failed"
        adjustment.write_attempt_count += 1

    db.commit()
    write_audit(
        db, actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="timecard_adjustment.manager_approval",
        target_table="timecard_adjustments",
        target_id=str(adjustment.id),
        before={"status": "pending_manager"},
        after={"status": adjustment.status}
    )

    if adjustment.status == "applied":
        notif_message = (
            f"Your timecard adjustment for {adjustment.work_date} has been approved "
            f"and successfully submitted to ADP."
        )
    else:
        notif_message = (
            f"Your timecard adjustment for {adjustment.work_date} was approved but "
            f"could not be submitted to ADP. Your manager has been notified."
        )
    db.add(Notification(
        company_id = caller.company_id,
        employee_id = adjustment.employee_id,
        type = "timecard_applied",
        message = notif_message
    ))
    db.commit()

    return {"detail": "Adjustment Approved", "status": adjustment.status}

@router.post("/adjustments/{adjustment_id}/reject", status_code=status.HTTP_202_ACCEPTED)
def reject_adjustment(
    adjustment_id: str,
    db: Session = Depends(get_db),
    caller: Employee = Depends(get_caller_employee)
) -> dict:
    
    adjustment = db.query(TimeCardAdjustment).filter(
        TimeCardAdjustment.company_id == caller.company_id,
        TimeCardAdjustment.id == adjustment_id
    ).first()

    if not adjustment:
        raise HTTPException(status_code=404, detail="Adjustment not found")
    
    if adjustment.status == "pending_employee":
        if caller.id != adjustment.employee_id and caller.role != "admin":
            raise HTTPException(status_code=403, detail="Only the employee on record or an admin can reject at this stage")
    
    elif adjustment.status == "pending_manager":
        if caller.role not in ["admin", "manager"]:
            raise HTTPException(status_code=403, detail="Only a manager or admin can reject at this stage")

    else:
        raise HTTPException(status_code=409, detail="Adjustment cannot be rejected at the current stage. Please speak to your manager or admin for assistance")
    
    previous_status = adjustment.status
    adjustment.status = "rejected"
    db.commit()

    write_audit(
        db, actor_id=str(caller.id),
        company_id=str(caller.company_id),
        action_type="timecard_adjustments.reject",
        target_table="timecard_adjustments",
        target_id=str(adjustment.id),
        before={"status": previous_status},
        after={"status": adjustment.status}
    )

    if previous_status == "pending_employee":
        # Employee disputed — notify managers/admins
        managers_and_admins = db.query(Employee).filter(
            Employee.company_id == caller.company_id,
            Employee.role.in_(["admin", "manager"]),
            Employee.is_active == True
        ).all()
        for person in managers_and_admins:
            db.add(Notification(
                company_id = caller.company_id,
                employee_id = person.id,
                type = "timecard_rejected",
                message = (
                    f"{caller.name.title()} has disputed their timecard adjustment for "
                    f"{adjustment.work_date}. Please review."
                )
            ))
    else:
        # Manager rejected — notify the employee
        db.add(Notification(
            company_id = caller.company_id,
            employee_id = adjustment.employee_id,
            type = "timecard_rejected",
            message = (
                f"Your timecard adjustment for {adjustment.work_date} has been rejected "
                f"by your manager. Please contact your manager for details."
            )
        ))
    db.commit()

    return {"detail": "Adjustment Rejected", "status": adjustment.status}