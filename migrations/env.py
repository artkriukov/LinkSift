import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from linksift.config import Settings
from linksift.infrastructure.database.engine import create_database_engine
from linksift.infrastructure.database.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    injected_url = config.attributes.get("database_url")
    if injected_url:
        return str(injected_url)
    return Settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    url = get_database_url()
    if not url:
        raise RuntimeError("Set LINKSIFT_DATABASE_URL before running migrations")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: object) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine: AsyncEngine = create_database_engine(get_database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    except SQLAlchemyError:
        raise RuntimeError("Database migration failed") from None
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
