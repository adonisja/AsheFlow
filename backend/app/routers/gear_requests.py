"""gear_requests.py — work gear request system.

Employees submit multi-item cart orders; managers approve/deny/fulfill at the
line-item level.

Season is derived from company local date at submission time:
  Summer items (shirt_short, shorts, cap): May 1 – Sep 30
  Winter items (shirt_long, pants, jacket, vest, gloves): Oct 1 – Apr 30

Limits enforced per item type across all orders:
  Weekly:   1 of each item type per rolling 7-day window
  Seasonal: 3 of each item type per current season
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, get_caller_employee
from app.database import get_db
from app.models.company import Company
from app.models.employee import Employee
from app.models.gear_request import GearOrder, GearOrderItem
from app.services.local_date import company_today

router = APIRouter(prefix="/gear-requests", tags=["gear-requests"])

allow_all       = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
allow_management = RoleChecker(["management", "admin"])


# ---------------------------------------------------------------------------
# Gear catalogue — source of truth for items, sizes, and seasons
# ---------------------------------------------------------------------------

SUMMER_ITEMS = frozenset({"shirt_short", "shorts", "cap"})
WINTER_ITEMS = frozenset({"shirt_long", "pants", "jacket", "vest", "gloves"})
ALL_ITEMS    = SUMMER_ITEMS | WINTER_ITEMS

STANDARD_SIZES = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]
GLOVE_SIZES    = ["S", "M", "L"]
NO_SIZE_ITEMS  = frozenset({"cap"})  # one-size-fits-all

VALID_SIZES: dict[str, list[str]] = {
    "shirt_short": STANDARD_SIZES,
    "shirt_long":  STANDARD_SIZES,
    "pants":       STANDARD_SIZES,
    "shorts":      STANDARD_SIZES,
    "jacket":      STANDARD_SIZES,
    "vest":        STANDARD_SIZES,
    "gloves":      GLOVE_SIZES,
    "cap":         [],  # no size
}

WEEKLY_LIMIT   = 1
SEASONAL_LIMIT = 3


# ---------------------------------------------------------------------------
# Season helpers
# ---------------------------------------------------------------------------

def _company_timezone(db: Session, company_id: UUID) -> ZoneInfo:
    company = db.query(Company).filter(Company.id == company_id).first()
    tz_str = company.timezone if company and company.timezone else "UTC"
    try:
        return ZoneInfo(tz_str)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _current_season(db: Session, company_id: UUID) -> str:
    """Return 'summer' or 'winter' based on company local date. May–Sep = summer."""
    tz = _company_timezone(db, company_id)
    month = datetime.now(tz).month
    return "summer" if 5 <= month <= 9 else "winter"


def _season_for_item(item: str) -> str:
    if item in SUMMER_ITEMS:
        return "summer"
    return "winter"


def _season_year_key(db: Session, company_id: UUID) -> str:
    """Return e.g. '2026-summer' or '2026-winter' for limit bucketing."""
    tz = _company_timezone(db, company_id)
    now = datetime.now(tz)
    season = "summer" if 5 <= now.month <= 9 else "winter"
    # Winter spans year boundary — attribute Jan–Apr to prior year's winter
    year = now.year if now.month >= 5 else now.year - 1
    return f"{year}-{season}"


def _season_bounds(season_key: str) -> tuple[datetime, datetime]:
    """Return UTC start/end datetimes for a season key like '2026-summer'."""
    year, season = season_key.split("-", 1)
    y = int(year)
    if season == "summer":
        start = datetime(y,     5,  1, tzinfo=timezone.utc)
        end   = datetime(y,     9, 30, 23, 59, 59, tzinfo=timezone.utc)
    else:
        start = datetime(y,     10, 1, tzinfo=timezone.utc)
        end   = datetime(y + 1, 4, 30, 23, 59, 59, tzinfo=timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# Limit helpers
# ---------------------------------------------------------------------------

def _weekly_count(db: Session, employee_id: UUID, company_id: UUID, item: str) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    return (
        db.query(GearOrderItem)
        .filter(
            GearOrderItem.company_id  == company_id,
            GearOrderItem.employee_id == employee_id,
            GearOrderItem.item        == item,
            GearOrderItem.status      != "denied",
            GearOrderItem.created_at  >= cutoff,
        )
        .count()
    )


def _seasonal_count(db: Session, employee_id: UUID, company_id: UUID, item: str) -> int:
    season_key = _season_year_key(db, company_id)
    start, end = _season_bounds(season_key)
    return (
        db.query(GearOrderItem)
        .filter(
            GearOrderItem.company_id  == company_id,
            GearOrderItem.employee_id == employee_id,
            GearOrderItem.item        == item,
            GearOrderItem.status      != "denied",
            GearOrderItem.created_at  >= start,
            GearOrderItem.created_at  <= end,
        )
        .count()
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class GearItemIn(BaseModel):
    item: str
    size: Optional[str] = None

    @field_validator("item")
    @classmethod
    def item_valid(cls, v: str) -> str:
        if v not in ALL_ITEMS:
            raise ValueError(f"Unknown item '{v}'. Valid items: {sorted(ALL_ITEMS)}")
        return v

    @field_validator("size")
    @classmethod
    def size_valid(cls, v: Optional[str], info) -> Optional[str]:
        item = info.data.get("item")
        if not item:
            return v
        if item in NO_SIZE_ITEMS:
            return None
        valid = VALID_SIZES.get(item, [])
        if v is None or v not in valid:
            raise ValueError(f"Size '{v}' invalid for '{item}'. Valid: {valid}")
        return v


class GearOrderCreate(BaseModel):
    items: list[GearItemIn]

    @field_validator("items")
    @classmethod
    def no_duplicates(cls, v: list[GearItemIn]) -> list[GearItemIn]:
        seen = set()
        for item in v:
            if item.item in seen:
                raise ValueError(f"Duplicate item '{item.item}' in the same order.")
            seen.add(item.item)
        if len(v) == 0:
            raise ValueError("Order must contain at least one item.")
        return v


class GearItemResponse(BaseModel):
    id: UUID
    item: str
    size: Optional[str]
    season: str
    status: str
    approved_by: Optional[UUID]
    approved_at: Optional[datetime]
    fulfilled_by: Optional[UUID]
    fulfilled_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class GearOrderResponse(BaseModel):
    id: UUID
    employee_id: UUID
    employee_name: str
    employee_role: str
    submitted_at: datetime
    items: list[GearItemResponse]

    model_config = {"from_attributes": True}


class ItemActionPayload(BaseModel):
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Catalogue endpoint (drives the frontend grid)
# ---------------------------------------------------------------------------

@router.get("/catalogue")
def get_catalogue(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_all),
    db: Session = Depends(get_db),
):
    """Return the full item catalogue with season tags and which items are
    currently available based on company local date."""
    current_season = _current_season(db, caller.company_id)

    catalogue = []
    for item in sorted(ALL_ITEMS):
        item_season = _season_for_item(item)
        catalogue.append({
            "item":      item,
            "season":    item_season,
            "available": item_season == current_season,
            "sizes":     VALID_SIZES[item],
            "no_size":   item in NO_SIZE_ITEMS,
        })
    return {"current_season": current_season, "items": catalogue}


# ---------------------------------------------------------------------------
# Submit a cart order
# ---------------------------------------------------------------------------

@router.post("/", response_model=GearOrderResponse, status_code=status.HTTP_201_CREATED)
def submit_gear_order(
    payload: GearOrderCreate,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_all),
    db: Session = Depends(get_db),
):
    """Submit a multi-item gear order. Validates season, weekly, and seasonal limits."""
    current_season = _current_season(db, caller.company_id)
    errors = []

    for gear_item in payload.items:
        item_season = _season_for_item(gear_item.item)

        # Season hard-block
        if item_season != current_season:
            errors.append(
                f"'{gear_item.item}' is a {item_season} item and is not available in {current_season}."
            )
            continue

        # Weekly limit
        weekly = _weekly_count(db, caller.id, caller.company_id, gear_item.item)
        if weekly >= WEEKLY_LIMIT:
            errors.append(
                f"'{gear_item.item}': weekly limit of {WEEKLY_LIMIT} already reached."
            )
            continue

        # Seasonal limit
        seasonal = _seasonal_count(db, caller.id, caller.company_id, gear_item.item)
        if seasonal >= SEASONAL_LIMIT:
            errors.append(
                f"'{gear_item.item}': seasonal limit of {SEASONAL_LIMIT} already reached."
            )

    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=errors,
        )

    order = GearOrder(
        company_id=caller.company_id,
        employee_id=caller.id,
    )
    db.add(order)
    db.flush()

    for gear_item in payload.items:
        db.add(GearOrderItem(
            order_id    = order.id,
            company_id  = caller.company_id,
            employee_id = caller.id,
            item        = gear_item.item,
            size        = gear_item.size if gear_item.item not in NO_SIZE_ITEMS else None,
            season      = _season_for_item(gear_item.item),
            status      = "pending",
        ))

    db.commit()
    db.refresh(order)
    return _build_order_response(order, caller, db)


# ---------------------------------------------------------------------------
# Employee: own order history
# ---------------------------------------------------------------------------

@router.get("/my-orders", response_model=list[GearOrderResponse])
def get_my_orders(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_all),
    db: Session = Depends(get_db),
):
    """Return the calling employee's gear order history, newest first."""
    orders = (
        db.query(GearOrder)
        .filter(
            GearOrder.company_id  == caller.company_id,
            GearOrder.employee_id == caller.id,
        )
        .order_by(GearOrder.submitted_at.desc())
        .all()
    )
    return [_build_order_response(o, caller, db) for o in orders]


