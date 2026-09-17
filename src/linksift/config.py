from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LINKSIFT_", env_file=".env", extra="ignore")

    environment: Literal["local", "preprod", "production"] = "local"
    bot_token: SecretStr = SecretStr("")
    database_url: SecretStr = SecretStr("")
    test_database_url: SecretStr = SecretStr("")
    allowed_user_ids: list[int] = Field(default_factory=list)
    data_dir: Path = Path("data")
    max_duration_seconds: int = Field(default=1800, gt=0)
    max_file_size_mb: int = Field(default=20, gt=0)
    media_ttl_seconds: int = Field(default=3600, gt=0, le=3600)
    history_ttl_days: int = Field(default=30, gt=0)
    analysis_pipeline: Literal["gemini", "local"] = "gemini"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = ""

    def allows(self, user_id: int | None) -> bool:
        return user_id is not None and user_id in self.allowed_user_ids
