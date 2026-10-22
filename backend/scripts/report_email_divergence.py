"""Which accounts' database email differs from Cognito's? (ADR-563 D5)

READ-ONLY. Before ADR-563, an admin editing an ACTIVE employee's email changed
only Employee.email; Cognito -- where sign-in and reset codes go -- kept the
old address. This lists every employee whose two copies differ, so an admin can
fix each with Change email (which confirms the new inbox). It doesn't fix
anything itself: which address is right is a question for a person.

Run inside the backend container:  python scripts/report_email_divergence.py
"""
import boto3
from botocore.exceptions import ClientError

from app.core.config import settings
from app.database import SessionLocal
from app.models.employee import Employee


def main() -> int:
    cog = boto3.client("cognito-idp", region_name=settings.aws_region)
    db = SessionLocal()
    rows, checked = [], 0
    try:
        for e in db.query(Employee).filter(Employee.username.isnot(None)).all():
            try:
                u = cog.admin_get_user(UserPoolId=settings.aws_cognito_user_pool_id, Username=e.username)
            except ClientError:
                continue   # no Cognito account (roster record): nothing to compare
            checked += 1
            attrs = {a["Name"]: a.get("Value") for a in u.get("UserAttributes", [])}
            cog_email = (attrs.get("email") or "").lower()
            db_email = (e.email or "").lower()
            if cog_email != db_email:
                rows.append((str(e.company_id), e.username, e.account_status, db_email or "-", cog_email or "-",
                             attrs.get("email_verified")))
    finally:
        db.close()
    print(f"checked {checked} employees with a Cognito account; {len(rows)} differ")
    for r in rows:
        print("company={} username={} status={} db={} cognito={} cognito_verified={}".format(*r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
