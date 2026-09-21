import boto3
import html
import logging
from botocore.exceptions import ClientError
from app.core.config import settings

logger = logging.getLogger(__name__)


def _greeting_name(employee_name: str) -> tuple[str, str]:
    """First name for the plain-text body, and an HTML-escaped copy for the HTML one.

    DIMENSION 10 (ADR-435). The name is operator-entered free text and lands
    inside an HTML email body. Unescaped, a name containing `<` silently
    truncates the message in the recipient's client, and `<img src=x
    onerror=...>` is an injected tag in whatever renders it. React protects the
    web app; nothing protects an email body, so it is escaped HERE, at the sink
    that interprets it, rather than at the point the name was typed -- a person
    genuinely called O'Brien is data, not an attack.

    Returns (plain, escaped) because the text/plain part must NOT be escaped:
    `O&#x27;Brien` in a plain-text email is a rendering bug.

    Also absorbs the empty case. `"".split()[0]` is an IndexError, which would
    turn a blank name into a failed send rather than a slightly impersonal one.
    """
    parts = employee_name.split()
    plain = parts[0] if parts else "there"
    return plain, html.escape(plain)

def _configuration_set_kwargs() -> dict:
    """ADR-445 D1. Stamp the configuration set so SES publishes bounce and
    complaint events to our SNS topic.

    Passed as **kwargs rather than a literal argument because SES REJECTS a
    send naming a configuration set that does not exist -- so an unset value
    must omit the parameter entirely, not send an empty string. That is the
    difference between "events are not wired up yet" and "no mail goes out".
    """
    name = getattr(settings, "ses_configuration_set", "") or ""
    return {"ConfigurationSetName": name} if name else {}


def _log_ses_failure(to_email: str, exc) -> None:
    """Log a send failure, naming the sandbox when that is what it is.

    ADR-442 D3. "email delivery failed" sent an operator to the IAM policies
    first, which were identical across environments and entirely fine. The cause
    was visible in the error all along: an AccessDenied whose RESOURCE is the
    recipient's identity ARN is the SES sandbox refusing an unverified
    recipient, not a missing permission.

    Naming it here means the log answers the question instead of starting a
    search.
    """
    err = getattr(exc, "response", {}).get("Error", {})
    code = err.get("Code", "Unknown")
    hint = ""
    if code == "AccessDenied" and f"identity/{to_email}" in str(exc):
        hint = (
            " — this is the SES sandbox refusing an unverified RECIPIENT, not "
            "an IAM policy problem. Verify the address, or request SES "
            "production access."
        )
    logger.error("SES send_email failed for %s (%s): %s%s", to_email, code, exc, hint)


