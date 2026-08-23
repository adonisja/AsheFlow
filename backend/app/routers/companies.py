import logging
import re
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import get_super_admin, get_caller_employee, RoleChecker
from app.services.company_config import _REQUIRED_FIELDS
from app.services.constants import OVERSIGHT_ROLES
from app.core.config import settings
from app.database import get_db
from app.services.audit import write_audit, super_admin_identity
from app.models.company import Company, CompanyConfig
from app.models.employee import Employee
from app.models.invite_token import InviteToken
from app.services.email import send_invite_email
from datetime import time as dt_time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/companies", tags=["companies"])

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CompanyCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    slug: str = Field(..., min_length=2, max_length=100)
    amazon_dsp_code: Optional[str] = Field(None, max_length=20)
    timezone: str = Field(default="America/New_York", max_length=64)

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens.")
        return v

    @field_validator("name")
    @classmethod
    def name_strip(cls, v: str) -> str:
        return v.strip()


class CompanyResponse(BaseModel):
    id: UUID
    name: str
    slug: str
    amazon_dsp_code: Optional[str]
    timezone: str
    is_active: bool
    created_at: datetime
    has_admin: bool = False
    # ADR-280 D5: super admin is the ONE surface that spans tenants, so it is
    # the one place this has to be visible. Every other analytics endpoint is
    # already scoped to caller.company_id — a user inside a seed tenant seeing
    # seeded numbers is correct, not contamination, and filtering those queries
    # on data_class would return nothing at all for those users.
    data_class: str = "live"

    model_config = {"from_attributes": True}


class CompanyDetailResponse(CompanyResponse):
    """Extended response that includes the company's config row."""
    config: Optional["CompanyConfigResponse"]


