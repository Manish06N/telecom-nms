from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Values that change between a laptop and a server. They come from the environment."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Telecom NMS"
    debug: bool = False
    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    password_reset_minutes: int = 30
    database_url: str = "postgresql+psycopg://telecom:telecom@localhost:5432/telecom"
    redis_url: str = ""
    auto_seed: bool = True
    admin_email: str = "admin@telecom.local"
    admin_password: str = "Admin@12345"
    admin_name: str = "System Admin"
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    login_rate_limit_per_minute: int = 10
    cors_origins: str = "*"
    task_backend: str = "background"
    deliver_notifications: bool = True
    usage_alert_percent: int = 80
    plan_expiry_warning_days: int = 3
    sla_soon_minutes: int = 60
    dashboard_cache_seconds: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
