from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/budget.db"
    simplefin_access_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_to: str = ""
    warning_threshold_pct: int = 80
    alert_threshold_pct: int = 100
    digest_frequency: str = "daily"  # "daily" | "weekly"
    sync_hour_utc: int = 11
    sync_interval_minutes: int = 0  # 0 = daily (uses sync_hour_utc); >0 = every N minutes
    simplefin_timeout_seconds: float = 120.0
    # Day of the month the recap email for the previous month fires. Default 5
    # so SimpleFIN has time to post late transactions.
    month_end_summary_day: int = 5


settings = Settings()
