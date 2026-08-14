"""Remove generated backfill history so it can be regenerated with the fixes.

Bounded to dates BEFORE the original seed (2026-07-04): everything earlier was
produced by seed_history_backfill.py, everything from that date on predates
this work and is left alone.
"""
from app.database import SessionLocal
from sqlalchemy import text

CUT = "2026-07-04"
db = SessionLocal()

before = db.execute(text("SELECT count(*) FROM routes WHERE route_date < :c"),
                    {"c": CUT}).scalar()
print(f"routes before cut: {before}")

# Children first: FKs point at routes / truck_assignments.
STATEMENTS = [
    ("rts_packages",      "DELETE FROM rts_packages WHERE route_id IN (SELECT id FROM routes WHERE route_date < :c)"),
    ("missing_packages",  "DELETE FROM missing_packages WHERE route_id IN (SELECT id FROM routes WHERE route_date < :c)"),
    ("delivery_stops",    "DELETE FROM delivery_stops WHERE route_id IN (SELECT id FROM routes WHERE route_date < :c)"),
    ("damaged_packages",  "DELETE FROM damaged_packages WHERE route_date < :c"),
    ("route_participants","DELETE FROM route_participants WHERE route_id IN (SELECT id FROM routes WHERE route_date < :c)"),
    ("routes",            "DELETE FROM routes WHERE route_date < :c"),
    ("assignment_members","DELETE FROM assignment_members WHERE assignment_id IN (SELECT id FROM truck_assignments WHERE date < :c)"),
    ("truck_assignments", "DELETE FROM truck_assignments WHERE date < :c"),
]
for name, stmt in STATEMENTS:
    n = db.execute(text(stmt), {"c": CUT}).rowcount
    print(f"  {name:20} -{n}")

db.commit()
print("routes remaining:", db.execute(text("SELECT count(*) FROM routes")).scalar())
print("stops remaining :", db.execute(text("SELECT count(*) FROM delivery_stops")).scalar())
