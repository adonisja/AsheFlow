"""Reshape the staging roster to match a real DSP, with testing headroom.

TARGET (operator's employer, 115 staff, plus headroom):
    walker 83 · trainer 14 · driver 12 · captain 10 · trainee 4
    dispatch 4 · management 1 · admin 2          = 130

WHY PROMOTION RATHER THAN CREATION for drivers and captains:
A newly created driver has no assignment history, so their My Stats renders
empty and the truck-scoped path stays untested. Promoting someone who already
rode on trucks gives them real AssignmentMember rows to read from.

This is SAFE because assignment_history scopes by `member.role` — the slot role
held THAT DAY — not by the employee's current job title. A promoted walker's
past days correctly stay counts_scope="own"; only days they work as a driver
read truck-wide. Verified at assignment_history.py:241.

PROTECTED: every *.test account, and trainer.test stays a trainer.
"""
from app.database import SessionLocal
from app.models.company import Company
from app.models.employee import Employee
from app.models.delivery_stop import DeliveryStop
from sqlalchemy import func, text

db = SessionLocal()
c = db.query(Company).first()

PROTECTED = {"walker.test", "driver.test", "trainee.test", "trainer.test",
             "captain.test", "dispatch.test", "admin.user-a", "manager.user-a",
             "admin.user-b", "manager.user-b"}

def actives(role):
    return (db.query(Employee)
            .filter(Employee.company_id == c.id, Employee.is_active == True,
                    Employee.role == role)
            .all())

def stop_count(e):
    return db.query(func.count(DeliveryStop.id)).filter(
        DeliveryStop.walker_id == e.id).scalar() or 0

print("=== BEFORE ===")
for r, n in sorted(db.query(Employee.role, func.count(Employee.id))
                   .filter(Employee.company_id == c.id, Employee.is_active == True)
                   .group_by(Employee.role).all(), key=lambda x: -x[1]):
    print(f"  {r:12} {n}")

# ── 1. promote 9 trainers -> captain (most history first, so the truck-scoped
#      view has data to show). trainer.test is protected.
trainers = [e for e in actives("trainer") if e.username not in PROTECTED]
trainers.sort(key=stop_count, reverse=True)
promoted_cap = trainers[:9]
for e in promoted_cap:
    e.role = "captain"
print(f"\npromoted {len(promoted_cap)} trainers -> captain")

# ── 2. promote 6 walkers -> driver
walkers = [e for e in actives("walker") if e.username not in PROTECTED]
walkers.sort(key=stop_count, reverse=True)
promoted_drv = walkers[:6]
for e in promoted_drv:
    e.role = "driver"
print(f"promoted {len(promoted_drv)} walkers -> driver")
db.flush()

# ── 3. delete the surplus, LEAST history first: keeping the people with the
#      richest data makes every remaining account better to test with.
TARGET = {"walker": 83, "trainer": 14, "management": 1}
deleted = 0
for role, keep in TARGET.items():
    pool = [e for e in actives(role) if e.username not in PROTECTED]
    if len(pool) <= keep:
        continue
    pool.sort(key=stop_count)               # least history first
    n_del = len(actives(role)) - keep
    for e in pool[:n_del]:
        # Detach then delete, so FK-restricted children do not block the row.
        db.execute(text("UPDATE delivery_stops SET walker_id=NULL WHERE walker_id=:i"), {"i": e.id})
        db.execute(text("UPDATE rts_packages   SET walker_id=NULL WHERE walker_id=:i"), {"i": e.id})
        db.execute(text("UPDATE missing_packages SET walker_id=NULL WHERE walker_id=:i"), {"i": e.id})
        db.execute(text("DELETE FROM assignment_members WHERE employee_id=:i"), {"i": e.id})
        db.execute(text("DELETE FROM employees WHERE id=:i"), {"i": e.id})
        deleted += 1
print(f"deleted {deleted} employees")

# ── 4. the detached rows belong to nobody now: remove them so no orphan
#      inflates company-wide totals.
n = db.execute(text("DELETE FROM rts_packages WHERE walker_id IS NULL")).rowcount
m = db.execute(text("DELETE FROM missing_packages WHERE walker_id IS NULL")).rowcount
s = db.execute(text("DELETE FROM delivery_stops WHERE walker_id IS NULL")).rowcount
print(f"removed orphans: {s} stops, {n} rts, {m} missing")

db.commit()

print("\n=== AFTER ===")
tot = 0
for r, n in sorted(db.query(Employee.role, func.count(Employee.id))
                   .filter(Employee.company_id == c.id, Employee.is_active == True)
                   .group_by(Employee.role).all(), key=lambda x: -x[1]):
    print(f"  {r:12} {n}")
    tot += n
print(f"  {'TOTAL':12} {tot}")

print("\n=== TEST ACCOUNTS ===")
for u in sorted(PROTECTED):
    e = db.query(Employee).filter(Employee.username == u).first()
    if e:
        print(f"  {u:16} {e.role}")
