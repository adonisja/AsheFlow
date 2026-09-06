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
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Phone, personal laptop, and the shared station terminal is an ordinary
# combination. 2 forces a re-challenge every time someone alternates.
MAX_REMEMBERED_DEVICES = 3

# How long a remembered device may skip the MFA challenge before it is forgotten
# and the next sign-in re-challenges (ADR-385).
#
# These bound how LONG one device stays trusted; MAX_REMEMBERED_DEVICES bounds
# how MANY are trusted at once. Neither subsumes the other: without the age
# bound, a single daily-driver device is remembered forever; without the count
# cap, a user accumulates unbounded trusted devices.
#
# 24h for privileged matches NIST SP 800-63B's AAL2 reauthentication ceiling.
# 7d for field is deliberately below Duo's 30-day default -- the trend is
# downward against MFA-targeting attacks -- while staying far from the
# per-session challenge a field user cannot tolerate: their app backgrounds and
# drops sessions constantly on unreliable mobile networks.
PRIVILEGED_DEVICE_TTL = timedelta(hours=24)
FIELD_DEVICE_TTL = timedelta(days=7)

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


def select_stale(devices: list[Device], ttl: timedelta,
                 now: Optional[datetime] = None) -> list[Device]:
    """Which remembered devices have not been used within `ttl`.

    Distinct from select_for_eviction, which sorts by COUNT to a cap. This is
    the AGE rule (ADR-385) and the two are not interchangeable.

    Only remembered devices are returned: a device already marked
    `not_remembered` is inert -- it is challenged on every sign-in already, and
    forgetting it would be a wasted API call.

    A device with no DeviceLastAuthenticatedDate is treated as INFINITELY OLD,
    matching Device.sort_key. It has never completed an auth, so it has no claim
    to be trusted; the alternative -- treating a missing timestamp as "now" --
    would make an unproven device permanently un-forgettable.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - ttl
    return [d for d in devices if d.remembered and d.sort_key < cutoff]


def forget_stale(username: str, pool_id: str, region: str, ttl: timedelta,
                 now: Optional[datetime] = None) -> int:
    """Forget this user's remembered devices unused within `ttl`. Returns count.

    Never raises, for the same reason enforce_cap does not: this runs unattended
    on a schedule, and one user's AWS hiccup must not abort the sweep for
    everyone after them.
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

    doomed = select_stale(parse_devices(resp.get("Devices", [])), ttl, now)
    forgotten = 0
    for d in doomed:
        try:
            client.admin_forget_device(
                UserPoolId=pool_id, Username=username, DeviceKey=d.key,
            )
            forgotten += 1
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "device_fleet: could not forget a stale device: %s", type(exc).__name__,
            )

    if forgotten:
        # No device_name, no last_ip_used, no username -- device_name carries OS
        # and browser, and the IP is personal data (ADR-115 D7).
        logger.info("device_fleet: forgot %d stale device(s)", forgotten)
    return forgotten


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
