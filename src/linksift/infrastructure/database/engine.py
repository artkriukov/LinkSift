from pydantic import SecretStr
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DatabaseConfigurationError(RuntimeError):
    pass


def _secret_value(database_url: SecretStr | str) -> str:
    return database_url.get_secret_value() if isinstance(database_url, SecretStr) else database_url


def create_database_engine(database_url: SecretStr | str) -> AsyncEngine:
    raw_url = _secret_value(database_url)
    if not raw_url:
        raise DatabaseConfigurationError("LINKSIFT_DATABASE_URL is not configured")

    try:
        url = make_url(raw_url)
    except (TypeError, ValueError):
        raise DatabaseConfigurationError("LINKSIFT_DATABASE_URL is invalid") from None

    if url.drivername != "postgresql+psycopg":
        raise DatabaseConfigurationError(
            "LINKSIFT_DATABASE_URL must use the postgresql+psycopg driver"
        )

    return create_async_engine(url, pool_pre_ping=True, hide_parameters=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
