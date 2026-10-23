"""A push is plain text (ADR-571).

The first real push to a device read "You have been assigned to **Truck 12**":
messages carry Markdown for the inbox, and the push sent it unchanged. FCM and
APNs render none of it.
"""
import inspect
from pathlib import Path

import pytest

from app.services.notification_gallery import sample_message
from app.services.notification_spec import SPEC
from app.services.push_delivery import plain_text

_ROOT = Path(__file__).resolve().parents[3]
_CLIENT_RULE = r"text.replace(/\*\*(.*?)\*\*/g, '$1').replace(/\*(.*?)\*/g, '$1')"


@pytest.mark.parametrize("text,expected", [
    ("You have been assigned to **Truck 12** for Thu.", "You have been assigned to Truck 12 for Thu."),
    ("Report *now* please", "Report now please"),
    ("**A** and **B**", "A and B"),
    ("2 * 3 = 6", "2 * 3 = 6"),
    ("", ""),
    (None, ""),
])
def test_emphasis_is_removed_and_nothing_else(text, expected):
    assert plain_text(text) == expected


@pytest.mark.parametrize("ntype", sorted(SPEC))
def test_no_registry_sample_keeps_markdown_in_a_push(ntype):
    assert "**" not in plain_text(sample_message(ntype))


def test_the_rule_is_the_clients_rule():
    """The push must read like the inbox preview, so it uses the same rule."""
    for rel in ("frontend/src/components/NotificationBanner.tsx",
                "mobile/src/screens/Notifications/NotificationsScreen.tsx"):
        assert _CLIENT_RULE in (_ROOT / rel).read_text(), f"{rel} changed its plain-text rule; update plain_text"


def test_the_push_task_sends_plain_text():
    from app.tasks import push_delivery_task as T
    assert "body=plain_text(notif.message)" in inspect.getsource(T)
