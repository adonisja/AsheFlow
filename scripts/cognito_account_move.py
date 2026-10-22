"""Recreate every account of one Cognito pool in its replacement (ADR-566 D2).

Usage:
  OWNER_EMAIL=... TEST_PASSWORD=... python scripts/cognito_account_move.py \
      <old-pool> <new-pool> <out-dir> [--apply]

Neither the owner's address nor any password is written into this file, the
repo, a log or stdout (ADR-547; owner's instruction). Both come from the
environment. Printed addresses are masked as <owner>+tag.

Per account (owner's decisions, 2026-10-22):
  - super_admin       generated temporary password, written to <out-dir>/handover.txt
                      (0600) for the owner; email unchanged; marked handed over.
  - EMAILED (real)    generated temporary password, EMAILED by Cognito to an
                      alias on the owner's inbox; unverified until that sign-in
                      verifies it (ADR-564).
  - everyone else     the shared test password, permanent; email is an alias on
                      the owner's inbox (an existing owner alias is kept).
  - test.platform_support is created if the old pool has none.

Carried: groups, `name`, `custom:pending_group`, and email_verified (D2: the
addresses are not changing, or are the owner's own inbox). NOT carried:
`custom:mfa_first_seen` -- everyone sets up two-factor again, and a carried
stamp whose 24-hour window had closed would lock a privileged account out of
enrolling at all.

Writes <out-dir>/mapping.json: [{username, old_sub, new_sub}] -- no addresses.
The database re-key reads it (scripts/cognito_rekey_database.py).
Default is a DRY RUN.
"""
import json
import os
import secrets
import string
import sys

import boto3

REGION = "us-east-2"
EMAILED = {"nicoy.hunt"}               # real people whose password is emailed
NEW_ACCOUNTS = {"test.platform_support": ["platform_support"]}
CARRIED_ATTRS = ("name", "custom:pending_group")


def role_tag(username: str) -> str:
    """The convention prod already uses: walker.test -> walker, test.surveyor -> surveyor."""
    if username.endswith(".test"):
        return username[: -len(".test")]
    if username.startswith("test."):
        return username[len("test."):]
    return username


def split(addr: str) -> tuple[str, str, str]:
    local, _, domain = addr.lower().partition("@")
    base, _, tag = local.partition("+")
    return base.replace(".", ""), tag, domain


def is_owner_alias(addr: str, owner: str) -> bool:
    b, _, d = split(addr or "")
    ob, _, od = split(owner)
    return bool(addr) and (b, d) == (ob, od)


def owner_alias(owner: str, tag: str) -> str:
    local, _, domain = owner.partition("@")
    return f"{local.split('+')[0]}+{tag}@{domain}"


def masked(addr: str, owner: str) -> str:
    if is_owner_alias(addr, owner):
        _, tag, _ = split(addr)
        return "<owner>" + (f"+{tag}" if tag else "")
    return "<their own address>"


def temp_password() -> str:
    a = string.ascii_letters + string.digits
    return "".join(secrets.choice(a) for _ in range(16)) + secrets.choice("!#%*") + "aZ9"


def accounts(c, pool: str) -> list[dict]:
    out, token = [], None
    while True:
        kw = {"UserPoolId": pool, "Limit": 60, **({"PaginationToken": token} if token else {})}
        r = c.list_users(**kw)
        for u in r["Users"]:
            attrs = {a["Name"]: a["Value"] for a in u["Attributes"]}
            groups = [g["GroupName"] for g in c.admin_list_groups_for_user(
                UserPoolId=pool, Username=u["Username"], Limit=60)["Groups"]]
            out.append({"username": u["Username"], "attrs": attrs, "groups": groups, "enabled": u["Enabled"]})
        token = r.get("PaginationToken")
        if not token:
            return out