# ---------------------------------------------------------------------------
# Manager: list all orders for the company
# ---------------------------------------------------------------------------

@router.get("/pending", response_model=list[GearOrderResponse])
def get_pending_orders(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Return all orders that have at least one pending item, newest first."""
    pending_order_ids = (
        db.query(GearOrderItem.order_id)
        .filter(
            GearOrderItem.company_id == caller.company_id,
            GearOrderItem.status == "pending",
        )
        .distinct()
        .subquery()
    )
    orders = (
        db.query(GearOrder)
        .filter(GearOrder.id.in_(pending_order_ids))
        .order_by(GearOrder.submitted_at.desc())
        .all()
    )
    return [_build_order_response(o, None, db) for o in orders]


@router.get("/all", response_model=list[GearOrderResponse])
def get_all_orders(
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    """Return all gear orders for the company, newest first."""
    orders = (
        db.query(GearOrder)
        .filter(GearOrder.company_id == caller.company_id)
        .order_by(GearOrder.submitted_at.desc())
        .all()
    )
    return [_build_order_response(o, None, db) for o in orders]


# ---------------------------------------------------------------------------
# Manager: item-level actions
# ---------------------------------------------------------------------------

@router.patch("/items/{item_id}/approve", response_model=GearItemResponse)
def approve_item(
    item_id: UUID,
    payload: ItemActionPayload,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    item = _get_item(item_id, caller.company_id, db)
    if item.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending items can be approved.")
    item.status      = "approved"
    item.approved_by = caller.id
    item.approved_at = datetime.now(timezone.utc)
    item.notes       = payload.notes
    db.commit()
    db.refresh(item)
    return item


@router.patch("/items/{item_id}/deny", response_model=GearItemResponse)
def deny_item(
    item_id: UUID,
    payload: ItemActionPayload,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    item = _get_item(item_id, caller.company_id, db)
    if item.status not in ("pending", "approved"):
        raise HTTPException(status_code=400, detail="Only pending or approved items can be denied.")
    item.status      = "denied"
    item.approved_by = caller.id
    item.approved_at = datetime.now(timezone.utc)
    item.notes       = payload.notes
    db.commit()
    db.refresh(item)
    return item


@router.patch("/items/{item_id}/fulfill", response_model=GearItemResponse)
def fulfill_item(
    item_id: UUID,
    payload: ItemActionPayload,
    caller: Employee = Depends(get_caller_employee),
    _: dict = Depends(allow_management),
    db: Session = Depends(get_db),
):
    item = _get_item(item_id, caller.company_id, db)
    if item.status != "approved":
        raise HTTPException(status_code=400, detail="Only approved items can be fulfilled.")
    item.status       = "fulfilled"
    item.fulfilled_by = caller.id
    item.fulfilled_at = datetime.now(timezone.utc)
    item.notes        = payload.notes or item.notes
    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_item(item_id: UUID, company_id: UUID, db: Session) -> GearOrderItem:
    item = db.query(GearOrderItem).filter(
        GearOrderItem.id         == item_id,
        GearOrderItem.company_id == company_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Gear item not found.")
    return item


def _build_order_response(order: GearOrder, caller: Optional[Employee], db: Session) -> GearOrderResponse:
    employee = db.query(Employee).filter(Employee.id == order.employee_id).first()
    items = (
        db.query(GearOrderItem)
        .filter(GearOrderItem.order_id == order.id)
        .order_by(GearOrderItem.created_at)
        .all()
    )
    return GearOrderResponse(
        id            = order.id,
        employee_id   = order.employee_id,
        employee_name = employee.name if employee else "Unknown",
        employee_role = employee.role if employee else "unknown",
        submitted_at  = order.submitted_at,
        items         = items,
    )
