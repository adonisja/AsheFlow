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
from app.core.config import settings
from app.database import get_db
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
    tier1_dbscan_eps:                 Optional[float]
    tier1_dbscan_min_samples:         Optional[int]
    tier1_small_tote_cutoff:          Optional[int]
    tier1_small_stray_max:            Optional[int]
    tier1_small_uncertain_max:        Optional[int]
    tier1_stray_pct:                  Optional[float]
    tier1_uncertain_pct:              Optional[float]
    effort_time_factor:               Optional[float]
    effort_physical_factor:           Optional[float]
    ingestion_mode:                   Optional[str]

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
            tier1_dbscan_eps=obj.tier1_dbscan_eps,
            tier1_dbscan_min_samples=obj.tier1_dbscan_min_samples,
            tier1_small_tote_cutoff=obj.tier1_small_tote_cutoff,
            tier1_small_stray_max=obj.tier1_small_stray_max,
            tier1_small_uncertain_max=obj.tier1_small_uncertain_max,
            tier1_stray_pct=obj.tier1_stray_pct,
            tier1_uncertain_pct=obj.tier1_uncertain_pct,
            effort_time_factor=obj.effort_time_factor,
            effort_physical_factor=obj.effort_physical_factor,
            ingestion_mode=obj.ingestion_mode,
        )


CompanyDetailResponse.model_rebuild()


class DiscordConfigUpdate(BaseModel):
    discord_guild_id:            Optional[int] = None
    discord_drivers_channel_id:  Optional[int] = None
    discord_trainers_channel_id: Optional[int] = None
    discord_general_channel_id:  Optional[int] = None
    discord_invite_channel_id:   Optional[int] = None
    discord_role_admin:          Optional[int] = None
    discord_role_manager:        Optional[int] = None
    discord_role_asheflow:       Optional[int] = None
    discord_role_bot:            Optional[int] = None
    discord_role_dispatch:       Optional[int] = None
    discord_role_driver:         Optional[int] = None
    discord_role_captain:        Optional[int] = None
    discord_role_walker:         Optional[int] = None


class DiscordConfigResponse(BaseModel):
    discord_guild_id:            Optional[str] = None
    discord_drivers_channel_id:  Optional[str] = None
    discord_trainers_channel_id: Optional[str] = None
    discord_general_channel_id:  Optional[str] = None
    discord_invite_channel_id:   Optional[str] = None
    discord_role_admin:          Optional[str] = None
    discord_role_manager:        Optional[str] = None
    discord_role_asheflow:       Optional[str] = None
    discord_role_bot:            Optional[str] = None
    discord_role_dispatch:       Optional[str] = None
    discord_role_driver:         Optional[str] = None
    discord_role_captain:        Optional[str] = None
    discord_role_walker:         Optional[str] = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_config(cls, config) -> "DiscordConfigResponse":
        fields = [
            "discord_guild_id", "discord_drivers_channel_id", "discord_trainers_channel_id",
            "discord_general_channel_id", "discord_invite_channel_id",
            "discord_role_admin", "discord_role_manager", "discord_role_asheflow",
            "discord_role_bot", "discord_role_dispatch", "discord_role_driver",
            "discord_role_captain", "discord_role_walker",
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

    for field, value in data.items():
        setattr(company, field, value)

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
_SUPER_ADMIN_ONLY_FIELDS = frozenset({"invite_expiry_days"})

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

    # Tier 1 manifest verify (DBSCAN tote classification)
    tier1_dbscan_eps:                Optional[float] = Field(None, ge=0.001, le=1.0)
    tier1_dbscan_min_samples:        Optional[int]   = Field(None, ge=1, le=200)
    tier1_small_tote_cutoff:         Optional[int]   = Field(None, ge=1, le=100)
    tier1_small_stray_max:           Optional[int]   = Field(None, ge=0, le=20)
    tier1_small_uncertain_max:       Optional[int]   = Field(None, ge=0, le=20)
    tier1_stray_pct:                 Optional[float] = Field(None, ge=0.0, le=1.0)
    tier1_uncertain_pct:             Optional[float] = Field(None, ge=0.0, le=1.0)

    # Effort scoring
    effort_time_factor:              Optional[float] = Field(None, ge=0.0, le=1.0)
    effort_physical_factor:          Optional[float] = Field(None, ge=0.0, le=1.0)

    # Manifest ingestion
    ingestion_mode:                  Optional[str]   = None


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

    _apply_config_update(config, payload, allow_super_admin_fields=True)
    db.commit()
    db.refresh(config)
    return CompanyConfigResponse.from_orm_obj(config)


# ---------------------------------------------------------------------------
# Company admin: read + update their own config
# ---------------------------------------------------------------------------

company_admin_router = APIRouter(prefix="/companies", tags=["company-config"])

allow_admin = RoleChecker(["admin"])
allow_management = RoleChecker(["management", "admin"])


@company_admin_router.get("/my-info")
def get_my_company_info(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Return name and timezone for the caller's company. Management and admin."""
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

    _apply_config_update(config, payload, allow_super_admin_fields=False)
    db.commit()
    db.refresh(config)
    return CompanyConfigResponse.from_orm_obj(config)


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

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(config, field, value)

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

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(config, field, value)

    db.commit()
    db.refresh(config)
    return DiscordConfigResponse.from_config(config)
