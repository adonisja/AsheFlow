"""Compare the roles we USE against the Cognito groups that grant them (ADR-317).

WHY THIS EXISTS
---------------
The mobile nav filters tabs on `hasRole`, which reads the JWT's `cognito:groups`
claim — NOT `Employee.role`. So there are two systems of record for who is a
captain, and nothing compared them.

Measured during the incident that produced this module:

    DB (dsp-test):  8 employees with role='captain'
    Cognito:        captain 0    driver 1    walker 1
                    dispatch 2   management 1  admin 2   trainer 1

The `captain` group existed and was empty. Every captain signed in with a token
carrying no `captain` group, so every gated tab vanished and the app showed three
tabs. Both systems were internally consistent; neither could see the other.

REPORTS, DOES NOT ENFORCE (D1)
------------------------------
A hard failure at boot would take the API down for every correctly-grouped role
over a directory problem affecting one. And it must degrade to a warning when
Cognito is unreachable: an outage in their service is not an outage in ours.

PII (Dimension 6)
-----------------
Group names and COUNTS only. Never a username, an email, or a `sub` — a
directory diagnostic is not a place to put PII.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class RoleDirectoryReport:
    """What the two systems disagree about. Counts and names, never people."""
    # A role employees hold, with no Cognito group at all: nobody with that role
    # can log in usefully.
    roles_without_group: list[str] = field(default_factory=list)
    # The group exists but has no members — this incident, exactly.
    roles_with_empty_group: list[str] = field(default_factory=list)
    # A group nobody holds. Harmless on its own, but a sign of drift.
    groups_without_role: list[str] = field(default_factory=list)
    # Cognito could not be reached. NOT a failure (see module docstring).
    unavailable: bool = False

    @property
    def ok(self) -> bool:
        return not (self.roles_without_group or self.roles_with_empty_group)

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "unavailable": self.unavailable,
            "roles_without_group": sorted(self.roles_without_group),
            "roles_with_empty_group": sorted(self.roles_with_empty_group),
            "groups_without_role": sorted(self.groups_without_role),
        }


def _group_member_counts(pool_id: str, region: str) -> Optional[dict[str, int]]:
    """{group_name: member_count}, or None when the directory is unreachable."""
    import boto3

    client = boto3.client("cognito-idp", region_name=region)
    counts: dict[str, int] = {}
    try:
        paginator = client.get_paginator("list_groups")
        names: list[str] = []
        for page in paginator.paginate(UserPoolId=pool_id):
            names.extend(g["GroupName"] for g in page.get("Groups", []))

        for name in names:
            # Federated identity providers create groups of their own
            # (`<pool>_Google`, `<pool>_Discord`). They are not roles and
            # counting them would report permanent false drift.
            if name.startswith(pool_id):
                continue
            total = 0
            for page in client.get_paginator("list_users_in_group").paginate(
                UserPoolId=pool_id, GroupName=name
            ):
                total += len(page.get("Users", []))
            counts[name] = total
        return counts
    except Exception:
        # No exception text: a boto error can carry request ids and ARNs, and
        # this runs at boot where it would land in every log.
        logger.warning("role_directory_check: Cognito unreachable; skipping")
        return None


def check_role_directory(db, *, pool_id: str, region: str) -> RoleDirectoryReport:
    """Compare roles in use against populated Cognito groups.

    A role held by ZERO employees is not reported: we only care about roles
    someone actually has, because those are the ones whose sign-in is broken.
    """
    from app.models.employee import Employee

    roles_in_use = {
        r for (r,) in db.query(Employee.role).distinct().all() if r
    }
    report = RoleDirectoryReport()

    if not pool_id:
        report.unavailable = True
        return report

    counts = _group_member_counts(pool_id, region)
    if counts is None:
        report.unavailable = True
        return report

    for role in roles_in_use:
        if role not in counts:
            report.roles_without_group.append(role)
        elif counts[role] == 0:
            report.roles_with_empty_group.append(role)

    report.groups_without_role = [g for g in counts if g not in roles_in_use]
    return report


def log_role_directory(db, *, pool_id: str, region: str) -> RoleDirectoryReport:
    """Run the check and log the outcome. Never raises."""
    try:
        report = check_role_directory(db, pool_id=pool_id, region=region)
    except Exception:
        logger.warning("role_directory_check: failed; continuing")
        return RoleDirectoryReport(unavailable=True)

    if report.unavailable:
        logger.warning("role_directory_check: directory unavailable, not verified")
    elif report.ok:
        logger.info("role_directory_check: roles and Cognito groups agree")
    else:
        # WARNING, not ERROR: the app works for every correctly-grouped role.
        logger.warning(
            "role_directory_check: %d role(s) with no group %s, %d with an EMPTY "
            "group %s — users holding those roles sign in with no group claim and "
            "lose every role-gated tab (ADR-317)",
            len(report.roles_without_group), sorted(report.roles_without_group),
            len(report.roles_with_empty_group), sorted(report.roles_with_empty_group),
        )
    return report
