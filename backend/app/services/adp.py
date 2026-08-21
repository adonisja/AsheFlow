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

async def fetch_adp_team_timecards(
    integration: ADPIntegration, manager_associate_oid: str, work_date: date
) -> dict[str, list[dict]]:
    """Fetch one day's timecards for a manager's whole team, in a single call.

    Reads ADP Workforce Now's Team Time Cards API. `{aoid}` is **the manager
    whose team to return**, not a worker to look up — the endpoint is
    team-scoped, so one request covers every direct report. `$expand=dayEntries`
    is mandatory; without it ADP returns timecard headers with no entries.

    Returns `{associateOID: [timeEntry, ...]}` so the caller can index into the
    result per employee. An employee absent from the mapping has no timecard for
    that date. Returns {} on 404.

    Calling this once per employee would be one request per head (126+ for a
    typical DSP), each asking ADP for the team reporting to a walker — which is
    empty. The volume is the smaller problem; the query is simply wrong.

    Raises:
        ADPAuthError: If the OAuth token exchange fails.
        ADPServerError: If ADP returns a non-200/404 response, or a network-level
            failure prevents the request from being sent.
    """
    client_secret, cert_pem = _get_adp_credentials(integration)
    token = await _fetch_adp_token(client_secret, cert_pem, integration.adp_environment)

    base_url = "https://api.adp.com" if integration.adp_environment == "production" else "https://sandbox.api.adp.com"
    url = f"{base_url}/time/v2/workers/{manager_associate_oid}/team-time-cards"

    try:
        async with httpx.AsyncClient(cert=cert_pem) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$expand": "dayEntries",
                    "$filter": f"timeCards/timePeriod/startDate eq '{work_date.isoformat()}'",
                },
            )
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.warning(
            "ADP team timecard fetch failed due to network error for manager %s on %s: %s",
            manager_associate_oid, work_date, e,
        )
        raise ADPServerError(0, {})

    if response.status_code == 404:
        return {}

    if response.status_code != 200:
        logger.warning(
            "ADP team timecard fetch failed for manager %s on %s with status %s: %s",
            manager_associate_oid, work_date, response.status_code, response.text,
        )
        raise ADPServerError(response.status_code, response.json() if response.content else {})

    return _index_time_entries_by_associate(response.json())


def _index_time_entries_by_associate(payload: dict) -> dict[str, list[dict]]:
    """Flatten a team payload into {associateOID: [timeEntry, ...]}.

    Walks teamTimeCards[].timeCards[].dayEntries[].timeEntries[]. associateOID
    appears on both the teamTimeCards and timeCards levels; the inner value wins
    where present, since one team card can carry cards for several workers.

    Entries whose owner cannot be determined at either level are dropped rather
    than guessed — attributing a timecard to the wrong employee would propose a
    payroll correction against the wrong person.

    Defensive at every level: ADP omits empty collections rather than sending [].
    """
    indexed: dict[str, list[dict]] = {}

    for team_card in payload.get("teamTimeCards") or []:
        team_oid = team_card.get("associateOID")

        for time_card in team_card.get("timeCards") or []:
            oid = time_card.get("associateOID") or team_oid
            if not oid:
                logger.warning("ADP timecard with no associateOID at either level — dropped")
                continue

            for day_entry in time_card.get("dayEntries") or []:
                entries = day_entry.get("timeEntries") or []
                if entries:
                    indexed.setdefault(str(oid), []).extend(entries)

    return indexed

async def fetch_adp_pay_periods(integration: ADPIntegration) -> list[dict]:
    """Fetch the pay period schedule for this company's payroll group from ADP.

    Returns the raw list of pay period objects. Returns an empty list if ADP
    returns 404 (no payroll group configured) or if no pay periods are present.

    The caller is responsible for parsing period start/end, close deadline and
    pay date out of each entry — field names are validated in the sync task so a
    single malformed entry does not discard the whole batch.

    Raises:
        ADPAuthError: If the OAuth token exchange fails.
        ADPServerError: If ADP returns a non-200/404 response or if a
            network-level failure prevents the request from being sent.
    """
    if not integration.adp_payroll_group_id:
        logger.warning(
            "ADP pay period fetch skipped for company %s: no payroll group configured",
            integration.company_id,
        )
        return []

    client_secret, cert_pem = _get_adp_credentials(integration)
    token = await _fetch_adp_token(client_secret, cert_pem, integration.adp_environment)

    base_url = "https://api.adp.com" if integration.adp_environment == "production" else "https://sandbox.api.adp.com"
    url = f"{base_url}/payroll/v2/payroll-groups/{integration.adp_payroll_group_id}/pay-periods"

    try:
        async with httpx.AsyncClient(cert=cert_pem) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
            )
    except (httpx.TimeoutException, httpx.RequestError) as e:
        logger.warning("ADP pay period fetch failed due to network error for company %s: %s", integration.company_id, e)
        raise ADPServerError(0, {})

    if response.status_code == 404:
        return []

    if response.status_code != 200:
        logger.warning("ADP pay period fetch failed for company %s with status %s: %s", integration.company_id, response.status_code, response.text)
        raise ADPServerError(response.status_code, response.json() if response.content else {})

    return response.json().get("payPeriods", [])


