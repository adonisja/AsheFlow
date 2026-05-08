import boto3
import logging
from botocore.exceptions import ClientError
from app.core.config import settings

logger = logging.getLogger(__name__)


def send_invite_email(*, to_email: str, employee_name: str, token: str) -> None:
    """Send a registration invite email via SES."""
    register_url = f"{settings.app_base_url}/register?token={token}"
    first_name = employee_name.split()[0]

    subject = "You've been invited to AsheFlow"
    body_text = (
        f"Hi {first_name},\n\n"
        f"Your manager has created an AsheFlow account for you.\n\n"
        f"Click the link below to set up your username and password:\n"
        f"{register_url}\n\n"
        f"This link expires in {settings.invite_expiry_days} days.\n\n"
        f"– The AsheFlow Team"
    )
    body_html = f"""
    <html>
    <body style="font-family:sans-serif;color:#1a1a1a;max-width:480px;margin:0 auto;">
      <div style="background:#5B21B6;padding:24px 32px;border-radius:8px 8px 0 0;">
        <h1 style="color:#fff;margin:0;font-size:22px;">AsheFlow</h1>
        <p style="color:rgba(255,255,255,0.8);margin:4px 0 0;">Field operations, simplified</p>
      </div>
      <div style="background:#fff;padding:32px;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 8px 8px;">
        <p>Hi <strong>{first_name}</strong>,</p>
        <p>Your manager has created an AsheFlow account for you.</p>
        <p>Click the button below to set your username and password and activate your account.</p>
        <p style="text-align:center;margin:32px 0;">
          <a href="{register_url}"
             style="background:#5B21B6;color:#fff;padding:14px 28px;border-radius:6px;
                    text-decoration:none;font-weight:600;font-size:15px;">
            Activate My Account
          </a>
        </p>
        <p style="color:#6b7280;font-size:13px;">
          Or paste this link into your browser:<br>
          <a href="{register_url}" style="color:#5B21B6;">{register_url}</a>
        </p>
        <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
        <p style="color:#6b7280;font-size:12px;">
          This link expires in {settings.invite_expiry_days} days.
          If you didn't expect this email, you can ignore it.
        </p>
      </div>
    </body>
    </html>
    """

    client = boto3.client("ses", region_name=settings.aws_region)
    try:
        client.send_email(
            Source=settings.ses_from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html,  "Charset": "UTF-8"},
                },
            },
        )
        logger.info("Invite email sent to %s", to_email)
    except ClientError as e:
        logger.error("SES send_email failed for %s: %s", to_email, e)
        raise
