"""Scorecard appeal schemas (ADR-243)."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── line items ───────────────────────────────────────────────────────────────

class AppealItemIn(BaseModel):
    metric_key: str = Field(..., max_length=50)
    metric_label: str = Field(..., max_length=100)
    # Snapshotted at draft time — re-uploading a corrected scorecard rewrites
    # scorecard_metrics, which would otherwise silently rewrite our evidence.
    amazon_value: Optional[str] = Field(None, max_length=50)
    our_value: Optional[str] = Field(None, max_length=50)
    delta: Optional[float] = None
    evidence: Optional[Dict[str, Any]] = None
    claim: Optional[str] = None
    sort_order: int = 0


class AppealItemOut(AppealItemIn):
    id: UUID
    outcome: str
    outcome_notes: Optional[str] = None
    corrected_value: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class AppealItemResolve(BaseModel):
    """Record what Amazon decided about ONE contested metric."""
    outcome: Literal["accepted", "rejected"]
    corrected_value: Optional[str] = Field(None, max_length=50)
    outcome_notes: Optional[str] = None


# ── appeal ───────────────────────────────────────────────────────────────────

class AppealCreate(BaseModel):
    scorecard_id: UUID
    title: Optional[str] = Field(None, max_length=200)
    rationale: Optional[str] = None
    items: List[AppealItemIn] = []


class AppealUpdate(BaseModel):
    """Draft-only edits. Enforced in the router: once filed with Amazon the
    contents are a record of what was actually submitted."""
    title: Optional[str] = Field(None, max_length=200)
    rationale: Optional[str] = None
    items: Optional[List[AppealItemIn]] = None


class AppealSubmit(BaseModel):
    """Mark as filed in Amazon's portal. AsheFlow does not file it."""
    amazon_reference: Optional[str] = Field(None, max_length=100)


class AppealResolve(BaseModel):
    outcome: Literal["won", "lost", "withdrawn"]
    outcome_notes: Optional[str] = None


class AppealOut(BaseModel):
    id: UUID
    company_id: UUID
    scorecard_id: UUID
    week: str
    scope: str
    employee_id: Optional[UUID] = None
    employee_name: Optional[str] = None
    status: str
    title: Optional[str] = None
    rationale: Optional[str] = None
    submitted_at: Optional[datetime] = None
    submitted_by_name: Optional[str] = None
    amazon_reference: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by_name: Optional[str] = None
    outcome_notes: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: datetime
    items: List[AppealItemOut] = []
    model_config = ConfigDict(from_attributes=True)


class AppealListItem(BaseModel):
    """Row shape for the appeals index — no items, so the list stays cheap."""
    id: UUID
    scorecard_id: UUID
    week: str
    scope: str
    employee_name: Optional[str] = None
    status: str
    title: Optional[str] = None
    item_count: int = 0
    items_accepted: int = 0
    submitted_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime


class AppealStats(BaseModel):
    """Win rate and where it comes from.

    win_rate_pct is None rather than 0.0 when nothing has been resolved — "no
    resolved appeals" and "we lose every appeal" are different facts.
    """
    total: int = 0
    draft: int = 0
    submitted: int = 0
    won: int = 0
    lost: int = 0
    withdrawn: int = 0
    win_rate_pct: Optional[float] = None
    most_appealed_metrics: List[Dict[str, Any]] = []
    most_won_metrics: List[Dict[str, Any]] = []
