from collections.abc import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import BASE_DIR, settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str):
    if url.startswith("sqlite"):
        (BASE_DIR / "data").mkdir(exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False})

        # SQLite ignores foreign keys (ON DELETE CASCADE / SET NULL) unless asked.
        # Without this, rows of a deleted resume survive and attach to a reused id.
        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        return eng
    return create_engine(url, pool_pre_ping=True)


engine = _make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            # Several workers boot at once; only one may create the schema.
            conn.execute(text("SELECT pg_advisory_xact_lock(727274)"))
        Base.metadata.create_all(conn)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
