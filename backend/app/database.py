import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

DATABASE_URL = settings.database_url

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Yield a database session and close it when the request is done.

    Intended for use as a FastAPI dependency via ``Depends(get_db)``.

    Yields:
        An active SQLAlchemy ``Session`` instance.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
