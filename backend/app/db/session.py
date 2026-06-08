from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=10,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False,
    connect_args={
        # Pin the session TimeZone to UTC so comparisons between naive timestamp
        # columns (stored as UTC wall-clock) and aware UTC params are unambiguous
        # regardless of the server's TimeZone GUC (matters for billing-period and
        # retention boundaries). Prod is already Etc/UTC; this makes it safe.
        "options": "-c statement_timeout=30000 -c lock_timeout=5000 -c timezone=UTC"
    },
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
