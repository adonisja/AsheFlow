import boto3
import logging
from uuid import UUID
from botocore.exceptions import ClientError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import RoleChecker, Pagination, get_caller_employee
from app.core.config import settings
from app.database import get_db
from app.models.employee import Employee
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeResponse, EmployeePublicResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/employees", tags=["employees"])

# Cognito group name per role — must match your User Pool group names exactly
ROLE_TO_COGNITO_GROUP: dict[str, str] = {
    "driver":     "driver",
    "walker":     "walker",
    "trainer":    "trainer",
    "trainee":    "trainee",
    "dispatch":   "dispatch",
    "management": "management",
    "admin":      "admin",
}


def _cognito_client():
    return boto3.client("cognito-idp", region_name=settings.aws_region)


@router.post("/", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
def create_employee(
    employee: EmployeeCreate,
    current_user: dict = Depends(RoleChecker(["management", "admin"])),
    db: Session = Depends(get_db),
):
    """Create an employee record and send a Cognito invite to their email.

    Calls AdminCreateUser so the employee receives a temporary-password email.
    Also adds them to the correct Cognito group matching their role.
    The employee's cognito_sub is stamped automatically on their first login.
    """
    # Check for duplicate email or discord_id before touching Cognito
    if db.query(Employee).filter(Employee.email == employee.email).first():
        raise HTTPException(status_code=400, detail="An employee with this email already exists.")
    if db.query(Employee).filter(Employee.discord_id == employee.discord_id).first():
        raise HTTPException(status_code=400, detail="An employee with this Discord ID already exists.")

    # Create the Cognito user — this sends the invite email automatically
    cognito = _cognito_client()
    cognito_sub = None
    try:
        response = cognito.admin_create_user(
            UserPoolId=settings.aws_cognito_user_pool_id,
            Username=employee.email,
            UserAttributes=[
                {"Name": "email",          "Value": employee.email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name",           "Value": employee.name},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )
        cognito_sub = next(
            (a["Value"] for a in response["User"]["Attributes"] if a["Name"] == "sub"),
            None,
        )

        # Add user to their role group
        group = ROLE_TO_COGNITO_GROUP.get(employee.role)
        if group:
            cognito.admin_add_user_to_group(
                UserPoolId=settings.aws_cognito_user_pool_id,
                Username=employee.email,
                GroupName=group,
            )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "UsernameExistsException":
            raise HTTPException(status_code=400, detail="A Cognito account with this email already exists.")
        logger.error("Cognito AdminCreateUser failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to create Cognito account: {e.response['Error']['Message']}")

    # Persist the employee record with the cognito_sub already stamped
    db_employee = Employee(**employee.model_dump(), cognito_sub=cognito_sub)
    db.add(db_employee)
    db.commit()
    db.refresh(db_employee)
    return db_employee


PRIVILEGED_ROLES = {"management", "admin", "dispatch"}
FIELD_ROLES      = {"driver", "walker", "trainer", "trainee"}


@router.get("/", response_model=list[EmployeeResponse])
def get_all_employees(
    current_user: dict = Depends(RoleChecker(list(PRIVILEGED_ROLES | FIELD_ROLES))),
    pg: Pagination = Depends(),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    """Return employees. Active-only by default; pass ?include_inactive=true for admin/management.

    Management/admin/dispatch receive the full record including phone, email,
    and cognito_sub. Field staff receive a redacted response with those fields
    removed.
    """
    caller_groups = set(current_user.get("cognito_groups", []))

    q = db.query(Employee)
    if include_inactive:
        if not (caller_groups & {"management", "admin"}):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    else:
        q = q.filter(Employee.is_active == True)

    employees = pg.apply(q).all()

    if caller_groups & PRIVILEGED_ROLES:
        return [EmployeeResponse.model_validate(e) for e in employees]
    return [EmployeePublicResponse.model_validate(e) for e in employees]


@router.get("/me", response_model=EmployeeResponse)
def get_my_employee(
    caller: Employee = Depends(get_caller_employee),
):
    """Return the Employee record for the currently authenticated user."""
    return EmployeeResponse.model_validate(caller)


@router.get("/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: UUID,
    current_user: dict = Depends(RoleChecker(list(PRIVILEGED_ROLES | FIELD_ROLES))),
    db: Session = Depends(get_db),
):
    """Fetch a single employee by ID.

    Management/admin/dispatch receive the full record. Field staff receive the
    redacted version without phone, email, and cognito_sub.
    """
    employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    caller_groups = set(current_user.get("cognito_groups", []))
    if caller_groups & PRIVILEGED_ROLES:
        return EmployeeResponse.model_validate(employee)
    return EmployeePublicResponse.model_validate(employee)


@router.put("/{employee_id}", response_model=EmployeeResponse)
def update_employee(employee_id: UUID, employee: EmployeeUpdate, current_user: dict = Depends(RoleChecker(["management", "admin"])), db: Session = Depends(get_db)):
    """Update an existing employee's fields.

    When the role changes, the employee is removed from their old Cognito group
    and added to the new one so permissions take effect on their next token refresh.
    """
    db_employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    updates = employee.model_dump(exclude_unset=True)
    new_role = updates.get("role")
    old_role = db_employee.role

    for key, value in updates.items():
        setattr(db_employee, key, value)

    db.commit()
    db.refresh(db_employee)

    # Sync Cognito group when role changes and the employee has a Cognito account
    if new_role and new_role != old_role and db_employee.email:
        cognito_username = db_employee.email
        old_group = ROLE_TO_COGNITO_GROUP.get(old_role)
        new_group = ROLE_TO_COGNITO_GROUP.get(new_role)
        cognito = _cognito_client()
        try:
            if old_group:
                cognito.admin_remove_user_from_group(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=cognito_username,
                    GroupName=old_group,
                )
            if new_group:
                cognito.admin_add_user_to_group(
                    UserPoolId=settings.aws_cognito_user_pool_id,
                    Username=cognito_username,
                    GroupName=new_group,
                )
        except ClientError as e:
            # DB is already committed — log the Cognito failure but don't roll back.
            # Management can retry; the DB record is the source of truth.
            logger.error(
                "Cognito group sync failed for employee %s (old=%s new=%s): %s",
                db_employee.id, old_group, new_group, e,
            )

    return db_employee


@router.put("/{employee_id}/deactivate", response_model=EmployeeResponse)
def deactivate_employee(employee_id: UUID, current_user: dict = Depends(RoleChecker(["management", "admin"])), db: Session = Depends(get_db)):
    """Set an employee's active status to False.

    Args:
        employee_id: UUID of the employee to deactivate.
        db: Database session.

    Returns:
        The updated Employee record with ``is_active`` set to False.

    Raises:
        HTTPException(404): If no employee with the given ID exists.
    """
    db_employee = (db.query(Employee)
                   .filter(Employee.id == employee_id)
                   .first()
                )
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")

    db_employee.is_active = False
    db.commit()
    db.refresh(db_employee)
    return db_employee


@router.put("/{employee_id}/reactivate", response_model=EmployeeResponse)
def reactivate_employee(employee_id: UUID, current_user: dict = Depends(RoleChecker(["management", "admin"])), db: Session = Depends(get_db)):
    """Set an employee's active status back to True."""
    db_employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if not db_employee:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    db_employee.is_active = True
    db.commit()
    db.refresh(db_employee)
    return db_employee
