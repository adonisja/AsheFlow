import logging
from datetime import datetime, date, timezone

import boto3
import httpx

from app.core.config import settings
from app.models.adp_integration import ADPIntegration

logger = logging.getLogger(__name__)

def _get_adp_credentials(integration: ADPIntegration) -> tuple[str, str]:
    """Retrieve ADP client secret and certificate from Secrets Manager.

    Returns (client_secret, certificate_pem) as strings.
    """

    sm = boto3.client("secretsmanager", region_name=settings.aws_region)
    secret = sm.get_secret_value(SecretId=integration.adp_client_secret_arn)["SecretString"]
    cert_pem = sm.get_secret_value(SecretId=integration.adp_certificate_arn)["SecretString"]
    return secret, cert_pem


async def _fetch_adp_token(client_secret: str, cert_pem: str, environment: str) -> str:
    """Exchange ADP client credentials for a short-lived OAuth bearer token.

    Uses mTLS — the certificate is passed as the client cert on the connection.
    """
    base_url = "https://accounts.adp.com" if environment == "production" else "https://accounts.adp.com/auth/oauth/v2"
    token_url = f"{base_url}/token"

    async with httpx.AsyncClient(cert=cert_pem) as client:
        response = await client.post(
            token_url,
            data={"grant_type": "client_credentials", "client_secret": client_secret},
        )

    if response.status_code != 200:
        logger.warning("ADP token fetch failed: %s", response.text)
        raise RuntimeError("Failed to obtain ADP access token")
    
    return response.json()["access_token"]

async def fetch_adp_employees(integration: ADPIntegration) -> list[dict]:
    """Fetch all active workers from ADP RUN for this company.

    Returns the raw list of worker objects from ADP's Workers v2 API.
    Raises RuntimeError on auth failure or unexpected ADP response.
    """
    client_secret, cert_pem = _get_adp_credentials(integration)
    token = await _fetch_adp_token(client_secret, cert_pem, integration.adp_environment)

    base_url = "https://api.adp.com" if integration.adp_environment == "production" else "https://sandbox.api.adp.com"
    url = f"{base_url}/hr/v2/workers"

    async with httpx.AsyncClient(cert=cert_pem) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"}
        )
    
    if response.status_code != 200:
        logger.warning ("ADP workers fetch failed for company %s: %s", integration.company_id, response.text)
        raise RuntimeError("Failed to fetch employees from ADP")

    return response.json().get("workers", [])

async def fetch_adp_timecard(integration: ADPIntegration, associate_oid: str, work_date: date) -> dict:
    """Fetch a single employee's timecard from ADP for a specific work date.

    Returns the raw timecard dict from ADP's Time and Attendance API.
    Returns an empty dict if ADP returns 404 (no timecard on record for that date).
    Raises RuntimeError on unexpected failures.
    """
    client_secret, cert_pem = _get_adp_credentials(integration)
    token = await _fetch_adp_token(client_secret, cert_pem, integration.adp_environment)

    base_url = "https://api.adp.com" if integration.adp_environment == "production" else "https://sandbox.api.adp.com"
    url = f"{base_url}/time/v2/workers/{associate_oid}/time-cards"

    async with httpx.AsyncClient(cert=cert_pem) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params={"$filter": f"timeCards/entry/timePeriod/startDate eq '{work_date.isoformat()}'"},
        )

    if response.status_code == 404:
        return {}
    
    if response.status_code != 200:
        logger.warning("ADP timecard fetch failed for %s on %s: %s", associate_oid, work_date, response.text)
        raise RuntimeError("Failed to fetch timecard from ADP")
    
    time_cards = response.json().get("timeCards", [])
    return time_cards[0] if time_cards else {}

async def patch_adp_timecard(integration: ADPIntegration, associate_oid: str, adp_pay_period_id: str, break_start_at: date, break_end_at: date) -> dict:
    client_secret, cert_pem = _get_adp_credentials(integration)
    token = await _fetch_adp_token(client_secret, cert_pem, integration.adp_environment)

    base_url = "https://api.adp.com" if integration.adp_environment == "production" else "https://sandbox.api.adp.com"
    url = f"{base_url}/time/v2/workers/{associate_oid}/time-cards"

    payload = {
        "timeLaborEntries": [
            {
                "payPeriodReference": {"id": adp_pay_period_id},
                "breakStart": break_start_at.isoformat(),
                "breakEnd": break_end_at.isoformat()
            }
        ]
    }

    async with httpx.AsyncClient(cert=cert_pem) as client:
        response = await client.patch(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=payload
        )

    if response.status_code == 404:
        return {}
    
    if response.status_code != 200:
        logger.warning(f"Failed to write timecard edits to adp")
        raise RuntimeError(f"Failed to write timecard edits to adp for Associate_OID: {associate_oid}")
    else:
        return response.json()