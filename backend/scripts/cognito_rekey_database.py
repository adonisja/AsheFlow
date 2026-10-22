"""Point the database at the accounts in the new Cognito pool (ADR-566 D3).

Run inside the backend container, AFTER scripts/cognito_account_move.py:
    python scripts/cognito_rekey_database.py <mapping.json> <old-pool> <new-pool> [--apply]

mapping.json holds {username, old_sub, new_sub} and no addresses. In ONE
transaction this:
  1. rewrites every column that stores an account's sub (REKEY), old -> new;
  2. mirrors each moved account's email from the NEW pool into Employee.email /
     SurveyContributor.email (Cognito is the record, ADR-563 D1);
  3. provisions each company's bot client in the new pool and rewrites
     Company.machine_client_id (ADR-364). The old client stays in the old pool
     for the rollback window;
  4. writes ONE audit row with the mapping (capped, with a truncated flag).

Before anything, it walks every model column whose name says it may hold a
sub and refuses to run if one is neither in REKEY nor in NOT_A_SUB. A list of
known columns passes forever while the schema grows (ADR-499's lesson); this
enumerates the schema instead. Default is a DRY RUN that prints row counts.
No address is printed.
"""
import json
import re
import sys
import uuid

from sqlalchemy import or_

import app.main  # noqa: F401  registers every model on Base.metadata
from app.core.config import settings
from app.database import SessionLocal
from app.models.base import Base

# Every column that can hold a Cognito sub. Ownership columns first: a missed
# one silently takes a person's own data away from them.
REKEY = {
    ("employees", "cognito_sub"): "who an employee is",
    ("survey_contributors", "cognito_sub"): "who a surveyor is",
    ("survey_walks", "writer_sub"): "who owns a survey walk",
    ("survey_observations", "writer_sub"): "who owns an observation",
    ("survey_block_claims", "writer_sub"): "who holds a block claim",
    ("survey_withdrawals", "writer_sub"): "who withdrew their survey data",
    ("platform_session_stamps", "cognito_sub"): "a platform account's session stamp",
    ("mfa_reset_requests", "cognito_sub"): "whose two-factor reset this is",
    ("email_change_requests", "cognito_sub"): "whose email change this is",
    # History that may name a sub (a super admin acting): kept followable.
    ("mfa_reset_requests", "resolved_by_ref"): "who resolved a reset",
    ("email_change_requests", "requested_by_ref"): "who started an email change",
    ("platform_alerts", "resolved_by_sub"): "who resolved an alert",
}
# Matching names that do NOT hold a sub, each with the reason.
NOT_A_SUB = {
    ("platform_alerts", "subject_ref"): "a username or company ref, never a sub (email_change.py)",
}
LOOKS_LIKE_SUB = re.compile(r"(^|_)sub$|_sub_|_ref$")
AUDIT_CAP = 100


def unhandled_columns() -> list[tuple[str, str]]:
    out = []
    for t in Base.metadata.sorted_tables:
        for c in t.columns:
            key = (t.name, c.name)
            if LOOKS_LIKE_SUB.search(c.name) and key not in REKEY and key not in NOT_A_SUB:
                out.append(key)
    return out


def check_schema() -> dict:
    """Refuse to run against a schema this script doesn't fully understand."""
    missing = unhandled_columns()
    if missing:
        sys.exit(f"columns that may hold a sub but are not handled: {missing}. "
                 "Add each to REKEY or NOT_A_SUB (with a reason) first.")
    tables = {t.name: t for t in Base.metadata.sorted_tables}
    for (t, c) in REKEY:
        if t not in tables or c not in tables[t].columns:
            sys.exit(f"REKEY names {t}.{c}, which the models don't have")
    return tables


