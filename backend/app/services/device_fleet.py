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
# and the next sign-in re-challenges (ADR-385; privileged rule ADR-540).
#
# These bound how LONG one device stays trusted; MAX_REMEMBERED_DEVICES bounds
# how MANY are trusted at once. Neither subsumes the other: without the age
# bound, a single daily-driver device is remembered forever; without the count
# cap, a user accumulates unbounded trusted devices.
#
# Privileged: 12h since the device last PASSED MFA (its DeviceCreateDate --
# forgetting deletes the record, so the next challenged sign-in creates a new
# one). Not since last USE: ADR-385 shipped an idle rule, and a laptop used
# every morning was never re-challenged at all (ADR-540). 12h is the owner's
# choice: an 8-hour shift plus a buffer. It is STRICTER than NIST SP 800-63B-4
# AAL2 ("SHOULD be no more than 24 hours") and equal to AAL3 (12h). The 12h
# AAL2 figure is from the withdrawn 800-63-3 -- see the ADR-463 lesson, which
# ADR-540 nearly repeated.
#
# Field: 7 days since the last MFA too (owner, 2026-10-18). It was 7 days IDLE,
# which gave a phone in daily use no overall bound at all -- and 800-63B-4's one
# SHALL at every level is that an overall reauthentication timeout exists (AAL1
# SHOULD be <= 30 days). 7 days stays far from the per-session challenge a field
# user cannot tolerate: their app backgrounds and drops sessions constantly.
#
# Both tiers now measure from the last MFA, so the idle device rule (ADR-385's
# select_stale) is gone. "Last use" survives only in the COUNT rule below,
# where it correctly picks which device to evict first.
PRIVILEGED_CHALLENGE_TTL = timedelta(hours=12)   # since DeviceCreateDate
FIELD_DEVICE_TTL = timedelta(days=7)             # since DeviceCreateDate

# Cognito's own ceiling for one AdminListDevices page. A user at the cap has
# ~3 devices, so one page is always enough -- but ask for the max so a user who
# somehow accumulated more is still fully seen and trimmed.
_PAGE = 60


@dataclass(frozen=True)
class Device:
    key: str
    last_auth: Optional[datetime]
    remembered: bool
    # When the device last passed MFA (ADR-540). Defaulted so the count rule's
    # callers, which never needed it, are unchanged.
    created: Optional[datetime] = None

    @property
    def created_key(self) -> datetime:
        """Missing creation date sorts OLDEST: an unproven device is not trusted."""
        return self.created or datetime.min.replace(tzinfo=timezone.utc)

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
            created=d.get("DeviceCreateDate"),
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


def select_unchallenged(devices: list[Device], max_age: timedelta,
                        now: Optional[datetime] = None) -> list[Device]:
    """Which remembered devices last passed MFA more than `max_age` ago (ADR-540).

    The age rule for both tiers. USE does not extend it: a device signed in on
    every hour is still forgotten `max_age` after its challenge -- ADR-385's
    idle rule never re-challenged a device in daily use (ADR-540).

    Only remembered devices are returned: a `not_remembered` device is already
    challenged on every sign-in. Strictly past: a device challenged exactly
    `max_age` ago survives that tick.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - max_age
    return [d for d in devices if d.remembered and d.created_key < cutoff]


def forget_stale(username: str, pool_id: str, region: str, ttl: timedelta,
                 now: Optional[datetime] = None) -> int:
    """Forget this user's remembered devices that passed MFA more than `ttl` ago.

    Returns the count (ADR-385; age measured from the last MFA since ADR-540).

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

    doomed = select_unchallenged(parse_devices(resp.get("Devices", [])), ttl, now)
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
