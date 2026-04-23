from app.database import SessionLocal
from app.models.employee import Employee

def seed_one_trainee():
    db = SessionLocal()
    new_trainee = Employee(name="Trainee Tyler", discord_id="trainee_tyler_999", role="trainee", is_active=True)
    db.add(new_trainee)
    db.commit()
    print("Successfully added 1 more trainee (Trainee Tyler) to the database.")

if __name__ == "__main__":
    seed_one_trainee()
