"""ADR-508 — a notification has one icon, and the registry owns it."""
from __future__ import annotations

import inspect
import re

import pytest

from app.models.notification import Notification
from app.services import notify as N
from app.services import notification_gallery as G
from app.services.notification_spec import SPEC
from tests.conftest import make_employee

LEAD = re.compile(r"^\s*(?:[←-⯿]|[\U0001F000-\U0001FAFF])")


class TestTheNormalisation:
    @pytest.mark.parametrize("raw,clean", [
        ("⚠️ **Trainee NCNS:** x", "**Trainee NCNS:** x"),   # with variation selector
        ("⏰ Truck 12 late", "Truck 12 late"),                # U+23F0: missed by the first regex
        ("  🆘 help", "help"),                                # U+1F198: missed by the first regex
        ("📍 Truck", "Truck"), ("🔁 Trainee", "Trainee"), ("⛽ fuel", "fuel"),
        ("Truck ⏰ mid", "Truck ⏰ mid"),                      # an inner emoji is content
        ("Plain text", "Plain text"), ("12 packages", "12 packages"),
    ])
    def test_only_a_leading_icon_is_removed(self, raw, clean):
        assert N.strip_leading_icon(raw) == clean

    def test_write_notification_stores_the_clean_message(self, db):
        emp = make_employee(db)
        n = N.write_notification(db, company_id=emp.company_id, employee_id=emp.id,
                                 type="anchor_point_running_late",
                                 message="⏰ Truck 12 — Alex is running late")
        db.flush()
        assert db.get(Notification, n.id).message == "Truck 12 — Alex is running late", (
            "the doubled icon the owner reported: ⏰ from the registry, ⏰ from the text"
        )

    def test_fan_out_stores_the_clean_message(self, db):
        a = make_employee(db, role="dispatch", name="A"); make_employee(db, role="dispatch", name="B")
        rows = N.fan_out(db, company_id=a.company_id, audience=("dispatch",),
                         type="crew_roster_submitted", message="📋 Crew roster is in")
        assert len(rows) == 2
        db.flush()
        assert all(r.message == "Crew roster is in" for r in rows)


class TestTheSources:
    def test_no_readable_template_starts_with_an_emoji(self):
        """The source half (D2). The normalisation would hide a regression; this
        finds it where it was written, using the gallery's extractor (ADR-507)."""
        G.extract_templates.cache_clear()
        bad = [(t, x.location) for t, xs in G.extract_templates().items()
               for x in xs if LEAD.match(x.text)]
        bad += [(t, "SAMPLES") for t, (_, v) in G.SAMPLES.items() if LEAD.match(v)]
        assert not bad, f"messages that start with their own icon: {bad}"

    def test_every_type_declares_an_icon(self):
        assert not [t for t, s in SPEC.items() if not s.icon]


class TestIconlessChannelsGetTheRegistryIcon:
    def test_discord_text_leads_with_the_registry_icon(self):
        assert N._with_icon("anchor_point_running_late", "Truck 12 late") == \
            f"{SPEC['anchor_point_running_late'].icon} Truck 12 late"

    def test_an_undeclared_type_is_sent_unchanged(self):
        assert N._with_icon("not_a_type", "x") == "x"

    def test_enqueue_uses_it_for_discord(self):
        src = inspect.getsource(N._enqueue)
        assert '"message": _with_icon(d.type, d.message)' in src

    def test_push_title_leads_with_the_registry_icon(self):
        from app.tasks import push_delivery_task as P
        src = inspect.getsource(P.send_push)
        assert 'title = f"{spec.icon} {spec.label}"' in src and "title=title" in src