def run(db, mapping_all: list[dict], old_pool: str, new_pool: str, *, apply: bool, cog, provision) -> dict:
    """The whole re-key on one session; commits only when `apply`. `cog` is a
    cognito-idp client and `provision(company_id, name) -> (client_id, secret)`
    makes a bot client in the NEW pool -- both injected so a test can run it."""
    from app.models.company import Company
    from app.models.employee import Employee
    from app.models.survey_register import SurveyContributor
    from app.services.audit import write_audit

    tables = check_schema()
    mapping = [m for m in mapping_all if m.get("old_sub")]
    pairs = {m["old_sub"]: m["new_sub"] for m in mapping}
    counts = {}
    for (t, c) in REKEY:
        col = tables[t].c[c]
        counts[f"{t}.{c}"] = db.query(tables[t]).filter(col.in_(list(pairs))).count() if pairs else 0
    companies = db.query(Company).filter(Company.machine_client_id.isnot(None)).all()
    unmatched = [m["username"] for m in mapping
                 if not db.query(Employee).filter(Employee.cognito_sub == m["old_sub"]).count()
                 and not db.query(SurveyContributor).filter(SurveyContributor.cognito_sub == m["old_sub"]).count()]
    summary = {"accounts": len(mapping), "rows": counts, "bot_clients": len(companies), "unmatched": unmatched}
    if not apply:
        return summary

    for (t, c) in REKEY:
        col = tables[t].c[c]
        for old, new in pairs.items():
            db.execute(tables[t].update().where(col == old).values({c: new}))
    mirrored = 0
    for m in mapping_all:
        u = cog.admin_get_user(UserPoolId=new_pool, Username=m["username"])
        email = next((a["Value"] for a in u["UserAttributes"] if a["Name"] == "email"), None)
        for model in (Employee, SurveyContributor):
            row = db.query(model).filter(model.cognito_sub == m["new_sub"]).first()
            if row is not None and email and row.email != email:
                row.email, mirrored = email, mirrored + 1
    reprovisioned = []
    for co in companies:
        client_id, _secret = provision(co.id, co.name)
        reprovisioned.append({"company_id": str(co.id), "old": co.machine_client_id, "new": client_id})
        co.machine_client_id = client_id
    db.flush()
    # audit_logs.target_id is a UUID column; a pool id isn't one. A name-based
    # UUID is stable per pool, and the ids themselves are in the detail.
    write_audit(db, action_type="cognito.pool_migrated", target_table="cognito_pools",
                target_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"cognito-idp:{new_pool}")),
                detail={"old_pool": old_pool, "new_pool": new_pool, "accounts": len(mapping),
                        "rows_rekeyed": counts, "emails_mirrored": mirrored,
                        "bot_clients": reprovisioned,
                        "mapping": [{"username": m["username"], "old_sub": m["old_sub"], "new_sub": m["new_sub"]}
                                    for m in mapping[:AUDIT_CAP]],
                        "truncated": len(mapping) > AUDIT_CAP})
    db.commit()
    return {**summary, "emails_mirrored": mirrored, "reprovisioned": len(reprovisioned)}


def main() -> int:
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    path, old_pool, new_pool, apply = sys.argv[1], sys.argv[2], sys.argv[3], "--apply" in sys.argv
    if settings.aws_cognito_user_pool_id not in (old_pool, new_pool):
        sys.exit(f"this backend is configured for {settings.aws_cognito_user_pool_id}, "
                 f"neither {old_pool} nor {new_pool}: wrong environment?")
    import boto3
    from app.services import tenant_machine_client as tmc

    def provision(company_id, name):
        settings.aws_cognito_user_pool_id = new_pool   # provision_machine_client reads it
        return tmc.provision_machine_client(company_id, name)

    db = SessionLocal()
    try:
        out = run(db, json.load(open(path)), old_pool, new_pool, apply=apply,
                  cog=boto3.client("cognito-idp", region_name=settings.aws_region), provision=provision)
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"{out['accounts']} moved accounts; rows that name an old sub:")
    for k, n in out["rows"].items():
        print(f"  {k:<45} {n}")
    print(f"bot clients in scope: {out['bot_clients']}")
    print(f"accounts with no employee/surveyor row (platform-only or roster-less): {out['unmatched']}")
    if apply:
        print(f"re-keyed; {out['emails_mirrored']} emails mirrored; {out['reprovisioned']} bot clients re-provisioned")
    else:
        print("DRY RUN — nothing changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
