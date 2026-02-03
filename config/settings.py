"""
Application configuration using Pydantic Settings.
Loads from environment variables with .env file support.
"""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # Anthropic
    anthropic_api_key: str

    # E2B Sandbox
    e2b_api_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # App Config
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    max_audits_per_hour: int = 10
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Audit settings
    audit_timeout_seconds: int = 180
    max_competitors: int = 5

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
