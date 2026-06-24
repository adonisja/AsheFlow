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
    """Escalate the urgency level of open timecard adjustments as pay period close approaches.

    Runs at 00:05 AM Eastern on Saturday and Sunday — the window when Amazon DSP
    pay periods close and unresolved adjustments become payroll errors.

    For each open adjustment (pending_employee or pending_manager), recalculates
    urgency based on how much time remains before the pay period deadline. Urgency
    never downgrades — only updates if the new level is strictly higher than the
    current one. A per-company try/except ensures one company's failure does not
    block others.
    """
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
                    if adjustment.urgency not in URGENCY_RANK:
                        logger.warning("Unknown urgency value '%s' on adjustment %s (company %s) — skipping", adjustment.urgency, adjustment.id, integration.company_id)
                        continue
                    new_urgency = calculate_urgency(now, company_config)
                    if URGENCY_RANK[new_urgency] > URGENCY_RANK[adjustment.urgency]:
                        adjustment.urgency = new_urgency
                        db.commit()
                        
            except Exception as e:
                logger.warning("ADP urgency escalation failed for company %s: %s", integration.company_id, e)
                continue

        return {"status": "ok"}
    finally:
        db.close()