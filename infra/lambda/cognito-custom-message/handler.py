"""CustomMessage: every Cognito-generated email looks like us (ADR-478).

Cognito's default sign-in code reads:

    Your AsheFlow sign-in code is 824878. It expires in 3 minutes.

No header, no brand, no sender identity beyond the address -- and it is the
email a privileged user sees most often. ADR-456 suppressed the one Cognito
message we could suppress (the admin-create temp password, replaced by
send_credentials_email), but suppression only works where WE create the user. A
sign-in code is generated inside the auth flow: it cannot be suppressed, only
rewritten. That is this trigger.

FAILS OPEN, and that is the whole safety design. An exception in CustomMessage
BLOCKS the message -- for Authentication that is a locked-out user with no code,
for ForgotPassword a password that cannot be reset. So every path returns the
event unchanged on an unexpected error and lets Cognito send its plain default.
An ugly email is a bad day; a missing one is an incident. Same reasoning as
PreAuthentication (ADR-459).

NOTHING SENSITIVE IS LOGGED. The trigger source only -- never the code, the link
or the address. A code in CloudWatch is a credential in CloudWatch (ADR-466).
"""
import html
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# The brand, from design/palette.json. Navy is the FIELD, violet is the ACCENT on
# the one thing that matters -- the inverse of the gradient templates, which use
# the accent as the whole identity and read as somebody else's email
# (send_owner_invite_email's docstring, ADR-455).
NAVY = "#1B2A6B"
VIOLET = "#8517D3"
INK = "#1B2A6B"
MUTED = "#5B6180"
PAGE = "#F9F9FB"
LINE = "#E6E8F2"

# ADR-456. This source is SUPPRESSED at the call site so send_credentials_email
# can send the branded version. Rewriting it here would quietly reintroduce the
# double email that ADR removed -- so it is returned untouched, and a test pins
# that.
SUPPRESSED_SOURCES = frozenset({"CustomMessage_AdminCreateUser"})


