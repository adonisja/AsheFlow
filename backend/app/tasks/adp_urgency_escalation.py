import logging

from datetime import datetime, timezone

from app.database import SessionLocal
from app.celery_app import celery_app
from app.models.timecard_adjustments import TimeCardAdjustment
from app.models.adp_integration import ADPIntegration
from app.models.company import CompanyConfig
from app.services.adp_urgency import calculate_urgency, URGENCY_RANK

logger = logging.getLogger(__name__)

@celery_app.task(name="app.tasks.adp_urgency_escalation.escalate_adjustment_urgency")
def escalate_adjustment_urgency() -> dict:
    db = SessionLocal()
    try:
        integrations = db.query(ADPIntegration).filter(
            ADPIntegration.is_enabled == True
        ).all()
        for integration in integrations:
            try: 
                company_config = db.query(CompanyConfig).filter(
                    CompanyConfig.company_id == integration.company_id
                ).first()
                now = datetime.now(timezone.utc)

                adjustments = db.query(TimeCardAdjustment).filter(
                    TimeCardAdjustment.company_id == integration.company_id,
                    TimeCardAdjustment.status.in_(["pending_employee", "pending_manager"])
                ).all()

                for adjustment in adjustments:
                    new_urgency = calculate_urgency(now, company_config)
                    if URGENCY_RANK[new_urgency] > URGENCY_RANK[adjustment.urgency]:
                        adjustment.urgency = new_urgency
                        db.commit()
                        
            except Exception as e:
                logger.warning(f"Integration failed for company: {integration.company_id}: {e}")
                continue

        return {"status": "ok"}
    finally:
        db.close()