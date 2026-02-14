"""SQLAlchemy 2 engine and session. Sqlite for development, PostgreSQL for deployment."""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for models."""

    pass


# Default: in-memory sqlite for tests; override with DATABASE_URL for real use
def get_engine_url() -> str:
    """Database URL from env or default sqlite."""
    import os
    return os.environ.get(
        "DATABASE_URL",
        "sqlite:///qman.sqlite",
    )


engine = create_engine(
    get_engine_url(),
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in get_engine_url() else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (for dev). In production use Alembic migrations."""
    Base.metadata.create_all(bind=engine)
