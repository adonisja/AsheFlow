"""Cap a user's remembered devices, evicting least-recently-used (ADR-377 D3).

Cognito enforces NO per-user device limit -- it remembers devices without bound
and `AdminListDevices` merely pages at 60. So the cap is ours to implement.

Why remembered devices and not multiple authenticators: Cognito holds exactly
one software token per user. Verifying a new secret silently invalidates the
previous one (measured on a scratch pool for ADR-377 -- OLD rejected, NEW
accepted), so a walker cannot register a phone AND a laptop as two factors; the
second registration locks the first out. One factor, three trusted devices, each
of which stops asking for the code, is what the requirement actually wants.

Eviction rather than refusal: refusing a 4th device punishes someone for
replacing their phone and produces a support ticket at 05:00. Forgetting the
least-recently-used one degrades to a challenge on the device they stopped
using, which is the correct outcome.

IAM REQUIRED -- easy to miss, because enforce_cap fails SOFT:

    cognito-idp:AdminListDevices
    cognito-idp:AdminForgetDevice

Both were absent from asheflow-ec2-role-{staging,prod} when this shipped
(AdminGetUser was allowed, so the role looked configured). Eviction would have
silently done nothing, logging a warning nobody reads, with a green test suite.
Verify with `aws iam simulate-principal-policy` against the pool ARN when
deploying to a new environment -- do not infer it from the service working.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Phone, personal laptop, and the shared station terminal is an ordinary
# combination. 2 forces a re-challenge every time someone alternates.
MAX_REMEMBERED_DEVICES = 3

# Cognito's own ceiling for one AdminListDevices page. A user at the cap has
# ~3 devices, so one page is always enough -- but ask for the max so a user who
# somehow accumulated more is still fully seen and trimmed.
_PAGE = 60


@dataclass(frozen=True)
class Device:
    key: str
    last_auth: Optional[datetime]
    remembered: bool

    @property
    def sort_key(self) -> datetime:
        """Missing timestamp sorts OLDEST, so it is evicted first.

        A device with no DeviceLastAuthenticatedDate has never completed an
        auth on that device. Treating it as newest would protect the least
        proven device and evict a phone in daily use.
        """
        return self.last_auth or datetime.min.replace(tzinfo=timezone.utc)


def parse_devices(raw: list[dict]) -> list[Device]:
    """Shape Cognito's AdminListDevices response. Pure, so it is testable."""
    out: list[Device] = []
    for d in raw:
        attrs = {a["Name"]: a["Value"] for a in d.get("DeviceAttributes", [])}
        out.append(Device(
            key=d["DeviceKey"],
            last_auth=d.get("DeviceLastAuthenticatedDate"),
            # Only remembered devices skip the challenge, so only they count
            # against the cap. A "not_remembered" row is inert.
            remembered=attrs.get("dev:device_remembered_status") == "remembered",
        ))
    return out


def select_for_eviction(devices: list[Device], cap: int = MAX_REMEMBERED_DEVICES) -> list[Device]:
    """Which remembered devices exceed the cap, oldest-used first.

    Only remembered devices are counted and only remembered devices are
    returned: forgetting an already-forgotten device is a no-op API call, and
    counting one toward the cap would evict a live device to make room for a
    row that never granted anything.
    """
    if cap < 1:
        # A cap of 0 would evict every device on every sign-in, re-challenging
        # the user forever. Refuse the configuration rather than enact it.
        raise ValueError("device cap must be at least 1")

    remembered = [d for d in devices if d.remembered]
    if len(remembered) <= cap:
        # A readability guard, not load-bearing: the slice below is already
        # empty at or under the cap, so `<` and `<=` are equivalent here
        # (verified exhaustively for n=0..6, cap=1..4). Mutation testing flags
        # the swap as a survivor for exactly that reason -- it is an equivalent
        # mutant, not a missing test. Do not "fix" it by tightening the slice.
        return []
    remembered.sort(key=lambda d: d.sort_key)
    return remembered[: len(remembered) - cap]


def enforce_cap(username: str, pool_id: str, region: str,
                cap: int = MAX_REMEMBERED_DEVICES) -> int:
    """Trim this user to `cap` remembered devices. Returns the number forgotten.

    Never raises. This runs on a sign-in path: an AWS hiccup must degrade to
    "one extra remembered device" rather than to a failed sign-in. The one thing
    worse than an uncapped fleet is a user who cannot log in because trimming it
    failed.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        client = boto3.client("cognito-idp", region_name=region)
        resp = client.admin_list_devices(
            UserPoolId=pool_id, Username=username, Limit=_PAGE,
        )
    except (ClientError, BotoCoreError) as exc:
        logger.warning("device_fleet: could not list devices: %s", type(exc).__name__)
        return 0

    doomed = select_for_eviction(parse_devices(resp.get("Devices", [])), cap)
    forgotten = 0
    for d in doomed:
        try:
            client.admin_forget_device(
                UserPoolId=pool_id, Username=username, DeviceKey=d.key,
            )
            forgotten += 1
        except (ClientError, BotoCoreError) as exc:
            # Keep going: forgetting 2 of 3 is better than 0 of 3, and the next
            # sign-in retries the rest.
            logger.warning(
                "device_fleet: could not forget a device: %s", type(exc).__name__,
            )

    if forgotten:
        # No device_name, no IP, no username in the log -- device_name carries
        # the OS and browser, and last_ip_used is personal data (D7).
        logger.info("device_fleet: forgot %d least-recently-used device(s)", forgotten)
    return forgotten
