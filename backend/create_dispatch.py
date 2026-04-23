from app.database import SessionLocal
from app.services.run_dispatch import run_dispatch
from app.models.employee_off_day import EmployeeOffDay
from app.models.time_off_request import TimeOffRequest
from datetime import date, timedelta
import sys

def wipe_time_off_and_seed_dispatch():
    db = SessionLocal()
    today = date.today()
    try:
        # Delete time offs to make enough drivers available
        try:
            db.query(EmployeeOffDay).delete()
            db.query(TimeOffRequest).delete()
            db.commit()
            print("Wiped off-days to guarantee drivers are available")
        except Exception as e:
            print("Cleanup error", e)
            db.rollback()

        # Generate dispatch for today and previous days
        for i in range(14, -1, -1):
            target_date = today - timedelta(days=i)
            print(f"Running dispatch for {target_date}")
            try:
                run_dispatch(db, target_date)
                print("Success")
            except Exception as e:
                print(f"Error on {target_date}: {e}")
                db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    wipe_time_off_and_seed_dispatch()
