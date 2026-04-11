from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.deps import RoleChecker, get_current_user
from app.models.truck import Truck
from app.schemas.truck import TruckCreate, TruckUpdate, TruckResponse

router = APIRouter(prefix="/trucks", tags=["trucks"])

# All authenticated users may read trucks (dispatch board, schedule view need the full list).
# Write operations restricted to management/admin.
allow_any_auth   = RoleChecker(["driver", "walker", "trainer", "trainee", "dispatch", "management", "admin"])
allow_write      = RoleChecker(["management", "admin"])


@router.post("/", response_model=TruckResponse, status_code=status.HTTP_201_CREATED)
def create_truck(truck: TruckCreate, db: Session = Depends(get_db), _: dict = Depends(allow_write)):
    """Create and persist a new truck record.

    Args:
        truck: Validated truck creation payload.
        db: Database session.

    Returns:
        The newly created Truck record.
    """
    db_truck = Truck(**truck.model_dump())
    db.add(db_truck)
    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.get("/", response_model=list[TruckResponse])
def get_trucks(db: Session = Depends(get_db), _: dict = Depends(allow_any_auth)):
    """Return all active trucks.

    Args:
        db: Database session.

    Returns:
        List of active Truck records.
    """
    return db.query(Truck).filter(Truck.is_active == True).all()


@router.get("/{truck_id}", response_model=TruckResponse)
def get_truck(truck_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_any_auth)):
    """Fetch a single truck by ID.

    Args:
        truck_id: UUID of the truck to retrieve.
        db: Database session.

    Returns:
        The matching Truck record.

    Raises:
        HTTPException(404): If no truck with the given ID exists.
    """
    truck = db.query(Truck).filter(Truck.id == truck_id).first()
    if not truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")
    return truck


@router.put("/{truck_id}", response_model=TruckResponse)
def update_truck(truck_id: UUID, truck: TruckUpdate, db: Session = Depends(get_db), _: dict = Depends(allow_write)):
    """Update an existing truck's fields.

    Args:
        truck_id: UUID of the truck to update.
        truck: Partial update payload; only provided fields are applied.
        db: Database session.

    Returns:
        The updated Truck record.

    Raises:
        HTTPException(404): If no truck with the given ID exists.
    """
    db_truck = db.query(Truck).filter(Truck.id == truck_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")

    for key, value in truck.model_dump(exclude_unset=True).items():
        setattr(db_truck, key, value)

    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.put("/{truck_id}/deactivate", response_model=TruckResponse)
def deactivate_truck(truck_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_write)):
    """Set a truck's active status to False.

    Args:
        truck_id: UUID of the truck to deactivate.
        db: Database session.

    Returns:
        The updated Truck record with ``is_active`` set to False.

    Raises:
        HTTPException(404): If no truck with the given ID exists.
    """
    db_truck = db.query(Truck).filter(Truck.id == truck_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")

    db_truck.is_active = False
    db.commit()
    db.refresh(db_truck)
    return db_truck


@router.delete("/{truck_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_truck(truck_id: UUID, db: Session = Depends(get_db), _: dict = Depends(allow_write)):
    """Soft-delete a truck by setting ``is_active`` to False.

    Args:
        truck_id: UUID of the truck to delete.
        db: Database session.

    Raises:
        HTTPException(404): If no truck with the given ID exists.
    """
    db_truck = db.query(Truck).filter(Truck.id == truck_id).first()
    if not db_truck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")

    db_truck.is_active = False
    db.commit()
