"""ADR-518: a critical injury can be reported.

Filing one raised the RETIRED type 'incident_critical_injury', which throws by
design (ADR-487 D1), so the request failed and the incident was never saved.
"""
from datetime import date
from unittest.mock import patch

from app.models.incident import Incident
from app.models.notification import Notification
from app.routers import incidents as I
from app.schemas.incident import IncidentCreate
from app.services.notification_spec import RETIRED
from tests.conftest import make_employee, sqlite_mirror_with_defaults


def test_a_critical_injury_is_saved_and_oversight_is_told_once_each(db):
    sqlite_mirror_with_defaults(Incident.__table__).create(db.get_bind(), checkfirst=True)
    walker = make_employee(db, role="walker", name="Wally Walker")
    oversight = [make_employee(db, role=r, name=f"{r} person") for r in ("dispatch", "management", "admin")]
    db.commit()
    body = IncidentCreate(date=date(2026, 10, 15), category="injury", severity="critical",
                          description="Twisted ankle on the stairs at the third stop")
    with patch("app.services.notify._enqueue"):
        I.submit_incident(body, db=db, reporter=walker)

    assert db.query(Incident).filter_by(category="injury", severity="critical").count() == 1
    sent = db.query(Notification).all()
    critical = [n for n in sent if n.type == "incident_critical"]
    assert sorted(n.employee_id for n in critical) == sorted(e.id for e in oversight)
    # The reporter gets their confirmation; nothing retired is raised.
    assert [n.employee_id for n in sent if n.type == "incident_submitted"] == [walker.id]
    assert {n.type for n in sent} == {"incident_critical", "incident_submitted"}
    assert not {n.type for n in sent} & set(RETIRED)
