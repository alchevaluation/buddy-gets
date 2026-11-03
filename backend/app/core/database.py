from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from .config import get_settings
from .models import Base


def make_engine(database_url: str | None = None) -> Engine:
    return create_engine(
        database_url if database_url is not None else get_settings().database_url,
        pool_pre_ping=True,
    )


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
