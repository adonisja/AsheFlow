from sqlalchemy import text
from app.database import engine

def alter_db():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE training_records ADD COLUMN trainee_comments TEXT;"))
        conn.execute(text("ALTER TABLE training_records ADD COLUMN trainer_rating INTEGER;"))
    print("Successfully added trainee_comments and trainer_rating to training_records.")

if __name__ == "__main__":
    alter_db()
