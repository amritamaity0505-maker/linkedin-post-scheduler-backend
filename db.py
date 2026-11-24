from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.config import settings

_engine = None
_SessionFactory = None


def get_engine(database_uri: str | None = None):
    global _engine, _SessionFactory
    if _engine is None or database_uri is not None:
        uri = database_uri or settings.sqlalchemy_database_uri
        try:
            temp_engine = create_engine(
                uri,
                pool_pre_ping=True,
                pool_recycle=3600,
                pool_size=10,
                max_overflow=20,
            )
            # Check connection if custom app user was configured
            if not database_uri and settings.DB_APP_USER:
                with temp_engine.connect() as conn:
                    pass
            _engine = temp_engine
        except Exception as exc:
            err_msg = str(exc)
            if ("1044" in err_msg or "1045" in err_msg or "Access denied" in err_msg) and settings.DB_APP_USER:
                # Fallback to root/admin DB credentials
                _engine = create_engine(
                    settings.admin_sqlalchemy_database_uri,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                    pool_size=10,
                    max_overflow=20,
                )
            else:
                _engine = temp_engine

        _SessionFactory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=_engine,
            expire_on_commit=False,
        )
    return _engine


def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        get_engine()
    return _SessionFactory


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Provides a transactional database session scope."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
