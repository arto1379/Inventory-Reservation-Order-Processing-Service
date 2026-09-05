"""
Alembic environment configuration.

Pulls the database URL from `src.config.settings` (i.e. from the same
`.env` file / environment the application itself uses) rather than from
`alembic.ini`, so there is exactly one source of truth for DATABASE_URL.
Also imports `src.models` so `Base.metadata` is fully populated, enabling
`alembic revision --autogenerate` for any *future* schema changes beyond
this project's hand-written initial migration.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.config import settings
from src.database import Base
from src.models import *  # noqa: F401,F403 -- populates Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live DB connection (`alembic upgrade --sql`)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live DB connection (the normal path)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
