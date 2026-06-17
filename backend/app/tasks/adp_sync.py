"""ADP RUN employee sync task for AsheFlow.

Registered in celery_app.py beat_schedule — runs nightly at 02:00 AM Eastern
to keep AsheFlow's employee roster in sync with ADP RUN.

Can also be triggered on-demand via POST /api/v1/adp/sync-employees.
"""
import logging
import asyncio
import boto3

from datetime import date, datetime

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.adp_integration import ADPIntegration
from app.models.employee import Employee
from app.services.adp import fetch_adp_employees
from app.core.config import settings
from app.models.truck_assignment import TruckAssignment
from app.models.assignment_member import AssignmentMember
from app.services.audit import write_audit
from app.models.notification import Notification

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.adp_sync.sync_adp_employees")
def sync_adp_employees() -> dict:
    db = SessionLocal()
    try:
        integrations = db.query(ADPIntegration).filter(
            ADPIntegration.is_enabled == True
        ).all()

        for integration in integrations:
            try:
                workers = asyncio.run(fetch_adp_employees(integration))
                for worker in workers:
                    associate_oid = worker["associateOID"]
                    assignment_status = worker["workerStatus"]["statusCode"]["codeValue"]

                    employee = db.query(Employee).filter(
                        Employee.hr_system_id_adp == associate_oid,
                        Employee.company_id == integration.company_id
                    ).first()

                    if assignment_status == "Terminated":
                        if not employee: continue
                        if not employee.is_active: continue
                        
                        employee.is_active = False
                        employee.account_status = "inactive"

                        db.commit()

                        cognito = boto3.client("cognito-idp", region_name=settings.aws_region)
                        cognito.admin_disable_user(
                            UserPoolId=settings.aws_cognito_user_pool_id,
                            Username=employee.cognito_sub
                        )

                        accounts = db.query(AssignmentMember).join(TruckAssignment, AssignmentMember.assignment_id == TruckAssignment.id
                        ).filter(
                            AssignmentMember.employee_id == employee.id,
                            TruckAssignment.date > date.today(),
                            TruckAssignment.company_id == integration.company_id,
                        ).all()

                        for member in accounts:
                            db.delete(member)

                        db.commit()

                        write_audit(
                            db,
                            actor_id = "system",
                            company_id = str(integration.company_id),
                            action_type = "employee.adp_offboarded",
                            target_table = "employees",
                            target_id = str(employee.id),
                            before = {"is_active": True},
                            after = {"is_active": False, "account_status": "inactive"}
                        )

                        admin_or_mangers = db.query(Employee).filter(
                            Employee.role.in_(["admin", "manager"]),
                            Employee.company_id == integration.company_id
                        ).all()

                        for person in admin_or_mangers:
                            db.add(Notification(
                                company_id = integration.company_id,
                                employee_id = person.id,
                                type = "employee_offboarding",
                                message =(
                                    f"Offboarded terminated employee {employee.name} "
                                    f"completed at {datetime.now().strftime('%A %b %d')}."
                                )
                            ))
                        db.commit()

                    elif not employee:
                        db.add(Employee(
                            company_id = integration.company_id,
                            name = worker["person"]["legalName"]["formattedName"],
                            hr_system_id_adp = associate_oid,
                            hr_system_id_adp_verified = True,
                            account_status = "pending_verification",
                            is_active = True,
                            role = "walker"
                        ))
                        db.commit()
                        
                    else:
                        employee.name = worker["person"]["legalName"]["formattedName"]
                        employee.hr_system_id_adp_verified = True
                        db.commit()

            except Exception as e:
                logger.warning(f"Integration failed for company {integration.company_id}: {e}")
                continue

        return {"status": "ok"}

    finally:
        db.close()