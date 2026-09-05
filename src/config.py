"""
Centralized application configuration.

All runtime configuration comes from environment variables (loaded from a
`.env` file in local/dev, or from the real environment in production/CI).
Every other module should import the single `settings` instance from here
instead of calling `os.environ` directly, so there is exactly one place that
knows how configuration is sourced and validated.

See `.env.example` at the repo root for the full list of supported variables.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application ---
    environment: str = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # --- Database ---
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/inventory_db"
    test_database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/inventory_db_test"

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- JWT ---
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # --- Bootstrap admin ---
    default_admin_email: str = "admin@example.com"
    default_admin_password: str = "ChangeMe123!"

    # --- Reservations ---
    reservation_timeout_minutes: int = 15
    reservation_cleanup_interval_seconds: int = 60

    # --- Outbox relay ---
    outbox_poll_interval_seconds: int = 1

    # --- Payment retry policy ---
    payment_retry_backoff_seconds: str = "5,30"
    payment_max_attempts: int = 3

    @property
    def payment_retry_backoff_list(self) -> list[int]:
        """Parse the comma separated backoff string into a list of ints."""
        return [int(v.strip()) for v in self.payment_retry_backoff_seconds.split(",") if v.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (env is only parsed once per process)."""
    return Settings()


settings = get_settings()
