from app.database import SessionLocal
from app.models.employee import Employee

def seed_trainees():
    db = SessionLocal()
    existing = db.query(Employee).filter(Employee.role == "trainee").count()
    if existing > 0:
        print(f"Already have {existing} trainees.")
        return

    trainees = [
        Employee(name="Trainee Tom", discord_id="trainee_tom_123", role="trainee", is_active=True),
        Employee(name="Trainee Tina", discord_id="trainee_tina_456", role="trainee", is_active=True),
        Employee(name="Trainee Toby", discord_id="trainee_toby_789", role="trainee", is_active=True)
    ]
    db.add_all(trainees)
    db.commit()
    print("Successfully added 3 trainees to the database.")

if __name__ == "__main__":
    seed_trainees()
