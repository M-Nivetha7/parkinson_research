from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings

_engine = None
_SessionLocal = None


def configure(url: str | None = None, **engine_kwargs):
    """(Re)configure the engine. Tests pass an in-memory SQLite URL with StaticPool."""
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    if url.startswith("sqlite") and "connect_args" not in engine_kwargs:
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(url, **engine_kwargs)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_engine():
    if _engine is None:
        configure()
    return _engine


def get_db():
    if _SessionLocal is None:
        configure()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
