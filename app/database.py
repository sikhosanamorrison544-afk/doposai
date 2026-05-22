from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy.pool import NullPool

from .config import DATABASE_URL


class Base(DeclarativeBase):
    """Base class for all ORM models."""


_IS_SQLITE = DATABASE_URL.startswith("sqlite")


def _set_sqlite_pragmas(dbapi_conn, connection_record):
    """Set SQLite PRAGMA settings for better performance on Raspberry Pi."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA cache_size=-16384")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


if _IS_SQLITE:
    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "check_same_thread": False,
            "timeout": 30.0,
        },
        pool_pre_ping=True,
        poolclass=NullPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragmas(dbapi_conn, connection_record):
        _set_sqlite_pragmas(dbapi_conn, connection_record)
else:
    # Small pool: Render Postgres basic-256mb cannot sustain many connections.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=5,
        pool_recycle=300,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency that provides a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
