"""The rules and side effects of a person's chosen name (ADR-567).

The column is Employee.chosen_name; `Employee.name` reads it (a hybrid). This
module holds what every path that changes it must do the same way: the shape
rule, and keeping Cognito's `name` attribute (the greeting in AsheFlow's
security emails, ADR-563) equal to the shown name.
"""
from __future__ import annotations

import logging
import re

from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_LEN = 100
# Letters in any script, then letters, spaces, apostrophes (' and ’), hyphens
# and periods. Starting with a letter means no value can open with a
# spreadsheet formula character (= + - @), ADR-567 D10.
_SHAPE = re.compile(r"^[^\W\d_][^\W\d_ '’.\-]*(?:[ '’.\-]+[^\W\d_]+)*[.]?$")
RULES = ("Up to 100 characters: letters, spaces, apostrophes, hyphens and periods, "
         "starting with a letter.")


class ChosenNameError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def normalise(raw: str) -> str:
    name = re.sub(r"\s+", " ", (raw or "").strip())
    if not name or len(name) > MAX_LEN or not _SHAPE.match(name):
        raise ChosenNameError(422, f"A chosen name is {RULES[0].lower()}{RULES[1:]}")
    return name


def sync_cognito_name(employee, username: str | None) -> bool:
    """Set Cognito's `name` to what this person is now called. Best effort:
    the database is the record of the chosen name, and a failed sync only
    means an email greets them by the old name until the next change."""
    if not username:
        return False
    from app.services import account_security
    try:
        account_security._cognito().admin_update_user_attributes(
            UserPoolId=settings.aws_cognito_user_pool_id, Username=username,
            UserAttributes=[{"Name": "name", "Value": employee.name[:2048]}])
        return True
    except (ClientError, BotoCoreError) as exc:
        code = exc.response.get("Error", {}).get("Code") if isinstance(exc, ClientError) else type(exc).__name__
        logger.warning("chosen name: Cognito name sync failed: %s", code)
        return False
