from logging.config import fileConfig
from os import getenv

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text

from alembic import context
from app.core.config import get_settings
from app.db.base import Base
from app.models import entities  # noqa: F401

# Serializes concurrent `alembic upgrade` runs. In prod the backend, worker
# and beat containers all share one image+entrypoint that runs migrations on
# start, so a deploy fires 3+ upgrades at once → a TOCTOU race where two
# runners both pass the "column absent?" guard and both ALTER → DuplicateColumn
# crash (which took the frontend down once, 2026-06-20). A session-level
# Postgres advisory lock makes the first runner migrate while the rest block,
# then find the DB already at head and no-op. Arbitrary but stable key.
_ALEMBIC_LOCK_KEY = 845_127_001

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = Base.metadata

settings = get_settings()
config.set_main_option("sqlalchemy.url", getenv("DATABASE_URL", settings.database_url))

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        is_pg = connection.dialect.name == "postgresql"
        if is_pg:
            # Blocking, session-level lock. Commit to end the implicit txn the
            # acquire opened — the advisory lock is session-scoped, not txn-
            # scoped, so it stays held across alembic's own migration txns.
            connection.execute(text("SELECT pg_advisory_lock(:k)"), {"k": _ALEMBIC_LOCK_KEY})
            connection.commit()
        try:
            context.configure(
                connection=connection, target_metadata=target_metadata
            )

            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_pg:
                # Explicit release for tidiness; closing the connection would
                # drop the session lock anyway.
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _ALEMBIC_LOCK_KEY})
                    connection.commit()
                except Exception:
                    pass


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
