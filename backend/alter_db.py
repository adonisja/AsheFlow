from sqlalchemy import text
from app.database import engine

def alter_db():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE assignment_members DROP CONSTRAINT ck_assignment_members_role;"))
        conn.execute(text("ALTER TABLE assignment_members ADD CONSTRAINT ck_assignment_members_role CHECK (role IN ('driver', 'trainer', 'walker', 'trainee'));"))
        print("Successfully altered database constraint.")

if __name__ == "__main__":
    alter_db()
