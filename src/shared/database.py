from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

engine = None


def get_db():
    global engine
    if engine is None:
        # Prefer POSTGRES_* (Render & .env); fall back to DATABASE_* for local docker-compose
        host = os.environ.get("POSTGRES_HOST") or os.environ.get("DATABASE_HOST")
        username = os.environ.get("POSTGRES_USER") or os.environ.get("DATABASE_USER")
        password = os.environ.get("POSTGRES_PASSWORD") or os.environ.get("DATABASE_PASSWORD")

        db_name = (
            os.environ.get("POSTGRES_DB")
            or os.environ.get("DATABASE_NAME")
            or username  # old behavior
        )

        DATABASE_URL = (
            f"postgresql+psycopg2://{username}:{password}@{host}:5432/{db_name}"
        )

        engine = create_engine(DATABASE_URL)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