def plan(old: list[dict], owner: str) -> list[dict]:
    rows = []
    for a in old:
        u, attrs = a["username"], a["attrs"]
        email = attrs.get("email") or ""
        if "super_admin" in a["groups"]:
            kind, new_email, verified = "handover", email, attrs.get("email_verified") == "true"
        elif u in EMAILED:
            kind, new_email, verified = "emailed", owner_alias(owner, role_tag(u)), False
        else:
            kind = "shared"
            new_email = email if is_owner_alias(email, owner) else owner_alias(owner, role_tag(u))
            verified = True
        rows.append({"username": u, "old_sub": attrs["sub"], "groups": a["groups"], "kind": kind,
                     "email": new_email, "verified": verified, "enabled": a["enabled"],
                     "carry": {k: attrs[k] for k in CARRIED_ATTRS if attrs.get(k)}})
    have = {r["username"] for r in rows}
    for u, groups in NEW_ACCOUNTS.items():
        if u not in have:
            rows.append({"username": u, "old_sub": None, "groups": groups, "kind": "shared",
                         "email": owner_alias(owner, role_tag(u)), "verified": True, "enabled": True, "carry": {}})
    return rows


def main() -> None:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    old_pool, new_pool, out_dir, apply = sys.argv[1], sys.argv[2], sys.argv[3], "--apply" in sys.argv
    owner, shared = os.environ.get("OWNER_EMAIL", "").strip().lower(), os.environ.get("TEST_PASSWORD", "")
    if "@" not in owner or not shared:
        sys.exit("OWNER_EMAIL and TEST_PASSWORD must be set in the environment")
    c = boto3.client("cognito-idp", region_name=REGION)
    if c.list_users(UserPoolId=new_pool, Limit=1)["Users"]:
        sys.exit(f"{new_pool} already has users; this script only fills an empty pool")
    rows = plan(accounts(c, old_pool), owner)
    emails = [r["email"] for r in rows]
    if len(set(emails)) != len(emails):
        sys.exit("two accounts would share an address; fix the plan first")
    for r in rows:
        print(f"  {r['username']:<24} {r['kind']:<9} {masked(r['email'], owner):<28} verified={r['verified']!s:<5} "
              f"groups={r['groups']} carry={sorted(r['carry'])}{'' if r['enabled'] else ' DISABLED'}")
    if not apply:
        print(f"DRY RUN — {len(rows)} accounts planned, nothing created.")
        return

    os.makedirs(out_dir, exist_ok=True)
    handover, mapping = [], []
    for r in rows:
        u = r["username"]
        attrs = [{"Name": "email", "Value": r["email"]},
                 {"Name": "email_verified", "Value": "true" if r["verified"] else "false"},
                 {"Name": "custom:pw_handed_over", "Value": "0" if r["kind"] == "emailed" else "1"}]
        attrs += [{"Name": k, "Value": v} for k, v in r["carry"].items()]
        kw = {"UserPoolId": new_pool, "Username": u, "UserAttributes": attrs}
        if r["kind"] == "emailed":
            kw.update(TemporaryPassword=temp_password(), DesiredDeliveryMediums=["EMAIL"])
        else:
            kw.update(MessageAction="SUPPRESS")
        created = c.admin_create_user(**kw)["User"]
        new_sub = next(a["Value"] for a in created["Attributes"] if a["Name"] == "sub")
        if r["kind"] == "shared":
            c.admin_set_user_password(UserPoolId=new_pool, Username=u, Password=shared, Permanent=True)
        elif r["kind"] == "handover":
            pw = temp_password()
            c.admin_set_user_password(UserPoolId=new_pool, Username=u, Password=pw, Permanent=False)
            handover.append(f"{u}\t{pw}")
        for g in r["groups"]:
            c.admin_add_user_to_group(UserPoolId=new_pool, Username=u, GroupName=g)
        if not r["enabled"]:
            c.admin_disable_user(UserPoolId=new_pool, Username=u)
        mapping.append({"username": u, "old_sub": r["old_sub"], "new_sub": new_sub})
        print(f"  created {u}")
    with open(os.path.join(out_dir, "mapping.json"), "w") as f:
        json.dump(mapping, f, indent=1)
    if handover:
        path = os.path.join(out_dir, "handover.txt")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(handover) + "\n")
        print(f"temporary passwords for {len(handover)} account(s) written to {path}")
    print(f"{len(mapping)} accounts created; mapping written to {out_dir}/mapping.json")


if __name__ == "__main__":
    main()