class CompanyUpdate(BaseModel):
    """Partial update for company identity fields."""
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    slug: Optional[str] = Field(None, min_length=2, max_length=100)
    amazon_dsp_code: Optional[str] = Field(None, max_length=20)
    timezone: Optional[str] = Field(None, max_length=64)

    @field_validator("slug")
    @classmethod
    def slug_format(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens.")
        return v

    @field_validator("name")
    @classmethod
    def name_strip(cls, v: str) -> str:
        return v.strip()


class AdminSummary(BaseModel):
    employee_id: UUID
    name: str
    email: Optional[str]
    account_status: str

    model_config = {"from_attributes": True}


class EmployeeSummaryResponse(BaseModel):
    total: int
    by_role: dict[str, int]
    admins: list[AdminSummary]


class CompanyConfigResponse(BaseModel):
    id: UUID
    company_id: UUID
    shift_start:                      Optional[str]
    shift_end:                        Optional[str]
    checkin_open:                     Optional[str]
    checkin_close:                    Optional[str]
    dispatch_confirmation_cutoff:     Optional[str]
    rating_window_hours:              Optional[int]
    invite_expiry_days:               Optional[int]
    is_configured:                    bool
    graduation_assignments:           Optional[int]
    debt_escalation_threshold:        Optional[int]
    phase4_pass_score:                Optional[float]
    underperforming_trainer_threshold: Optional[int]
    max_training_phase:               Optional[int]
    dispatch_weight_driver:           Optional[float]
    dispatch_weight_trainer:          Optional[float]
    dispatch_weight_walker:           Optional[float]
    dispatch_mutual_bonus:            Optional[float]
    dispatch_tridirectional_bonus:    Optional[float]
    dispatch_consecutive_penalty:     Optional[float]
    dispatch_weight_cap:              Optional[float]
    flag_threshold:                   Optional[float]
    driver_checkin_count:             Optional[int]
    late_window_minutes:              Optional[int]
    ncns_cutoff_minutes:              Optional[int]
    effort_time_factor:               Optional[float]
    effort_physical_factor:           Optional[float]
    ingestion_mode:                   Optional[str]
    # Scorecard tier targets (ADR-262). None = not configured.
    scorecard_dcr_target:             Optional[float] = None
    scorecard_dnr_dpmo_target:        Optional[int]   = None
    scorecard_pod_target:             Optional[float] = None
    scorecard_cc_target:              Optional[float] = None
    scorecard_cdf_target:             Optional[float] = None
    scorecard_dsb_dpmo_target:        Optional[int]   = None
    scorecard_fico_target:            Optional[int]   = None
    scorecard_speeding_rate_target:   Optional[float] = None
    scorecard_signsignal_rate_target: Optional[float] = None
    scorecard_dvic_target:            Optional[float] = None
    # Route-sort tuning (ADR-273). None = using the code default.
    sort_w_dense:                     Optional[float] = None
    sort_w_time:                      Optional[float] = None
    sort_w_diff:                      Optional[float] = None
    sort_w_doorman:                   Optional[float] = None
    sort_walk_budget_m:               Optional[float] = None
    sort_span_cap_m:                  Optional[float] = None
    sort_max_consecutive_no_fit:      Optional[int]   = None
    sort_f5_load_floor_hs:            Optional[int]   = None
    sort_f5_max_hops:                 Optional[int]   = None
    sort_f5_walk_radius_km:           Optional[float] = None
    route_assembly_mode:              Optional[str]   = None

    model_config = {"from_attributes": True}

    @staticmethod
    def _fmt_time(t) -> Optional[str]:
        return t.strftime("%H:%M") if t else None

    @classmethod
    def from_orm_obj(cls, obj: CompanyConfig) -> "CompanyConfigResponse":
        return cls(
            id=obj.id,
            company_id=obj.company_id,
            shift_start=cls._fmt_time(obj.shift_start),
            shift_end=cls._fmt_time(obj.shift_end),
            checkin_open=cls._fmt_time(obj.checkin_open),
            checkin_close=cls._fmt_time(obj.checkin_close),
            dispatch_confirmation_cutoff=cls._fmt_time(obj.dispatch_confirmation_cutoff),
            rating_window_hours=obj.rating_window_hours,
            invite_expiry_days=obj.invite_expiry_days,
            is_configured=obj.is_configured,
            graduation_assignments=obj.graduation_assignments,
            debt_escalation_threshold=obj.debt_escalation_threshold,
            phase4_pass_score=obj.phase4_pass_score,
            underperforming_trainer_threshold=obj.underperforming_trainer_threshold,
            max_training_phase=obj.max_training_phase,
            dispatch_weight_driver=obj.dispatch_weight_driver,
            dispatch_weight_trainer=obj.dispatch_weight_trainer,
            dispatch_weight_walker=obj.dispatch_weight_walker,
            dispatch_mutual_bonus=obj.dispatch_mutual_bonus,
            dispatch_tridirectional_bonus=obj.dispatch_tridirectional_bonus,
            dispatch_consecutive_penalty=obj.dispatch_consecutive_penalty,
            dispatch_weight_cap=obj.dispatch_weight_cap,
            flag_threshold=obj.flag_threshold,
            driver_checkin_count=obj.driver_checkin_count,
            late_window_minutes=obj.late_window_minutes,
            ncns_cutoff_minutes=obj.ncns_cutoff_minutes,
            effort_time_factor=obj.effort_time_factor,
            effort_physical_factor=obj.effort_physical_factor,
            ingestion_mode=obj.ingestion_mode,
            scorecard_dcr_target=obj.scorecard_dcr_target,
            scorecard_dnr_dpmo_target=obj.scorecard_dnr_dpmo_target,
            scorecard_pod_target=obj.scorecard_pod_target,
            scorecard_cc_target=obj.scorecard_cc_target,
            scorecard_cdf_target=obj.scorecard_cdf_target,
            scorecard_dsb_dpmo_target=obj.scorecard_dsb_dpmo_target,
            scorecard_fico_target=obj.scorecard_fico_target,
            scorecard_speeding_rate_target=obj.scorecard_speeding_rate_target,
            scorecard_signsignal_rate_target=obj.scorecard_signsignal_rate_target,
            scorecard_dvic_target=obj.scorecard_dvic_target,
            sort_w_dense=obj.sort_w_dense,
            sort_w_time=obj.sort_w_time,
            sort_w_diff=obj.sort_w_diff,
            sort_w_doorman=obj.sort_w_doorman,
            sort_walk_budget_m=obj.sort_walk_budget_m,
            sort_span_cap_m=obj.sort_span_cap_m,
            sort_max_consecutive_no_fit=obj.sort_max_consecutive_no_fit,
            sort_f5_load_floor_hs=obj.sort_f5_load_floor_hs,
            sort_f5_max_hops=obj.sort_f5_max_hops,
            sort_f5_walk_radius_km=obj.sort_f5_walk_radius_km,
            route_assembly_mode=obj.route_assembly_mode,
        )


CompanyDetailResponse.model_rebuild()


class DiscordConfigUpdate(BaseModel):
    discord_guild_id:            Optional[int] = None
    discord_drivers_channel_id:  Optional[int] = None
    discord_trainers_channel_id: Optional[int] = None
    discord_captains_channel_id: Optional[int] = None
    discord_general_channel_id:  Optional[int] = None
    discord_invite_channel_id:   Optional[int] = None
    discord_role_admin:          Optional[int] = None
    discord_role_manager:        Optional[int] = None
    discord_role_asheflow:       Optional[int] = None
    discord_role_bot:            Optional[int] = None
    discord_role_dispatch:       Optional[int] = None
    discord_role_driver:         Optional[int] = None
    discord_role_trainer:        Optional[int] = None
    discord_role_captain:        Optional[int] = None
    discord_role_walker:         Optional[int] = None


class DiscordConfigResponse(BaseModel):
    discord_guild_id:            Optional[str] = None
    discord_drivers_channel_id:  Optional[str] = None
    discord_trainers_channel_id: Optional[str] = None
    discord_captains_channel_id: Optional[str] = None
    discord_general_channel_id:  Optional[str] = None
    discord_invite_channel_id:   Optional[str] = None
    discord_role_admin:          Optional[str] = None
    discord_role_manager:        Optional[str] = None
    discord_role_asheflow:       Optional[str] = None
    discord_role_bot:            Optional[str] = None
    discord_role_dispatch:       Optional[str] = None
    discord_role_driver:         Optional[str] = None
    discord_role_trainer:        Optional[str] = None
    discord_role_captain:        Optional[str] = None
    discord_role_walker:         Optional[str] = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_config(cls, config) -> "DiscordConfigResponse":
        fields = [
            "discord_guild_id", "discord_drivers_channel_id", "discord_trainers_channel_id",
            "discord_captains_channel_id", "discord_general_channel_id", "discord_invite_channel_id",
            "discord_role_admin", "discord_role_manager", "discord_role_asheflow",
            "discord_role_bot", "discord_role_dispatch", "discord_role_driver",
            "discord_role_trainer", "discord_role_captain", "discord_role_walker",
        ]
        return cls(**{f: str(getattr(config, f)) if getattr(config, f) is not None else None for f in fields})


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
def create_company(
    payload: CompanyCreate,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Provision a new tenant company.

    Creates the Company row and a blank CompanyConfig row in one transaction.
    The config row starts with all fields null — services fall back to the
    hardcoded defaults in constants.py until the company admin configures them.

    Slug must be unique and URL-safe (lowercase, numbers, hyphens only).
    """
    if db.query(Company).filter(Company.slug == payload.slug).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A company with slug '{payload.slug}' already exists.",
        )

    company = Company(
        name=payload.name,
        slug=payload.slug,
        amazon_dsp_code=payload.amazon_dsp_code,
        timezone=payload.timezone,
    )
    db.add(company)
    db.flush()  # populate company.id before creating config

    db.add(CompanyConfig(company_id=company.id))

    write_audit(
        db=db,
        company_id=str(company.id),
        action_type="company.create",
        target_table="companies",
        target_id=str(company.id),
        after={**super_admin_identity(_), "name": company.name, "slug": company.slug,
               "amazon_dsp_code": company.amazon_dsp_code, "timezone": company.timezone},
    )
    db.commit()
    db.refresh(company)
    return company


@router.get("/", response_model=list[CompanyResponse])
def list_companies(
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """List all tenant companies. Super admin only."""
    companies = db.query(Company).order_by(Company.created_at.desc()).all()
    admin_company_ids = {
        row.company_id
        for row in db.query(Employee.company_id)
        .filter(Employee.role == "admin", Employee.is_active == True)
        .distinct()
        .all()
    }
    result = []
    for c in companies:
        resp = CompanyResponse.model_validate(c)
        resp.has_admin = c.id in admin_company_ids
        result.append(resp)
    return result


@router.get("/{company_id}", response_model=CompanyDetailResponse)
def get_company(
    company_id: UUID,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Get a single company with its current config. Super admin only."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    config = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    config_resp = CompanyConfigResponse.from_orm_obj(config) if config else None

    return CompanyDetailResponse(
        id=company.id,
        name=company.name,
        slug=company.slug,
        amazon_dsp_code=company.amazon_dsp_code,
        timezone=company.timezone,
        is_active=company.is_active,
        created_at=company.created_at,
        config=config_resp,
    )


@router.patch("/{company_id}", response_model=CompanyResponse)
def update_company(
    company_id: UUID,
    payload: CompanyUpdate,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Update company identity fields. Super admin only."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    data = payload.model_dump(exclude_unset=True)

    if "slug" in data and data["slug"] != company.slug:
        if db.query(Company).filter(Company.slug == data["slug"]).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A company with slug '{data['slug']}' already exists.",
            )

    before = {k: getattr(company, k) for k in data}
    for field, value in data.items():
        setattr(company, field, value)

    write_audit(
        db=db,
        company_id=str(company.id),
        action_type="company.update",
        target_table="companies",
        target_id=str(company.id),
        before=before,
        after={**super_admin_identity(_), **data},
    )
    db.commit()
    db.refresh(company)
    return company


@router.get("/{company_id}/employees/summary", response_model=EmployeeSummaryResponse)
def get_employee_summary(
    company_id: UUID,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Return headcount by role and a list of admin employees for a company."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    employees = db.query(Employee).filter(Employee.company_id == company_id).all()

    by_role: dict[str, int] = {}
    for emp in employees:
        by_role[emp.role] = by_role.get(emp.role, 0) + 1

    admins = [
        AdminSummary(
            employee_id=emp.id,
            name=emp.name,
            email=emp.email,
            account_status=emp.account_status,
        )
        for emp in employees
        if emp.role == "admin"
    ]

    return EmployeeSummaryResponse(
        total=len(employees),
        by_role=by_role,
        admins=admins,
    )


@router.patch("/{company_id}/deactivate", response_model=CompanyResponse)
def deactivate_company(
    company_id: UUID,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Deactivate a company. Super admin only.

    Sets is_active=False. Does not delete any data. The company's employees
    can no longer log in (enforced at the application layer — future work).
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    if not company.is_active:
        raise HTTPException(status_code=400, detail="Company is already inactive.")

    company.is_active = False
    # The highest-impact action in this router: every employee of the tenant
    # loses access. Recording who and when is the point of an audit trail.
    write_audit(
        db=db,
        company_id=str(company.id),
        action_type="company.deactivate",
        target_table="companies",
        target_id=str(company.id),
        before={"is_active": True},
        after={**super_admin_identity(_), "is_active": False, "name": company.name},
    )
    db.commit()
    db.refresh(company)
    return company


@router.patch("/{company_id}/reactivate", response_model=CompanyResponse)
def reactivate_company(
    company_id: UUID,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Reactivate a previously deactivated company. Super admin only."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    if company.is_active:
        raise HTTPException(status_code=400, detail="Company is already active.")

    company.is_active = True
    write_audit(
        db=db,
        company_id=str(company.id),
        action_type="company.reactivate",
        target_table="companies",
        target_id=str(company.id),
        before={"is_active": False},
        after={**super_admin_identity(_), "is_active": True, "name": company.name},
    )
    db.commit()
    db.refresh(company)
    return company


# ---------------------------------------------------------------------------
# Bootstrap — provision the first admin employee for a new company
# ---------------------------------------------------------------------------

class BootstrapRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr

    @field_validator("name")
    @classmethod
    def name_strip(cls, v: str) -> str:
        return v.strip()


class BootstrapResponse(BaseModel):
    employee_id: UUID
    name: str
    email: str
    role: str
    account_status: str
    invite_sent: bool

    model_config = {"from_attributes": True}


@router.post("/{company_id}/bootstrap", response_model=BootstrapResponse, status_code=status.HTTP_201_CREATED)
def bootstrap_company_admin(
    company_id: UUID,
    payload: BootstrapRequest,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Provision the first admin employee for a newly created company.

    Creates an Employee row with role='admin' and account_status='not_invited',
    generates an invite token, and emails the registration link to the provided
    address. The admin then registers through the standard /register?token=...
    flow — no special path for the first admin.

    Safe to call multiple times: if an admin employee with the same email already
    exists for this company, a fresh invite token is issued instead of creating
    a duplicate row.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    if not company.is_active:
        raise HTTPException(status_code=400, detail="Cannot bootstrap an inactive company.")

    # Idempotent — re-use existing admin row if email already registered
    employee = db.query(Employee).filter(
        Employee.company_id == company_id,
        Employee.email == payload.email,
    ).first()

    if employee:
        if employee.account_status == "active":
            raise HTTPException(
                status_code=409,
                detail="An active admin with that email already exists for this company.",
            )
        # Existing but not yet active — fall through and re-issue their invite
    else:
        employee = Employee(
            company_id=company_id,
            name=payload.name,
            email=payload.email,
            role="admin",
            is_active=False,
            account_status="pending_verification",
        )
        db.add(employee)
        db.flush()  # populate employee.id

    # Invalidate any prior token for this employee
    db.query(InviteToken).filter(InviteToken.employee_id == employee.id).delete()

    token_str = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.invite_expiry_days)
    db.add(InviteToken(
        token=token_str,
        company_id=company_id,
        employee_id=employee.id,
        expires_at=expires_at,
    ))

    employee.invited_at = datetime.now(timezone.utc)
    # Account provisioning: this creates the tenant's FIRST admin and the invite
    # that grants them access. The token itself is never recorded — an audit row
    # is readable by other admins, and a live invite token is a credential.
    write_audit(
        db=db,
        company_id=str(company_id),
        action_type="company.bootstrap_admin",
        target_table="employees",
        target_id=str(employee.id),
        after={**super_admin_identity(_), "employee_id": str(employee.id), "role": employee.role,
               "invite_expires_at": expires_at.isoformat()},
    )
    db.commit()
    db.refresh(employee)

    invite_sent = False
    try:
        send_invite_email(
            to_email=employee.email,
            employee_name=employee.name,
            token=token_str,
        )
        invite_sent = True
    except ClientError as e:
        logger.error("Bootstrap invite email failed for %s: %s", employee.email, e)
        # Don't roll back — the token is valid, super admin can retry

    return BootstrapResponse(
        employee_id=employee.id,
        name=employee.name,
        email=employee.email,
        role=employee.role,
        account_status=employee.account_status,
        invite_sent=invite_sent,
    )


# ---------------------------------------------------------------------------
# Company config — shared schema, two access paths
# ---------------------------------------------------------------------------

# Fields only super_admin may touch
# ADR-273: route-sort tuning is super-admin only. These change how routes are
# built for the entire tenant, and the telemetry that says which one to move is
# only readable at that level — a company admin can see their routes, not the
# cross-run series that justifies a weight change.
_SORT_TUNING_FIELDS = frozenset({
    "sort_w_dense", "sort_w_time", "sort_w_diff", "sort_w_doorman",
    "sort_walk_budget_m", "sort_span_cap_m", "sort_max_consecutive_no_fit",
    "sort_f5_load_floor_hs", "sort_f5_max_hops", "sort_f5_walk_radius_km",
    "route_assembly_mode",
})

_SUPER_ADMIN_ONLY_FIELDS = frozenset({"invite_expiry_days"}) | _SORT_TUNING_FIELDS

# All editable config fields with their types (used for validation messaging)
_TIME_FIELDS = frozenset({"shift_start", "shift_end", "checkin_open", "checkin_close", "dispatch_confirmation_cutoff"})


def _parse_time(value: str, field: str) -> dt_time:
    """Parse 'HH:MM' string into a datetime.time. Raises ValueError on bad input."""
    try:
        h, m = value.split(":")
        return dt_time(int(h), int(m))
    except Exception:
        raise ValueError(f"'{field}' must be in HH:MM format (e.g. '07:00').")


class CompanyConfigUpdate(BaseModel):
    """All config fields are optional — only provided fields are updated (PATCH semantics).

    Time fields are accepted as 'HH:MM' strings.
    invite_expiry_days is accepted in the schema but rejected for non-super-admin callers
    at the endpoint layer.
    """
    # Shift timing
    shift_start:                     Optional[str]   = None
    shift_end:                       Optional[str]   = None
    checkin_open:                    Optional[str]   = None
    checkin_close:                   Optional[str]   = None
    dispatch_confirmation_cutoff:    Optional[str]   = None

    # Operational
    rating_window_hours:             Optional[int]   = Field(None, ge=1, le=48)
    invite_expiry_days:              Optional[int]   = Field(None, ge=1, le=90)

    # Training
    graduation_assignments:          Optional[int]   = Field(None, ge=1, le=30)
    debt_escalation_threshold:       Optional[int]   = Field(None, ge=1, le=30)
    phase4_pass_score:               Optional[float] = Field(None, ge=0.0, le=100.0)
    underperforming_trainer_threshold: Optional[int] = Field(None, ge=1, le=30)
    max_training_phase:              Optional[int]   = Field(None, ge=1, le=10)

    # Dispatch weights
    dispatch_weight_driver:          Optional[float] = Field(None, ge=0.0, le=1.0)
    dispatch_weight_trainer:         Optional[float] = Field(None, ge=0.0, le=1.0)
    dispatch_weight_walker:          Optional[float] = Field(None, ge=0.0, le=1.0)
    dispatch_mutual_bonus:           Optional[float] = Field(None, ge=0.0, le=1.0)
    dispatch_tridirectional_bonus:   Optional[float] = Field(None, ge=0.0, le=1.0)
    dispatch_consecutive_penalty:    Optional[float] = Field(None, ge=0.0, le=1.0)
    dispatch_weight_cap:             Optional[float] = Field(None, ge=0.0, le=1.0)

    # Walker rating
    flag_threshold:                  Optional[float] = Field(None, ge=0.0, le=10.0)

    # Driver check-ins
    driver_checkin_count:            Optional[int]   = Field(None, ge=0, le=10)

    # Attendance (ADR-198/228)
    late_window_minutes:             Optional[int]   = Field(None, ge=0, le=240)
    ncns_cutoff_minutes:             Optional[int]   = Field(None, ge=1, le=480)

    # Effort scoring
    effort_time_factor:              Optional[float] = Field(None, ge=0.0, le=1.0)
    effort_physical_factor:          Optional[float] = Field(None, ge=0.0, le=1.0)

    # Manifest ingestion
    ingestion_mode:                  Optional[str]   = None

    # Route-sort tuning (ADR-273). Super-admin only — these change how routes
    # are built for the whole tenant, and the telemetry that tells you which one
    # to move is only readable at that level. Bounded per Dimension 9: every one
    # is attacker-controlled input that feeds a hot algorithm loop.
    #
    # Weights: 0–5 is generous. The invariant that matters (W_TIME/W_DIFF above
    # W_DENSE, so a KNOWN urgent block outranks the densest unknown-easy one) is
    # not expressible as a per-field bound — it is validated below.
    sort_w_dense:                    Optional[float] = Field(None, ge=0.0, le=5.0)
    sort_w_time:                     Optional[float] = Field(None, ge=0.0, le=5.0)
    sort_w_diff:                     Optional[float] = Field(None, ge=0.0, le=5.0)
    sort_w_doorman:                  Optional[float] = Field(None, ge=0.0, le=5.0)
    # Traversal guards. Floors are non-zero: a 0 m budget would close every
    # route after its seed block.
    sort_walk_budget_m:              Optional[float] = Field(None, ge=100.0, le=10000.0)
    sort_span_cap_m:                 Optional[float] = Field(None, ge=100.0, le=10000.0)
    sort_max_consecutive_no_fit:     Optional[int]   = Field(None, ge=1, le=20)
    # F5 thin-block consolidation. load_floor is in HALF-slots (6 ≈ 3 totes).
    sort_f5_load_floor_hs:           Optional[int]   = Field(None, ge=0, le=40)
    sort_f5_max_hops:                Optional[int]   = Field(None, ge=1, le=6)
    sort_f5_walk_radius_km:          Optional[float] = Field(None, ge=0.1, le=5.0)
    # Route assembly mode (ADR-272): "block_completion" | "group_first".
    # max_length in addition to the enum validator below: bounding the field is
    # what stops an oversized string reaching the validator at all (Dimension 9).
    route_assembly_mode:             Optional[str]   = Field(None, max_length=20)

    @field_validator("route_assembly_mode")
    @classmethod
    def _valid_assembly_mode(cls, v):
        if v is None:
            return v
        from app.services.sort_tuning import VALID_ASSEMBLY_MODES
        if v not in VALID_ASSEMBLY_MODES:
            raise ValueError(
                f"route_assembly_mode must be one of {sorted(VALID_ASSEMBLY_MODES)}"
            )
        return v

    # Amazon scorecard tier targets (ADR-262). Bounded per Dimension 9 — these
    # are attacker-controlled input. Percentages 0–100; DPMO 0–1,000,000 (a
    # defect rate cannot exceed one million per million); FICO on its real
    # 100–850 scale; event rates per 100 trips capped generously at 1000.
    scorecard_dcr_target:             Optional[float] = Field(None, ge=0.0, le=100.0)
    scorecard_pod_target:             Optional[float] = Field(None, ge=0.0, le=100.0)
    scorecard_cc_target:              Optional[float] = Field(None, ge=0.0, le=100.0)
    scorecard_cdf_target:             Optional[float] = Field(None, ge=0.0, le=100.0)
    scorecard_dvic_target:            Optional[float] = Field(None, ge=0.0, le=100.0)
    scorecard_dnr_dpmo_target:        Optional[int]   = Field(None, ge=0, le=1_000_000)
    scorecard_dsb_dpmo_target:        Optional[int]   = Field(None, ge=0, le=1_000_000)
    scorecard_fico_target:            Optional[int]   = Field(None, ge=100, le=850)
    scorecard_speeding_rate_target:   Optional[float] = Field(None, ge=0.0, le=1000.0)
    scorecard_signsignal_rate_target: Optional[float] = Field(None, ge=0.0, le=1000.0)


def _apply_config_update(config: CompanyConfig, payload: CompanyConfigUpdate, allow_super_admin_fields: bool = False) -> None:
    """Apply a CompanyConfigUpdate to a CompanyConfig ORM object in place.

    After writing all fields, automatically sets is_configured=True once
    every required field is non-null.  is_configured can never go back to
    False through this path — super admin would have to do it directly.
    """
    data = payload.model_dump(exclude_unset=True)

    for field, value in data.items():
        if field in _SUPER_ADMIN_ONLY_FIELDS and not allow_super_admin_fields:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"'{field}' can only be changed by a super admin.",
            )
        if field in _TIME_FIELDS and value is not None:
            value = _parse_time(value, field)
        setattr(config, field, value)

    # ADR-273: the seed-priority invariant is a RELATIONSHIP between weights, so
    # it cannot be expressed as a per-field bound and has to be checked on the
    # merged state (a PATCH may set only one of them).
    #
    # ADR-186 D3: W_TIME and W_DIFF sit ABOVE W_DENSE so a KNOWN urgent or hard
    # block outranks the densest unknown-easy one. Invert that and a block with a
    # cutoff 20 minutes away loses to whichever block happens to hold the most
    # totes — the failure ADR-189 called out as needing structure, not weights.
    from app.services.sort_tuning import (
        DEFAULT_W_DENSE, DEFAULT_W_TIME, DEFAULT_W_DIFF,
    )
    if any(f in data for f in ("sort_w_dense", "sort_w_time", "sort_w_diff")):
        w_dense = config.sort_w_dense if config.sort_w_dense is not None else DEFAULT_W_DENSE
        w_time  = config.sort_w_time  if config.sort_w_time  is not None else DEFAULT_W_TIME
        w_diff  = config.sort_w_diff  if config.sort_w_diff  is not None else DEFAULT_W_DIFF
        if w_time < w_dense or w_diff < w_dense:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "sort_w_time and sort_w_diff must each be >= sort_w_dense, so a "
                    "known-urgent or known-hard block still outranks the densest "
                    "unknown-easy one (ADR-186 D3)."
                ),
            )

    if not config.is_configured:
        all_set = all(getattr(config, f) is not None for f in _REQUIRED_FIELDS)
        if all_set:
            config.is_configured = True


# ---------------------------------------------------------------------------
# Super admin: PATCH any company's config
# ---------------------------------------------------------------------------

@router.patch("/{company_id}/config", response_model=CompanyConfigResponse)
def update_company_config_super_admin(
    company_id: UUID,
    payload: CompanyConfigUpdate,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Update a company's config. Super admin only — can set all fields including invite_expiry_days."""
    config = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Company config not found.")

    changed = payload.model_dump(exclude_unset=True)
    before = {k: getattr(config, k, None) for k in changed}
    _apply_config_update(config, payload, allow_super_admin_fields=True)
    write_audit(
        db=db,
        company_id=str(company_id),
        action_type="company_config.update",
        target_table="company_configs",
        target_id=str(config.id),
        before=before,
        after={**super_admin_identity(_), **changed},
    )
    db.commit()
    db.refresh(config)
    return CompanyConfigResponse.from_orm_obj(config)


# ---------------------------------------------------------------------------
# Company admin: read + update their own config
# ---------------------------------------------------------------------------

company_admin_router = APIRouter(prefix="/companies", tags=["company-config"])

allow_admin = RoleChecker(["admin"])
allow_management = RoleChecker(["management", "admin"])
# /my-info returns only the caller's own company name and timezone — not
# sensitive, and DISPATCH is the role that lives on the page needing it. Gated
# to management/admin, every dispatcher 403'd on every Dispatch Dashboard load;
# the frontend swallows it, so the only symptom was a missing timezone label
# beside the date, on the page where the date matters most.
#
# OVERSIGHT_ROLES rather than a hand-written list: the same set is already the
# notification fan-out audience, so "who oversees operations" has one spelling.
allow_oversight = RoleChecker(list(OVERSIGHT_ROLES))


@company_admin_router.get("/my-info")
def get_my_company_info(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_oversight),
    db: Session = Depends(get_db),
):
    """Return name and timezone for the caller's company. Oversight roles."""
    company = db.query(Company).filter(Company.id == caller.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")
    return {"name": company.name, "timezone": company.timezone}


@company_admin_router.get("/my-config", response_model=CompanyConfigResponse)
def get_my_company_config(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Return the calling company admin's company config."""
    config = db.query(CompanyConfig).filter(CompanyConfig.company_id == caller.company_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Company config not found.")
    return CompanyConfigResponse.from_orm_obj(config)


@company_admin_router.patch("/my-config", response_model=CompanyConfigResponse)
def update_my_company_config(
    payload: CompanyConfigUpdate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Update the calling company admin's company config.

    All fields are optional — only provided fields are written.
    invite_expiry_days is locked to super admin; any attempt to set it here
    returns 403.
    """
    config = db.query(CompanyConfig).filter(CompanyConfig.company_id == caller.company_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Company config not found.")

    # ADR-228 reverse guard: raising the NCNS cutoff above an already-configured
    # Check-In #1 would break "Check-In #1 >= NCNS". Catch it here (the add-deadline
    # path enforces the forward direction).
    data = payload.model_dump(exclude_unset=True)
    if data.get("ncns_cutoff_minutes") is not None:
        first = (
            db.query(CheckInDeadline)
            .filter(CheckInDeadline.company_id == caller.company_id, CheckInDeadline.sequence == 1)
            .first()
        )
        if first is not None and data["ncns_cutoff_minutes"] > first.offset_minutes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"NCNS cutoff ({data['ncns_cutoff_minutes']} min) can't be later than "
                    f"Check-In #1 ({first.offset_minutes} min). Lower it, or move Check-In #1 later first."
                ),
            )

    changed = payload.model_dump(exclude_unset=True)
    before = {k: getattr(config, k, None) for k in changed}
    _apply_config_update(config, payload, allow_super_admin_fields=False)
    # Config drives dispatch weighting, attendance cutoffs and scorecard targets —
    # a silent change here reshapes operational outcomes company-wide.
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="company_config.update",
        target_table="company_configs",
        target_id=str(config.id),
        before=before,
        after=changed,
    )
    db.commit()
    db.refresh(config)
    return CompanyConfigResponse.from_orm_obj(config)


# ── Check-in deadlines (ADR-228) ──────────────────────────────────────────────
# Ordered per-check-in deadlines, each expressed as minutes past the attendance
# reference max(shift_start, AP-established) — same anchor as ncns_cutoff_minutes,
# so Check-In #1 inherits the same late-AP allowance and the ordering guard is a
# direct offset comparison. Replaces the flat CompanyConfig.driver_checkin_count.

from app.models.check_in_deadline import CheckInDeadline


class CheckInDeadlineOut(BaseModel):
    id: UUID
    sequence: int
    offset_minutes: int
    model_config = {"from_attributes": True}


class CheckInDeadlineCreate(BaseModel):
    # Only the deadline is supplied; sequence is assigned server-side (append).
    offset_minutes: int = Field(..., ge=1, le=1440)


def _company_ncns_cutoff(db: Session, company_id: UUID) -> Optional[int]:
    cfg = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    return cfg.ncns_cutoff_minutes if cfg else None


def _list_deadlines(db: Session, company_id: UUID) -> list[CheckInDeadline]:
    return (
        db.query(CheckInDeadline)
        .filter(CheckInDeadline.company_id == company_id)
        .order_by(CheckInDeadline.sequence.asc())
        .all()
    )


@company_admin_router.get("/my-config/check-in-deadlines", response_model=list[CheckInDeadlineOut])
def list_check_in_deadlines(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Ordered check-in deadlines for the caller's company (ADR-228)."""
    return _list_deadlines(db, caller.company_id)


@company_admin_router.post(
    "/my-config/check-in-deadlines", response_model=CheckInDeadlineOut,
    status_code=status.HTTP_201_CREATED,
)
def add_check_in_deadline(
    payload: CheckInDeadlineCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Append the next check-in with its deadline (ADR-228).

    Ordering guards, surfaced to the admin:
      - NCNS cutoff must be set FIRST — you can't schedule a check-in before crew
        are even NCNS-decided.
      - Check-In #1's offset must be >= the NCNS cutoff.
      - each subsequent offset must be strictly greater than the previous.
    """
    ncns = _company_ncns_cutoff(db, caller.company_id)
    if ncns is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Set the NCNS cutoff before adding check-in deadlines — a check-in "
                "can't be scheduled before crew attendance is decided."
            ),
        )

    existing = _list_deadlines(db, caller.company_id)
    next_seq = (existing[-1].sequence + 1) if existing else 1

    if next_seq == 1:
        if payload.offset_minutes < ncns:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Check-In #1 must be at or after the NCNS cutoff ({ncns} min) — "
                    f"got {payload.offset_minutes} min. Crew NCNS must be decided first."
                ),
            )
    else:
        prev = existing[-1].offset_minutes
        if payload.offset_minutes <= prev:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Check-In #{next_seq} ({payload.offset_minutes} min) must be later than "
                    f"Check-In #{next_seq - 1} ({prev} min)."
                ),
            )

    row = CheckInDeadline(
        company_id=caller.company_id, sequence=next_seq, offset_minutes=payload.offset_minutes,
    )
    db.add(row)
    db.flush()
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="check_in_deadline.create",
        target_table="check_in_deadlines",
        target_id=str(row.id),
        after={"sequence": next_seq, "offset_minutes": payload.offset_minutes},
    )
    db.commit()
    db.refresh(row)
    return row


@company_admin_router.delete("/my-config/check-in-deadlines/{sequence}", status_code=status.HTTP_200_OK)
def delete_check_in_deadline(
    sequence: int,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Remove a check-in and renumber the rest so sequences stay contiguous (ADR-228).

    Only the LAST check-in may be removed directly — removing a middle one would
    reorder deadlines under the driver mid-schedule. Renumbering after deleting the
    tail is a no-op; this keeps 'each later than previous' trivially intact.
    """
    existing = _list_deadlines(db, caller.company_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No check-in deadlines configured.")
    if sequence != existing[-1].sequence:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Only the last check-in (#{existing[-1].sequence}) can be removed — "
                "remove from the end so the earlier deadlines keep their order."
            ),
        )
    # Snapshot BEFORE the delete — after it, the row's fields are gone.
    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="check_in_deadline.delete",
        target_table="check_in_deadlines",
        target_id=str(existing[-1].id),
        before={"sequence": existing[-1].sequence,
                "offset_minutes": existing[-1].offset_minutes},
    )
    db.delete(existing[-1])
    db.commit()
    return {"deleted_sequence": sequence, "remaining": len(existing) - 1}


# ---------------------------------------------------------------------------
# Company admin: read + update their own Discord config
# ---------------------------------------------------------------------------

@company_admin_router.get("/my-discord-config", response_model=DiscordConfigResponse)
def get_my_discord_config(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Return the calling company admin's Discord integration config."""
    config = db.query(CompanyConfig).filter(CompanyConfig.company_id == caller.company_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Company config not found.")
    return DiscordConfigResponse.from_config(config)


@company_admin_router.patch("/my-discord-config", response_model=DiscordConfigResponse)
def update_my_discord_config(
    payload: DiscordConfigUpdate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_admin),
    db: Session = Depends(get_db),
):
    """Update the calling company admin's Discord integration config.

    All fields are optional — only provided fields are written.
    """
    config = db.query(CompanyConfig).filter(CompanyConfig.company_id == caller.company_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Company config not found.")

    changed = payload.model_dump(exclude_unset=True)
    before = {k: getattr(config, k, None) for k in changed}
    for field, value in changed.items():
        setattr(config, field, value)

    write_audit(
        db=db,
        company_id=str(caller.company_id),
        actor_id=str(caller.id),
        action_type="company_discord_config.update",
        target_table="company_configs",
        target_id=str(config.id),
        before=before,
        after=changed,
    )
    db.commit()
    db.refresh(config)
    return DiscordConfigResponse.from_config(config)


# ---------------------------------------------------------------------------
# Discord config — super admin only read/write
# ---------------------------------------------------------------------------

@router.get("/{company_id}/discord-config", response_model=DiscordConfigResponse)
def get_company_discord_config(
    company_id: UUID,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Return Discord integration settings for a company. Super admin only."""
    config = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Company config not found.")
    return DiscordConfigResponse.from_config(config)


@router.patch("/{company_id}/discord-config", response_model=DiscordConfigResponse)
def update_company_discord_config(
    company_id: UUID,
    payload: DiscordConfigUpdate,
    _: dict = Depends(get_super_admin),
    db: Session = Depends(get_db),
):
    """Update Discord integration settings for a company. Super admin only."""
    config = db.query(CompanyConfig).filter(CompanyConfig.company_id == company_id).first()
    if not config:
        raise HTTPException(status_code=404, detail="Company config not found.")

    changed = payload.model_dump(exclude_unset=True)
    before = {k: getattr(config, k, None) for k in changed}
    for field, value in changed.items():
        setattr(config, field, value)

    write_audit(
        db=db,
        company_id=str(company_id),
        action_type="company_discord_config.update",
        target_table="company_configs",
        target_id=str(config.id),
        before=before,
        after={**super_admin_identity(_), **changed},
    )
    db.commit()
    db.refresh(config)
    return DiscordConfigResponse.from_config(config)
