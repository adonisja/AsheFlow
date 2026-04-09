from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.time_off_request import TimeOffRequest
from app.models.employee_off_day import EmployeeOffDay
from app.schemas.time_off_request import TimeOffRequestCreate, TimeOffRequestResponse

router = APIRouter(prefix="/time-off-requests", tags=["time-off-requests"])

@router.get("/{employee_id}", response_model=list[TimeOffRequestResponse])
def get_time_off_requests(employee_id: UUID, db: Session = Depends(get_db)):
    requests = db.query(TimeOffRequest).filter(TimeOffRequest.employee_id == employee_id).all()
    return requests

@router.post("/", response_model=TimeOffRequestResponse, status_code=status.HTTP_201_CREATED)
def create_time_off_request(request: TimeOffRequestCreate, db: Session = Depends(get_db)):
    day_of_week = request.date.strftime("%A")
    
    recurring_off_day = db.query(EmployeeOffDay).filter(
        EmployeeOffDay.employee_id == request.employee_id,
        EmployeeOffDay.day_of_week == day_of_week,
        EmployeeOffDay.status == "approved"
    ).first()

    if recurring_off_day:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Cannot request time off on {day_of_week}s; it is already an approved recurring off-day."
        )

    existing_request = db.query(TimeOffRequest).filter(
        TimeOffRequest.employee_id == request.employee_id,
        TimeOffRequest.date == request.date
    ).first()

    if existing_request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="A time-off request already exists for this date."
        )

    db_request = TimeOffRequest(
        employee_id=request.employee_id,
        date=request.date,
        status="pending"
    )
    db.add(db_request)
    db.commit()
    db.refresh(db_request)
    return db_request

@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_time_off_request(request_id: UUID, db: Session = Depends(get_db)):
    db_request = db.query(TimeOffRequest).filter(TimeOffRequest.id == request_id).first()
    if not db_request:
        raise HTTPException(status_code=404, detail="Time-off request not found")
    
    db.delete(db_request)
    db.commit()

@router.patch("/{request_id}/approve", response_model=TimeOffRequestResponse)
def approve_time_off_request(request_id: UUID, db: Session = Depends(get_db)):
    db_request = db.query(TimeOffRequest).filter(TimeOffRequest.id == request_id).first()
    if not db_request:
        raise HTTPException(status_code=404, detail="Time-off request not found")
    
    db_request.status = "approved"
    db.commit()
    db.refresh(db_request)
    return db_request

@router.patch("/{request_id}/reject", response_model=TimeOffRequestResponse)
def reject_time_off_request(request_id: UUID, db: Session = Depends(get_db)):
    db_request = db.query(TimeOffRequest).filter(TimeOffRequest.id == request_id).first()
    if not db_request:
        raise HTTPException(status_code=404, detail="Time-off request not found")
    
    db_request.status = "rejected"
    db.commit()
    db.refresh(db_request)
    return db_request