# _changeCode vocabulary is NOT uniform across entry types in ADP's own examples:
# hoursEntry uses 'modify' to update, while timePairEntry and amountEntry use
# 'change'. AsheFlow only ever writes timePairEntry, so the correct literal is
# 'change'. Sending 'modify' is a valid literal for a different entry type — it
# would not obviously fail. Hardcoded, never parameterised (ADR-233).
_CHANGE_CODE_UPDATE = "change"
_ENTRY_TYPE_TIME_PAIR = "timePairEntry"


def build_break_correction_payload(
    associate_oid: str,
    work_assignment_id: str,
    entry_id: str,
    entry_date: date,
    break_start_at: datetime,
    break_end_at: datetime,
) -> dict:
    """Build the time-entries.modify payload for one break-window correction.

    Exactly one event — a single-employee payload takes ADP's synchronous path,
    avoiding 202-accepted polling and 207 partial-success handling entirely.

    Deliberately omits:
      - timeDuration / entryCode — those belong to hoursEntry, not timePairEntry.
      - laborAllocations — AsheFlow does not own department/job coding, and
        echoing stale values risks overwriting correct allocations. (Whether
        omission preserves or clears them is a sandbox question.)

    Kept separate from the request so the exact wire format can be asserted in a
    unit test without mocking HTTP.
    """
    return {
        "events": [
            {
                "serviceCategoryCode": {"codeValue": "time"},
                "eventNameCode": {"codeValue": "timeEntries.modify"},
                "data": {
                    "eventContext": {
                        "associateOID": associate_oid,
                        "workAssignmentID": work_assignment_id,
                    },
                    "transform": {
                        "timeEntries": [
                            {
                                "entryID": entry_id,
                                "entryTypeCode": {"codeValue": _ENTRY_TYPE_TIME_PAIR},
                                "entryDate": entry_date.isoformat(),
                                "startPeriod": {"startDateTime": break_start_at.isoformat()},
                                "endPeriod": {"endDateTime": break_end_at.isoformat()},
                                "_changeCode": _CHANGE_CODE_UPDATE,
                            }
                        ]
                    },
                },
            }
        ]
    }


async def patch_adp_timecard(
    integration: ADPIntegration,
    associate_oid: str,
    work_assignment_id: str,
    entry_id: str,
    entry_date: date,
    break_start_at: datetime,
    break_end_at: datetime,
) -> dict:
    """Submit an approved break-window correction to ADP Workforce Now.

    POSTs a single-employee timeEntries.modify event. Only ever called after the
    employee has signed off and a manager has approved (ADR-233) — this function
    performs no authorisation of its own and must never be wired to a detection
    path.

    entry_id comes from the read (timeEntries[].entryID) and is an opaque ADP
    string; it is never parsed.

    Returns the raw ADP response on success, or {} on 404 (entry not found).

    Raises:
        ADPAuthError: If the OAuth token exchange fails before the write.
        ADPClientError: On 4xx — the payload is structurally invalid. Caller
            should mark the adjustment non-retryable.
        ADPServerError: On 5xx, a network failure, or a 202/207 the caller cannot
            treat as applied. Caller should leave the adjustment retryable.
    """
    client_secret, cert_pem = _get_adp_credentials(integration)
    token = await _fetch_adp_token(client_secret, cert_pem, integration.adp_environment)

    base_url = "https://api.adp.com" if integration.adp_environment == "production" else "https://sandbox.api.adp.com"
    url = f"{base_url}/events/time/v2/time-entries.modify"

    payload = build_break_correction_payload(
        associate_oid, work_assignment_id, entry_id, entry_date, break_start_at, break_end_at
    )

    try:
        async with httpx.AsyncClient(cert=cert_pem) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
    except (httpx.TimeoutException, httpx.RequestError):
        raise ADPServerError(0, {})

    if response.status_code in (200, 201):
        return response.json() if response.content else {}

    if response.status_code == 404:
        return {}

    # 202 means the upload was accepted for asynchronous processing, NOT that the
    # timecard was updated — ADP returns requestStatusCode 'succeeded' on a 202
    # too. A single-employee payload should take the sync path, so a 202 here
    # means an assumption broke. 207 is per-event partial success. Treating
    # either as applied would stamp an adjustment that never reached payroll, so
    # both are raised as retryable rather than silently accepted.
    if response.status_code in (202, 207):
        logger.warning(
            "ADP timecard write returned %s for associate %s entry %s — not treated as "
            "applied; single-employee payload was expected to be synchronous.",
            response.status_code, associate_oid, entry_id,
        )
        raise ADPServerError(response.status_code, response.json() if response.content else {})

    if 400 <= response.status_code < 500:
        raise ADPClientError(response.status_code, response.json() if response.content else {})

    raise ADPServerError(response.status_code, response.json() if response.content else {})
