import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()


def _normalize_db_url(url: str) -> str:
    """
    Hosts hand out 'postgres://...' or 'postgresql://...'. SQLAlchemy needs to
    be told which driver to use, and its default changed between versions
    (2.1 switched from psycopg2 to psycopg3). We ship psycopg2-binary, so
    always say so explicitly.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


# Set this to your actual Postgres connection string - see README for where
# to get one (a free Render/Railway Postgres instance both work fine).
DATABASE_URL = _normalize_db_url(
    os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/drishti")
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency - one DB session per request, closed automatically."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
