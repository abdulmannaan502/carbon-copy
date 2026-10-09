"""Engine, session factory and low-level database helpers."""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base


def create_db_engine(url: str, echo: bool = False) -> Engine:
    if not url.startswith("sqlite"):
        return create_engine(url, echo=echo, pool_pre_ping=True)

    in_memory = url in ("sqlite://", "sqlite:///:memory:")
    engine = create_engine(
        url,
        echo=echo,
        # FastAPI may serve a request on a different thread than the one that
        # opened the connection; sessions are still never shared between requests.
        connect_args={"check_same_thread": False},
        # An in-memory database only lives as long as its single connection.
        poolclass=StaticPool if in_memory else None,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


_settings = get_settings()
engine = create_db_engine(_settings.database_url, echo=_settings.sql_echo)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    """Create tables for all registered models (no-op until models exist)."""
    import app.models  # noqa: F401  -- registers models on Base.metadata

    Base.metadata.create_all(bind=engine)


def ping_database(session: Session) -> bool:
    try:
        session.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False