def _shell(*, heading: str, intro: str, body_html: str, footer: str) -> str:
    """The house chrome: navy header, white card, muted footer.

    Table-based and inline-styled throughout because Outlook ignores flex and
    drops <style> blocks -- the same constraint send_owner_invite_email records.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:{PAGE};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:{PAGE};padding:40px 16px;">
    <tr><td align="center">
      <table width="520" cellpadding="0" cellspacing="0" style="max-width:520px;width:100%;">
        <tr><td style="background:{NAVY};border-radius:14px 14px 0 0;padding:28px 40px;">
          <table cellpadding="0" cellspacing="0"><tr>
            <td style="padding-right:10px;">
              <div style="width:30px;height:30px;background:{VIOLET};border-radius:8px;text-align:center;line-height:30px;">
                <span style="color:#fff;font-size:15px;font-weight:800;">A</span>
              </div>
            </td>
            <td><span style="color:#fff;font-size:17px;font-weight:700;letter-spacing:-0.2px;">AsheFlow</span></td>
          </tr></table>
          <p style="margin:18px 0 0;color:#fff;font-size:20px;font-weight:700;letter-spacing:-0.3px;">{heading}</p>
        </td></tr>
        <tr><td style="background:#ffffff;padding:32px 40px;border-left:1px solid {LINE};border-right:1px solid {LINE};">
          <p style="margin:0 0 20px;color:{INK};font-size:15px;line-height:1.6;">{intro}</p>
          {body_html}
        </td></tr>
        <tr><td style="background:#ffffff;border:1px solid {LINE};border-top:none;border-radius:0 0 14px 14px;padding:18px 40px;">
          <p style="margin:0;color:{MUTED};font-size:12px;line-height:1.5;">{footer}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _code_block(code: str) -> str:
    """A code is read aloud and typed, so it gets its own line.

    Large and letter-spaced rather than inline in a sentence, which is how the
    Cognito default reads and why it is easy to misread over a phone.
    """
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 20px;">'
        f'<tr><td align="center" style="background:{PAGE};border:1px solid {LINE};'
        f'border-radius:12px;padding:20px;">'
        f'<span style="color:{INK};font-size:30px;font-weight:700;letter-spacing:7px;'
        f'font-family:SFMono-Regular,Menlo,Consolas,monospace;">{html.escape(code)}</span>'
        f'</td></tr></table>'
    )


def _button(url: str, label: str) -> str:
    return (
        f'<table cellpadding="0" cellspacing="0" style="margin:0 0 20px;"><tr><td '
        f'style="background:{VIOLET};border-radius:10px;">'
        f'<a href="{html.escape(url, quote=True)}" '
        f'style="display:inline-block;padding:12px 22px;color:#ffffff;font-size:15px;'
        f'font-weight:600;text-decoration:none;">{label}</a>'
        f'</td></tr></table>'
    )


def _render(source: str, code: str, link: str) -> tuple[str, str] | None:
    """(subject, html) for a trigger source, or None to leave Cognito's default.

    COPY PER SOURCE, not one shared message. What the reader is doing differs --
    signing in, recovering an account, confirming an address -- and a single
    message for all three either says too little or claims the wrong thing.
    """
    if source == "CustomMessage_Authentication":
        return (
            "Your AsheFlow sign-in code",
            _shell(
                heading="Your sign-in code",
                intro="Enter this code to finish signing in.",
                body_html=_code_block(code) + (
                    f'<p style="margin:0;color:{MUTED};font-size:13px;line-height:1.6;">'
                    "The code expires shortly. If you did not try to sign in, "
                    "someone has your password and you should change it."
                    "</p>"
                ),
                footer="AsheFlow will never ask you for this code.",
            ),
        )

    if source == "CustomMessage_ForgotPassword":
        return (
            "Reset your AsheFlow password",
            _shell(
                heading="Reset your password",
                intro="Use this code to choose a new password.",
                body_html=_code_block(code) + (
                    f'<p style="margin:0;color:{MUTED};font-size:13px;line-height:1.6;">'
                    "If you did not ask to reset your password, you can ignore "
                    "this — nothing has changed yet."
                    "</p>"
                ),
                footer="AsheFlow will never ask you for this code.",
            ),
        )

    if source in ("CustomMessage_UpdateUserAttribute",
                  "CustomMessage_VerifyUserAttribute"):
        return (
            "Confirm your new AsheFlow email",
            _shell(
                heading="Confirm this address",
                intro="Enter this code to confirm the new address on your account.",
                body_html=_code_block(code) + (
                    f'<p style="margin:0;color:{MUTED};font-size:13px;line-height:1.6;">'
                    "Your old address stays in place until this is confirmed."
                    "</p>"
                ),
                footer="AsheFlow will never ask you for this code.",
            ),
        )

    if source in ("CustomMessage_SignUp", "CustomMessage_ResendCode"):
        body = _code_block(code) if code else ""
        if link:
            body += _button(link, "Confirm your account")
        return (
            "Confirm your AsheFlow account",
            _shell(
                heading="Confirm your account",
                intro="One step left before you can sign in.",
                body_html=body,
                footer="If you were not expecting this, you can ignore it.",
            ),
        )

    return None


# Named `handler` to match cognito-pre-auth and cognito-pre-signup: the
# Lambda Handler config reads `handler.handler`, and a second naming
# convention across four functions is a deploy waiting to be misconfigured.
def handler(event, _context):
    source = (event or {}).get("triggerSource", "")

    # ADR-456's suppression must survive. Rewriting this source would put the
    # temp password back into a second, unbranded email beside the one
    # send_credentials_email already sends.
    if source in SUPPRESSED_SOURCES:
        return event

    try:
        params = (event.get("request") or {}).get("codeParameter") or ""
        link = (event.get("request") or {}).get("linkParameter") or ""
        rendered = _render(source, params, link)
        if rendered is None:
            # An unknown source: Cognito's default is plain, and plain is better
            # than a message written for a different situation.
            logger.info("custom-message: no template for %s", source)
            return event

        subject, body = rendered
        event.setdefault("response", {})
        event["response"]["emailSubject"] = subject
        event["response"]["emailMessage"] = body
        # Source only. Never the code, the link, or the address (ADR-466).
        logger.info("custom-message: rendered %s", source)
        return event

    except Exception:
        # FAILS OPEN. A raise here BLOCKS the email -- a locked-out user with no
        # code, or a password that cannot be reset. Cognito's plain default is
        # the floor, and it is a good floor.
        logger.exception("custom-message: falling back to the default for %s", source)
        return event
