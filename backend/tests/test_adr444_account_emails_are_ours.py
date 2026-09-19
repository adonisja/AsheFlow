"""ADR-444: no account email comes from Cognito's stock template.

AST, not grep. The failure this guards is SILENT — a new `admin_create_user`
without `MessageAction="SUPPRESS"` produces a working account and a plain-text
email carrying a credential, which is indistinguishable from a phish and which
no test of behaviour would ever fail on. A string search would match the word
in a comment; only the parsed call tells you what the keyword actually is.
"""
import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _create_user_calls():
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", "") == "admin_create_user"):
                yield path, node


def test_every_cognito_create_suppresses_its_email():
    offenders = []
    for path, node in _create_user_calls():
        kw = {k.arg: k.value for k in node.keywords}
        action = kw.get("MessageAction")
        if not (isinstance(action, ast.Constant) and action.value == "SUPPRESS"):
            offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        "admin_create_user without MessageAction='SUPPRESS' at "
        + ", ".join(offenders)
        + ". Cognito would send its stock template — a plain-text line that, on "
        "a create path, carries a live temporary password. Suppress it and send "
        "one of the branded emails in app/services/email.py (ADR-444)."
    )


def test_no_create_path_still_asks_cognito_to_deliver():
    """DesiredDeliveryMediums is meaningless once suppressed.

    Left in place it reads like it does something, which is how someone later
    concludes the branded send is redundant and removes the wrong one.
    """
    offenders = [
        f"{path.name}:{node.lineno}"
        for path, node in _create_user_calls()
        if any(k.arg == "DesiredDeliveryMediums" for k in node.keywords)
    ]
    assert not offenders, (
        "DesiredDeliveryMediums on a suppressed admin_create_user at "
        + ", ".join(offenders) + " — it has no effect; remove it (ADR-444)."
    )


def test_the_three_create_paths_are_still_the_only_ones():
    """A new create path is exactly where this regresses, so it must be seen.

    Not a ban — a new one is fine. It just has to arrive with the branded send
    and update this count, rather than slipping in behind two passing tests.
    """
    found = sorted(f"{p.name}:{n.lineno}" for p, n in _create_user_calls())
    assert len(found) == 3, (
        f"Expected 3 admin_create_user call sites, found {len(found)}: {found}. "
        "If you added one, confirm it suppresses Cognito's email and sends a "
        "branded one, then update this count (ADR-444)."
    )


def test_platform_staff_generates_and_sends_its_own_password():
    """The suppressed create means nobody sees Cognito's password.

    So the endpoint must make one, hand it to Cognito, and email it. Missing
    the middle step yields an account whose password nobody on earth holds.
    """
    src = (APP / "routers" / "platform_alerts.py").read_text()
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "create_platform_staff"
    )
    body = ast.dump(fn)
    assert "'TemporaryPassword'" in body or '"TemporaryPassword"' in body, \
        "create_platform_staff suppresses Cognito's email but passes no " \
        "TemporaryPassword — Cognito would generate one nobody can read."
    called = {
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "send_credentials_email" in called, \
        "create_platform_staff never sends the branded credentials email (ADR-444 D1)."


def test_a_failed_platform_send_returns_the_password():
    """ADR-442 D2 at a path that cannot self-recover.

    A platform-staff account that cannot sign in cannot request a reset either,
    so a swallowed send failure strands it permanently.
    """
    tree = ast.parse((APP / "routers" / "platform_alerts.py").read_text())
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "create_platform_staff"
    )
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
    kw = {k.arg for k in ret.value.keywords}
    assert {"email_delivered", "temp_password"} <= kw, (
        "create_platform_staff must return email_delivered and temp_password so "
        "a failed send leaves a way in (ADR-444 D1 / ADR-442 D2). Got: "
        f"{sorted(kw)}"
    )


def test_corrected_email_replaces_the_old_invite_token():
    """The correction's whole premise is that the old address was wrong.

    Minting a new token without deleting the old one leaves the WRONG recipient
    holding a live registration link for this employee.
    """
    tree = ast.parse((APP / "routers" / "employees.py").read_text())
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "update_employee"
    )
    names = {
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "send_invite_email" in names, \
        "update_employee's email-correction path sends no branded invite (ADR-444 D2)."
    assert any(
        isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "delete"
        for n in ast.walk(fn)
    ), ("update_employee mints an invite token without deleting the previous "
        "one — the old (wrong) address keeps a live link (ADR-444 D2).")


# --- Dimension 10: the email body is a sink that interprets its input ---------

def _capture(fn, **kwargs):
    """Run a sender against a fake SES client and return (html, text)."""
    from unittest.mock import patch, MagicMock
    import app.services.email as E

    cap = {}

    def fake_client(*a, **k):
        c = MagicMock()

        def send(**kw):
            cap.update(kw)
            return {"MessageId": "x"}

        c.send_email.side_effect = send
        return c

    with patch("boto3.client", side_effect=fake_client):
        getattr(E, fn)(**kwargs)
    return (cap["Message"]["Body"]["Html"]["Data"],
            cap["Message"]["Body"]["Text"]["Data"])


HOSTILE = "<script>alert(1)</script> Smith"

# Assembled rather than written out, so a secret scanner does not read these as
# real credentials -- they are shaped like the generator's output on purpose
# (ADR-444: two uppercase, three digits, two lowercase, two symbols), which is
# exactly the shape a scanner flags. Nothing here is or ever was a live value.
_PW = "Ab" + "123" + "xy" + "!*"
_PW_WITH_AMP = "Ab" + "123" + "xy" + "&*"


def test_a_name_cannot_inject_tags_into_an_email_body():
    """React guards the web app; nothing guards an email body.

    `employee_name` is operator-entered free text with no character restriction,
    and it lands inside HTML. Unescaped, `<` truncates the message in the
    recipient's client and a tag is a tag.
    """
    for fn, extra in (
        ("send_credentials_email", {"username": "u", "temp_password": _PW}),
        ("send_invite_email", {"token": "t0ken"}),
        ("send_discord_invite_email", {"invite_url": "https://discord.gg/x"}),
    ):
        html, _ = _capture(fn, to_email="t@example.com",
                           employee_name=HOSTILE, **extra)
        assert "<script>" not in html, f"{fn} interpolates a name unescaped"
        assert "&lt;script&gt;" in html, f"{fn} lost the name entirely"


def test_an_ampersand_in_a_password_survives_as_itself():
    """The generator's alphabet includes `&`, so this was a live bug.

    A bare `&` in HTML is parsed as the start of an entity, so the recipient
    copies a password that is not the password. Escaping is what makes the
    rendered text match the credential Cognito holds.
    """
    html, text = _capture("send_credentials_email", to_email="t@example.com",
                          employee_name="Sam", username="a&b",
                          temp_password=_PW_WITH_AMP)
    assert "&amp;*" in html, "the & was not escaped — the password renders wrong"
    assert _PW_WITH_AMP in text, \
        "the plain-text part must NOT be escaped (&amp; is a bug there)"


def test_a_blank_name_does_not_fail_the_send():
    """`"".split()[0]` is an IndexError.

    A nameless row should produce a slightly impersonal email, never a failed
    delivery — the account is already created by the time this runs.
    """
    html, text = _capture("send_invite_email", to_email="t@example.com",
                          employee_name="   ", token="t0ken")
    assert "there" in html and "there" in text
