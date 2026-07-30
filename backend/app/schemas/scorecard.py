from datetime import datetime, date
from typing import Optional, List, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class ScorecardMetricIn(BaseModel):
    key: str = Field(..., max_length=50)
    label: str = Field(..., max_length=100)
    value: str = Field(..., max_length=50)
    unit: Optional[str] = Field(None, max_length=20)
    tier: Optional[str] = Field(None, max_length=30)
    flag: Optional[Literal["excellent", "needs_focus"]] = None
    sort_order: int = 0


class ScorecardMetricOut(ScorecardMetricIn):
    id: UUID
    model_config = ConfigDict(from_attributes=True)


class ScorecardCreate(BaseModel):
    """Manager creates/updates a scorecard for a week (structured entry — this is
    what the upload+confirm step writes). scope='company' → employee_id omitted."""
    week: str = Field(..., max_length=10, description='ISO week, e.g. "2026-W28"')
    scope: Literal["individual", "company"] = "individual"
    employee_id: Optional[UUID] = None
    overall_standing: Optional[str] = Field(None, max_length=30)
    source_file_url: Optional[str] = None
    metrics: List[ScorecardMetricIn] = []


class ScorecardDraftOut(BaseModel):
    """Parsed-but-unsaved scorecard (ADR-204 Phase C). The manager reviews/edits
    this in the entry form, then saves via POST /scorecards."""
    week: Optional[str] = None
    overall_standing: Optional[str] = None
    metrics: List[ScorecardMetricIn] = []


class ScorecardOut(BaseModel):
    id: UUID
    week: str
    scope: str
    employee_id: Optional[UUID] = None
    employee_name: Optional[str] = None
    overall_standing: Optional[str] = None
    source_file_url: Optional[str] = None
    created_at: datetime
    metrics: List[ScorecardMetricOut] = []
    model_config = ConfigDict(from_attributes=True)


# ── Cross-check (ADR-204 Phase D): Amazon vs our data ───────────────────────────

class CrossCheckItem(BaseModel):
    metric: str                           # 'packages_delivered' | 'delivery_completion_dpmo'
    amazon_value: Optional[float] = None  # parsed from the scorecard
    our_value: Optional[float] = None     # computed from DeliveryStop/RTS for that employee+week
    delta: Optional[float] = None         # amazon - ours
    contestable: bool = False             # our data materially disagrees → worth appealing
    note: str = ""


class RtsReasonEvidence(BaseModel):
    rts_type: str
    count: int


class CrossCheckResponse(BaseModel):
    scorecard_id: UUID
    week: str
    week_start: date
    week_end: date
    our_delivered: int
    our_rts: int
    our_missing: int
    items: List[CrossCheckItem] = []
    # RTS reasons we recorded that week — the evidence for a completion-defect appeal.
    rts_evidence: List[RtsReasonEvidence] = []


# ── Company trend (ADR-241 follow-up) ────────────────────────────────────────
# Amazon's weekly scorecard is the number the business is judged on, and it is
# the one dataset with an inherent baseline (Amazon's own tiers). Everything
# below is a multi-week view over company-scope scorecards.

class MetricTrendPoint(BaseModel):
    week: str
    value: Optional[float] = None      # parsed numeric, None if non-numeric
    raw: str                           # original string, e.g. "100.0%" | "PLATINUM"
    tier: Optional[str] = None
    flag: Optional[str] = None


class MetricTrend(BaseModel):
    key: str
    label: str
    unit: Optional[str] = None
    points: List[MetricTrendPoint]
    latest: Optional[float] = None
    previous: Optional[float] = None
    delta: Optional[float] = None       # latest - previous
    direction: Optional[str] = None     # up | down | flat | None when unknown
    weeks_flagged: int = 0              # how many weeks carried needs_focus


class StandingPoint(BaseModel):
    week: str
    standing: Optional[str] = None


class ScorecardTrendResponse(BaseModel):
    weeks: List[str]                    # oldest -> newest
    standings: List[StandingPoint]
    current_standing: Optional[str] = None
    previous_standing: Optional[str] = None
    metrics: List[MetricTrend]
    # Metrics Amazon flagged needs_focus in the most recent week — the actual
    # to-do list, rather than making the reader scan every row.
    focus_now: List[str] = []
    missing_weeks: List[str] = []       # gaps in the range, so absence is visible


# ── Tier 1: company overview, visible to every role ──────────────────────────

class CompanyStandingCard(BaseModel):
    """The company's standing — a shared fact about the operation, no PII.

    Surfaces as a header card for every role, so a driver knows where the DSP
    stands without seeing anyone's individual numbers.
    """
    week: Optional[str] = None
    standing: Optional[str] = None
    previous_standing: Optional[str] = None
    direction: Optional[str] = None       # improved | declined | unchanged | None
    consecutive_weeks: int = 0            # weeks held at the CURRENT standing
    has_data: bool = False


# ── Tier 3: individual trends ────────────────────────────────────────────────

class IndividualMetricPoint(BaseModel):
    week: str
    value: Optional[float] = None
    raw: str
    flag: Optional[str] = None


class IndividualMetricTrend(BaseModel):
    key: str
    label: str
    unit: Optional[str] = None
    points: List[IndividualMetricPoint]
    latest: Optional[float] = None
    previous: Optional[float] = None
    delta: Optional[float] = None
    direction: Optional[str] = None       # already inverted for lower-is-better


class IndividualTrendResponse(BaseModel):
    """One person's scorecard trend. Self-serve or management-viewed."""
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    weeks: List[str]
    standings: List[StandingPoint]
    current_standing: Optional[str] = None
    metrics: List[IndividualMetricTrend]
    focus_now: List[str] = []


class IndividualRosterRow(BaseModel):
    """A roster row for the management leaderboard.

    Named deliberately — management and admin only, consistent with
    /field-ops/walker-leaderboard which already shows named ratings to the same
    audience. Never exposed to dispatch or to field staff.
    """
    employee_id: str
    employee_name: str
    employee_role: Optional[str] = None
    latest_week: Optional[str] = None
    standing: Optional[str] = None
    weeks_recorded: int = 0
    flagged_metric_count: int = 0         # metrics needing focus in latest week
    trend_direction: Optional[str] = None # standing movement vs prior week


class IndividualRosterResponse(BaseModel):
    weeks_considered: List[str]
    rows: List[IndividualRosterRow]
    employees_without_scorecards: int = 0
