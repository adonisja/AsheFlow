"""Probe the platform integrations before a person trips over them (ADR-337).

Every integration alert built so far fires only when someone USES the
integration: Discord on a publish, SES on an invite, Cognito on an offboarding.
That is how a revoked Discord token crash-looped the bot for weeks and surfaced
when a dispatcher reported that messages had stopped.

It also left two of three alert types unable to close themselves. Discord clears
on the next successful bot call (ADR-335 D3); SES has no equivalent, because the
next email may be days away. A board that must be tidied by hand is one people
stop believing.

This runs every ten minutes and both RAISES and CLEARS, which is what makes the
board reflect reality.
"""
import logging

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError

from app.celery_app import celery_app
from app.core.config import settings
from app.database import SessionLocal
from app.services.integration_alerts import (
    DISCORD_INTEGRATION_FAILED,
    DISCORD_DOWN_MESSAGE,
    EMAIL_DELIVERY_FAILED,
    EMAIL_DOWN_MESSAGE,
    IDENTITY_REVOCATION_FAILED,
    IDENTITY_REVOCATION_MESSAGE,
    raise_platform_alert,
    clear_integration_alert,
)

logger = logging.getLogger(__name__)

# Short: a health probe that hangs delays the other two and the beat schedule.
PROBE_TIMEOUT_SECONDS = 5


def _probe_discord() -> bool:
    """Is the bot logged in to Discord? (ADR-337 D2)

    Reads `discord_ready`, not the HTTP status. A liveness check would have
    reported healthy throughout the original incident: the container answered
    while the bot crash-looped on an invalid token, completely unable to send.
    """
    import os

    base = os.environ.get("BOT_INTERNAL_URL", "http://bot:8001")
    resp = requests.get(f"{base}/internal/health", timeout=PROBE_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return bool(resp.json().get("discord_ready"))


def _probe_ses() -> bool:
    """Does the SES credential work? Read-only — sends no mail.

    A health check with side effects becomes a thing people disable.
    """
    boto3.client("ses", region_name=settings.aws_region).get_send_quota()
    return True


def _probe_cognito() -> bool:
    """Is the user pool readable? Read-only, mutates nothing."""
    boto3.client("cognito-idp", region_name=settings.aws_region).describe_user_pool(
        UserPoolId=settings.aws_cognito_user_pool_id,
    )
    return True


# (probe, alert_type, message) — one entry per PLATFORM integration (ADR-336 D3).
# ADP is deliberately absent: its credentials are per-company, so a failure is
# that tenant's own admin's to fix and must not reach a cross-tenant board.
_PROBES = (
    (_probe_discord, DISCORD_INTEGRATION_FAILED, DISCORD_DOWN_MESSAGE),
    (_probe_ses, EMAIL_DELIVERY_FAILED, EMAIL_DOWN_MESSAGE),
    (_probe_cognito, IDENTITY_REVOCATION_FAILED, IDENTITY_REVOCATION_MESSAGE),
)


@celery_app.task(name="app.tasks.integration_health.check_integration_health")
def check_integration_health() -> dict:
    """Probe each platform integration; raise or clear its alert.

    Each probe is independently guarded (ADR-337 D5): one raising an unexpected
    exception must not skip the others, or an SES outage silently becomes
    "Cognito was never checked".

    Alerts carry `company_id=None` — these are platform credentials (ADR-337
    D4), which is the first producer to exercise ADR-335's `.is_(None)` dedup
    branch.
    """
    results: dict[str, str] = {}
    db = SessionLocal()
    try:
        for probe, alert_type, message in _PROBES:
            try:
                healthy = probe()
            except (requests.RequestException, ClientError, BotoCoreError) as e:
                logger.warning("health probe %s failed: %s", alert_type, e)
                healthy = False
            except Exception:
                # Never let one probe take out the rest — or the five other
                # scheduled tasks sharing this worker.
                logger.exception("health probe %s raised unexpectedly", alert_type)
                healthy = False

            if healthy:
                cleared = clear_integration_alert(db, alert_type=alert_type, company_id=None)
                results[alert_type] = f"healthy (cleared {cleared})"
            else:
                raise_platform_alert(
                    db, alert_type=alert_type, company_id=None, message=message,
                )
                results[alert_type] = "unhealthy"

        db.commit()
    except Exception:
        logger.exception("integration health check failed")
        db.rollback()
    finally:
        db.close()

    logger.info("integration health: %s", results)
    return results
