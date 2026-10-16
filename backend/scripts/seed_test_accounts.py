"""One sign-in per role in a SEED company (ADR-526).

`seed_demo.py` creates the demo companies and a roster of employees with no
Cognito account: they exist in the database but nobody can sign in as them.
This script creates the accounts a tester actually signs in with, `<role>.test`,
exactly as registration would (routers/registration.py):

  - Cognito user, MessageAction=SUPPRESS, email + email_verified + name
  - a PERMANENT password (from SEED_ACCOUNT_PASSWORD, never from this file)
  - the role's Cognito group, which the web navigation routes on (ADR-380 D1)
  - an Employee, account_status='active', linked by cognito_sub

Refuses any company whose data_class is not 'seed' (ADR-280). Idempotent: an
existing account is re-linked and its password reset to SEED_ACCOUNT_PASSWORD.
Dry run unless --apply.

    SEED_ACCOUNT_PASSWORD='...' SEED_ACCOUNT_EMAIL='someone+{label}@example.com' \\
      python scripts/seed_test_accounts.py --slug dsp-test [--apply]
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import boto3  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402

import app.models  # noqa: E402,F401  (registers every mapper)
from app.core.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.employee import Employee  # noqa: E402
from app.routers.registration import ROLE_TO_COGNITO_GROUP  # noqa: E402
from app.schemas.employee import VALID_ROLES  # noqa: E402
from app.services.audit import write_audit  # noqa: E402
from _seed_guard import seed_target  # noqa: E402

LABEL = {"management": "manager"}   # manager.test reads better than management.test


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="dsp-test")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    password = os.environ.get("SEED_ACCOUNT_PASSWORD")
    email_pattern = os.environ.get("SEED_ACCOUNT_EMAIL")
    if not email_pattern or "{label}" not in email_pattern:
        raise SystemExit("SEED_ACCOUNT_EMAIL must be set and contain {label}")
    if args.apply and not password:
        raise SystemExit("SEED_ACCOUNT_PASSWORD must be set to --apply")

    db = SessionLocal()
    try:
        company = seed_target(db, slug=args.slug)          # refuses live
        if company.data_class != "seed":                    # demo/other: not ours to touch
            raise SystemExit(f"Refusing {company.slug!r}: data_class={company.data_class!r}, not 'seed'.")
        cognito = boto3.client("cognito-idp", region_name=settings.aws_region)
        pool = settings.aws_cognito_user_pool_id
        print(f"company {company.slug} ({company.data_class}) pool {pool} {'APPLY' if args.apply else 'DRY RUN'}")

        for role in VALID_ROLES:
            label = LABEL.get(role, role)
            username = f"{label}.test"
            email = email_pattern.format(label=label)
            name = f"{label.replace('_', ' ').title()} Test"
            emp = db.query(Employee).filter(Employee.username == username).first()
            if emp is not None and emp.company_id != company.id:
                print(f"  ! {username}: exists in ANOTHER company; skipped")
                continue

            try:
                user = cognito.admin_get_user(UserPoolId=pool, Username=username)
                sub = next(a["Value"] for a in user["UserAttributes"] if a["Name"] == "sub")
                cognito_state = "exists"
            except ClientError as e:
                if e.response["Error"]["Code"] != "UserNotFoundException":
                    raise
                sub, cognito_state = None, "missing"

            print(f"  {username:28s} role={role:16s} cognito={cognito_state:7s} employee={'exists' if emp else 'missing'}")
            if not args.apply:
                continue

            if sub is None:
                resp = cognito.admin_create_user(
                    UserPoolId=pool,
                    Username=username,
                    UserAttributes=[
                        {"Name": "email", "Value": email},
                        {"Name": "email_verified", "Value": "true"},
                        {"Name": "name", "Value": name},
                    ],
                    MessageAction="SUPPRESS",   # ADR-444: never Cognito's stock email
                )
                sub = next(a["Value"] for a in resp["User"]["Attributes"] if a["Name"] == "sub")
            cognito.admin_set_user_password(UserPoolId=pool, Username=username,
                                            Password=password, Permanent=True)
            group = ROLE_TO_COGNITO_GROUP.get(role)
            if group:
                cognito.admin_add_user_to_group(UserPoolId=pool, Username=username, GroupName=group)

            created = emp is None
            if created:
                emp = Employee(id=uuid.uuid4(), company_id=company.id, name=name, role=role,
                               username=username, email=email, is_active=True,
                               account_status="active", cognito_sub=sub)
                db.add(emp)
            else:
                emp.cognito_sub, emp.email, emp.is_active, emp.account_status = sub, email, True, "active"
            db.flush()
            write_audit(db=db, company_id=company.id, actor_id=None,
                        action_type="seed.test_account_created" if created else "seed.test_account_relinked",
                        target_table="employees", target_id=str(emp.id),
                        detail={"username": username, "role": role, "adr": "ADR-526"})
            db.commit()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
