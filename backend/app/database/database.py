"""
Storm Energy RTU Platform — Database engine + session factory.
Uses SQLAlchemy 2.x with connection pooling for MS SQL Server via pyodbc.
Never construct SQL by string concatenation — always use parameterised queries.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


def _build_engine():
    settings = get_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=settings.SQL_POOL_SIZE,
        max_overflow=settings.SQL_MAX_OVERFLOW,
        pool_recycle=settings.SQL_POOL_RECYCLE,
        pool_pre_ping=True,          # validate connections before use
        echo=settings.LOG_LEVEL == "DEBUG",
        # pyodbc login timeout — bounded so health checks fail fast when SQL is unreachable
        connect_args={"timeout": settings.SQL_CONNECT_TIMEOUT},
    )

    @event.listens_for(engine, "connect")
    def set_isolation_level(dbapi_conn, _):
        """Ensure READ COMMITTED isolation for every new connection."""
        dbapi_conn.autocommit = False

    return engine


# Module-level singletons — created once at import time.
engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session and guarantees cleanup.
    Usage:
        @router.get("/")
        def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def db_session() -> Generator[Session, None, None]:
    """
    Context-manager variant for use outside FastAPI (MQTT consumer, TCP listener).
    Usage:
        with db_session() as db:
            db.add(record)
            db.commit()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def check_database_connection() -> bool:
    """Return True if the database is reachable; False otherwise."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database connectivity check failed: %s", exc)
        return False
