import logging
from datetime import datetime, date, timezone

import boto3
import httpx

from app.core.config import settings
from app.models.adp_integration import ADPIntegration
from app.services.adp_exceptions import ADPAuthError, ADPClientError, ADPServerError

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

    Raises:
        ADPAuthError: If the token endpoint returns a non-200 response or if a
            network-level failure prevents the request from being sent.
    """
    base_url = "https://accounts.adp.com" if environment == "production" else "https://accounts.adp.com/auth/oauth/v2"
    token_url = f"{base_url}/token"

    try:
        async with httpx.AsyncClient(cert=cert_pem) as client:
            response = await client.post(
                token_url,
                data={"grant_type": "client_credentials", "client_secret": client_secret},
            )
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.warning("ADP token request failed due to network error: %s", e)
        raise ADPAuthError(0, "Could not reach the ADP authentication service. Please check your network connection and try again.")

    if response.status_code != 200:
        logger.warning("ADP token fetch failed with status %s: %s", response.status_code, response.text)
        raise ADPAuthError(response.status_code, "ADP authentication failed. Please verify your ADP credentials and certificate are correct.")

    return response.json()["access_token"]

async def fetch_adp_employees(integration: ADPIntegration) -> list[dict]:
    """Fetch all active workers from ADP RUN for this company.

    Returns the raw list of worker objects from ADP's Workers v2 API.

    Raises:
        ADPAuthError: If the OAuth token exchange fails.
        ADPServerError: If the ADP workers endpoint returns a non-200 response
            or if a network-level failure prevents the request from being sent.
    """
    client_secret, cert_pem = _get_adp_credentials(integration)
    token = await _fetch_adp_token(client_secret, cert_pem, integration.adp_environment)

    base_url = "https://api.adp.com" if integration.adp_environment == "production" else "https://sandbox.api.adp.com"
    url = f"{base_url}/hr/v2/workers"

    try:
        async with httpx.AsyncClient(cert=cert_pem) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"}
            )
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.warning("ADP employee fetch failed due to network error for company %s: %s", integration.company_id, e)
        raise ADPServerError(0, {})

    if response.status_code != 200:
        logger.warning("ADP workers fetch failed for company %s with status %s: %s", integration.company_id, response.status_code, response.text)
        raise ADPServerError(response.status_code, response.json() if response.content else {})

    return response.json().get("workers", [])

async def fetch_adp_timecard(integration: ADPIntegration, associate_oid: str, work_date: date) -> dict:
    """Fetch a single employee's timecard from ADP for a specific work date.

    Returns the raw timecard dict from ADP's Time and Attendance API.
    Returns an empty dict if ADP returns 404 (no timecard on record for that date)
    or if no time cards are present in the response.

    Raises:
        ADPAuthError: If the OAuth token exchange fails.
        ADPServerError: If ADP returns a non-200/404 response or if a
            network-level failure prevents the request from being sent.
    """
    client_secret, cert_pem = _get_adp_credentials(integration)
    token = await _fetch_adp_token(client_secret, cert_pem, integration.adp_environment)

    base_url = "https://api.adp.com" if integration.adp_environment == "production" else "https://sandbox.api.adp.com"
    url = f"{base_url}/time/v2/workers/{associate_oid}/time-cards"

    try:
        async with httpx.AsyncClient(cert=cert_pem) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": f"timeCards/entry/timePeriod/startDate eq '{work_date.isoformat()}'"},
            )
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.warning("ADP timecard fetch failed due to network error for associate %s on %s: %s", associate_oid, work_date, e)
        raise ADPServerError(0, {})

    if response.status_code == 404:
        return {}

    if response.status_code != 200:
        logger.warning("ADP timecard fetch failed for associate %s on %s with status %s: %s", associate_oid, work_date, response.status_code, response.text)
        raise ADPServerError(response.status_code, response.json() if response.content else {})

    time_cards = response.json().get("timeCards", [])
    return time_cards[0] if time_cards else {}

async def patch_adp_timecard(integration: ADPIntegration, associate_oid: str, adp_pay_period_id: str, break_start_at: date, break_end_at: date) -> dict:
    """Submit a corrected break window to ADP for a single employee's timecard.

    Sends a PATCH request to ADP's Time and Attendance API with the approved
    break start and end times. Returns the raw ADP response payload on success.
    Returns an empty dict if ADP returns 404 (timecard not found).

    Raises:
        ADPAuthError: If the OAuth token exchange fails before the write is attempted.
        ADPClientError: If ADP returns a 4xx response — the payload is structurally
            invalid. The caller should mark the adjustment as non-retryable.
        ADPServerError: If ADP returns a 5xx response or a network-level failure
            prevents the request from being delivered. The caller should leave
            the adjustment retryable for the next scheduled retry window.
    """
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
    try:
        async with httpx.AsyncClient(cert=cert_pem) as client:
            response = await client.patch(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=payload
            )
    except (httpx.TimeoutException, httpx.RequestError):
        raise ADPServerError(0,{})

    if response.status_code == 200:
        return response.json()
    
    if response.status_code == 404:
        return {}

    if 400 <= response.status_code < 500:
        raise ADPClientError(response.status_code, response.json())
    
    if 500 <= response.status_code < 600:
        raise ADPServerError(response.status_code, response.json())