def send_discord_invite_email(*, to_email: str, employee_name: str, invite_url: str) -> None:
    """Send a Discord server invite link to a newly activated employee."""
    first_name, first_name_html = _greeting_name(employee_name)

    subject = "Join the AsheFlow Discord server"
    body_text = (
        f"Hi {first_name},\n\n"
        f"Your AsheFlow account is now active. Join the team Discord server using the link below:\n\n"
        f"{invite_url}\n\n"
        f"This invite is single-use and expires in 7 days.\n\n"
        f"– The AsheFlow Team"
    )
    body_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f8;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">
        <tr><td style="background:linear-gradient(135deg,#4F35D2 0%,#7C3AED 100%);border-radius:16px 16px 0 0;padding:32px 40px;">
          <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:12px;padding:8px 14px;margin-bottom:16px;">
            <span style="color:#fff;font-size:18px;font-weight:800;">AF</span>
          </div>
          <h1 style="color:#fff;margin:0;font-size:24px;font-weight:700;">AsheFlow</h1>
          <p style="color:rgba(255,255,255,0.7);margin:4px 0 0;font-size:13px;">Field operations, simplified</p>
        </td></tr>
        <tr><td style="background:#ffffff;padding:36px 40px;border-left:1px solid #e8e8f0;border-right:1px solid #e8e8f0;">
          <p style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111827;">You're all set, {first_name_html}!</p>
          <p style="margin:0 0 28px;font-size:15px;color:#6b7280;line-height:1.6;">
            Your AsheFlow account is active. Join the team Discord server to receive dispatch notifications and stay connected with your crew.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center" style="padding-bottom:24px;">
              <a href="{invite_url}"
                 style="display:inline-block;background:#5865F2;color:#ffffff;
                        text-decoration:none;font-size:15px;font-weight:700;padding:14px 36px;
                        border-radius:10px;">
                Join Discord Server →
              </a>
            </td></tr>
          </table>
          <p style="margin:0;font-size:13px;color:#9ca3af;text-align:center;">
            This invite is single-use and expires in 7 days.
          </p>
        </td></tr>
        <tr><td style="background:#f8f7ff;border:1px solid #e8e8f0;border-top:none;border-radius:0 0 16px 16px;padding:20px 40px;text-align:center;">
          <p style="margin:0;font-size:12px;color:#9ca3af;">© AsheFlow · Field operations, simplified</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    client = boto3.client("ses", region_name=settings.aws_region)
    try:
        client.send_email(
            **_configuration_set_kwargs(),
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
        logger.info("Discord invite email sent to %s", to_email)
    except ClientError as e:
        _log_ses_failure(to_email, e)
        raise


def send_credentials_email(*, to_email: str, employee_name: str, username: str, temp_password: str) -> None:
    """Send a single branded email with username + temp password after registration.

    Replaces Cognito's plain-text system email entirely (AdminCreateUser is called
    with MessageAction=SUPPRESS so only this email is sent).
    """
    login_url  = f"{settings.app_base_url}/login"
    first_name, first_name_html = _greeting_name(employee_name)

    subject = "Your AsheFlow account is ready"
    body_text = (
        f"Hi {first_name},\n\n"
        f"Your AsheFlow account has been created. Here are your sign-in credentials:\n\n"
        f"  Username:          {username}\n"
        f"  Temporary password: {temp_password}\n\n"
        f"Sign in at: {login_url}\n\n"
        f"You will be prompted to set a new password on your first login.\n"
        f"Keep your credentials safe — do not share them.\n\n"
        f"– The AsheFlow Team"
    )
    body_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f8;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">

        <!-- Header -->
        <tr><td style="background:linear-gradient(135deg,#4F35D2 0%,#7C3AED 100%);border-radius:16px 16px 0 0;padding:32px 40px;">
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td>
                <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:12px;padding:8px 14px;margin-bottom:16px;">
                  <span style="color:#fff;font-size:18px;font-weight:800;letter-spacing:-0.5px;">AF</span>
                </div>
                <h1 style="color:#fff;margin:0;font-size:24px;font-weight:700;letter-spacing:-0.5px;">AsheFlow</h1>
                <p style="color:rgba(255,255,255,0.7);margin:4px 0 0;font-size:13px;">Field operations, simplified</p>
              </td>
            </tr>
          </table>
        </td></tr>

        <!-- Body -->
        <tr><td style="background:#ffffff;padding:36px 40px;border-left:1px solid #e8e8f0;border-right:1px solid #e8e8f0;">
          <p style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111827;">Welcome aboard, {first_name_html}!</p>
          <p style="margin:0 0 28px;font-size:15px;color:#6b7280;line-height:1.6;">
            Your account has been created. Use the credentials below to sign in for the first time.
          </p>

          <!-- Credentials card -->
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8f7ff;border:1px solid #e0daf7;border-radius:12px;margin-bottom:28px;">
            <tr>
              <td style="padding:20px 24px;">
                <p style="margin:0 0 16px;font-size:11px;font-weight:700;color:#7C3AED;text-transform:uppercase;letter-spacing:0.08em;">Sign-in credentials</p>
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="padding:10px 0;border-bottom:1px solid #ede9fe;">
                      <span style="font-size:12px;color:#9ca3af;font-weight:500;">USERNAME</span>
                      <div style="background:#ffffff;border:1px solid #e0daf7;border-radius:8px;padding:10px 14px;margin-top:6px;">
                        <span style="font-size:16px;font-weight:700;color:#111827;font-family:'Courier New',monospace;letter-spacing:0.02em;">{html.escape(username)}</span>
                      </div>
                      <p style="margin:4px 0 0;font-size:11px;color:#a78bfa;">Triple-click to select &amp; copy</p>
                    </td>
                  </tr>
                  <tr>
                    <td style="padding:10px 0 0;">
                      <span style="font-size:12px;color:#9ca3af;font-weight:500;">TEMPORARY PASSWORD</span>
                      <div style="background:#ffffff;border:1px solid #e0daf7;border-radius:8px;padding:10px 14px;margin-top:6px;">
                        <span style="font-size:16px;font-weight:700;color:#111827;font-family:'Courier New',monospace;letter-spacing:0.05em;">{html.escape(temp_password)}</span>
                      </div>
                      <p style="margin:4px 0 0;font-size:11px;color:#a78bfa;">Triple-click to select &amp; copy</p>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>
          </table>

          <!-- Notice -->
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;margin-bottom:28px;">
            <tr><td style="padding:14px 18px;">
              <p style="margin:0;font-size:13px;color:#92400e;line-height:1.5;">
                <strong>You will be asked to set a new password</strong> on your first sign-in. Keep these credentials private.
              </p>
            </td></tr>
          </table>

          <!-- CTA -->
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center">
              <a href="{login_url}"
                 style="display:inline-block;background:linear-gradient(135deg,#4F35D2 0%,#7C3AED 100%);color:#ffffff;
                        text-decoration:none;font-size:15px;font-weight:700;padding:14px 36px;
                        border-radius:10px;letter-spacing:0.01em;">
                Sign In to AsheFlow →
              </a>
            </td></tr>
          </table>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f8f7ff;border:1px solid #e8e8f0;border-top:none;border-radius:0 0 16px 16px;padding:20px 40px;text-align:center;">
          <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.6;">
            If you didn't expect this email, contact your admin.<br>
            © AsheFlow · Field operations, simplified
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    client = boto3.client("ses", region_name=settings.aws_region)
    try:
        client.send_email(
            **_configuration_set_kwargs(),
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
        logger.info("Credentials email sent to %s", to_email)
    except ClientError as e:
        _log_ses_failure(to_email, e)
        raise


def send_invite_email(*, to_email: str, employee_name: str, token: str) -> None:
    """Send a registration invite email via SES."""
    register_url = f"{settings.app_base_url}/register?token={token}"
    first_name, first_name_html = _greeting_name(employee_name)

    subject = "You've been invited to AsheFlow"
    body_text = (
        f"Hi {first_name},\n\n"
        f"Your manager has created an AsheFlow account for you.\n\n"
        f"Click the link below to set up your username and password:\n"
        f"{register_url}\n\n"
        f"This link expires in {settings.invite_expiry_days} days.\n\n"
        f"– The AsheFlow Team"
    )
    body_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f8;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">
        <tr><td style="background:linear-gradient(135deg,#4F35D2 0%,#7C3AED 100%);border-radius:16px 16px 0 0;padding:32px 40px;">
          <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:12px;padding:8px 14px;margin-bottom:16px;">
            <span style="color:#fff;font-size:18px;font-weight:800;">AF</span>
          </div>
          <h1 style="color:#fff;margin:0;font-size:24px;font-weight:700;">AsheFlow</h1>
          <p style="color:rgba(255,255,255,0.7);margin:4px 0 0;font-size:13px;">Field operations, simplified</p>
        </td></tr>
        <tr><td style="background:#ffffff;padding:36px 40px;border-left:1px solid #e8e8f0;border-right:1px solid #e8e8f0;">
          <p style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111827;">You've been invited, {first_name_html}!</p>
          <p style="margin:0 0 28px;font-size:15px;color:#6b7280;line-height:1.6;">
            Your manager has created an AsheFlow account for you. Click the button below to complete your setup.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center" style="padding-bottom:24px;">
              <a href="{register_url}"
                 style="display:inline-block;background:linear-gradient(135deg,#4F35D2 0%,#7C3AED 100%);color:#ffffff;
                        text-decoration:none;font-size:15px;font-weight:700;padding:14px 36px;
                        border-radius:10px;">
                Activate My Account →
              </a>
            </td></tr>
          </table>
          <p style="margin:0 0 4px;font-size:13px;color:#9ca3af;text-align:center;">Or copy this link into your browser:</p>
          <p style="margin:0;font-size:12px;color:#7C3AED;text-align:center;word-break:break-all;">
            <a href="{register_url}" style="color:#7C3AED;">{register_url}</a>
          </p>
        </td></tr>
        <tr><td style="background:#f8f7ff;border:1px solid #e8e8f0;border-top:none;border-radius:0 0 16px 16px;padding:20px 40px;text-align:center;">
          <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.6;">
            This link expires in {settings.invite_expiry_days} days. If you didn't expect this, you can ignore it.<br>
            © AsheFlow · Field operations, simplified
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    client = boto3.client("ses", region_name=settings.aws_region)
    try:
        client.send_email(
            **_configuration_set_kwargs(),
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
        _log_ses_failure(to_email, e)
        raise


def send_bot_setup_email(*, to_email: str, admin_name: str, invite_url: str,
                         company_name: str) -> None:
    """Tell a company admin to authorise the bot in their Discord server (ADR-448 D4).

    Sent when `discord_guild_id` is first saved — the moment the step becomes
    actionable. NOT at company creation, when nobody has chosen a server yet.

    The link is an OAuth consent URL, not a credential: a client id is public by
    construction and Discord's own consent screen is the access control. It is
    still only USABLE by someone with Manage Server on that guild, which is why
    it goes to a person rather than sitting in a log.
    """
    first_name, first_name_html = _greeting_name(admin_name)
    company_html = html.escape(company_name)

    subject = "One more step to connect Discord"
    body_text = (
        f"Hi {first_name},\n\n"
        f"You've set the Discord server for {company_name}. One step is left, and "
        f"only a Discord server admin can do it: authorise the AsheFlow bot to "
        f"join that server.\n\n"
        f"{invite_url}\n\n"
        f"Until the bot is in the server, dispatch notifications, crew rooms and "
        f"employee Discord invites will not work — even though your settings are "
        f"correct.\n\n"
        f"If you are not the Discord admin for {company_name}, forward this link "
        f"to whoever is.\n\n"
        f"— AsheFlow"
    )

    body_html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f8;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f8;padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">
        <tr><td style="background:linear-gradient(135deg,#4F35D2 0%,#7C3AED 100%);border-radius:16px 16px 0 0;padding:32px 40px;">
          <div style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:12px;padding:8px 14px;margin-bottom:16px;">
            <span style="color:#fff;font-size:18px;font-weight:800;">AF</span>
          </div>
          <h1 style="color:#fff;margin:0;font-size:24px;font-weight:700;">AsheFlow</h1>
          <p style="color:rgba(255,255,255,0.7);margin:4px 0 0;font-size:13px;">Field operations, simplified</p>
        </td></tr>
        <tr><td style="background:#ffffff;padding:36px 40px;border-left:1px solid #e8e8f0;border-right:1px solid #e8e8f0;">
          <p style="margin:0 0 8px;font-size:22px;font-weight:700;color:#111827;">One more step, {first_name_html}</p>
          <p style="margin:0 0 24px;font-size:15px;color:#6b7280;line-height:1.6;">
            You've set the Discord server for <strong style="color:#111827;">{company_html}</strong>.
            The last step can only be done by a Discord server admin: authorise the
            AsheFlow bot to join it.
          </p>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr><td align="center" style="padding-bottom:24px;">
              <a href="{invite_url}"
                 style="display:inline-block;background:#5865F2;color:#ffffff;
                        text-decoration:none;font-size:15px;font-weight:700;padding:14px 36px;
                        border-radius:10px;">
                Authorise AsheFlow in Discord →
              </a>
            </td></tr>
          </table>
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#fff8f1;border:1px solid #fde4cd;border-radius:10px;">
            <tr><td style="padding:14px 18px;">
              <p style="margin:0;font-size:13px;color:#9a5b1e;line-height:1.6;">
                Until the bot is in the server, dispatch notifications, crew rooms
                and employee Discord invites will not work &mdash; even though your
                settings are correct.
              </p>
            </td></tr>
          </table>
          <p style="margin:20px 0 0;font-size:13px;color:#9ca3af;text-align:center;">
            Not the Discord admin for {company_html}? Forward this to whoever is.
          </p>
        </td></tr>
        <tr><td style="background:#f8f7ff;border:1px solid #e8e8f0;border-top:none;border-radius:0 0 16px 16px;padding:20px 40px;text-align:center;">
          <p style="margin:0;font-size:12px;color:#9ca3af;">© AsheFlow · Field operations, simplified</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""

    client = boto3.client("ses", region_name=settings.aws_region)
    try:
        client.send_email(
            **_configuration_set_kwargs(),
            Source=settings.ses_from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
    except ClientError as exc:
        _log_ses_failure(to_email, exc)
        raise
