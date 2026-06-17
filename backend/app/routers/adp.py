import logging

import boto3

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.adp_integration import ADPIntegration
from app.models.employee import Employee



logger = logging.getLogger(__name__)
router = APIRouter(prefix="/adp", tags=["adp"])

allow_admin = RoleChecker(["admin"])

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