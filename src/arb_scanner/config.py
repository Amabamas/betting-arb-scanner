"""Settings loaded from .env / environment."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Authenticated venue credentials (all optional)
    kalshi_api_key_id: str | None = None
    kalshi_private_key_pem: str | None = None
    cloudbet_api_key: str | None = None
    ps3838_username: str | None = None
    ps3838_password: str | None = None
    overtime_api_key: str | None = None

    # Scanner config
    scanner_venues: str = ""  # csv; empty = all
    scanner_domain: Literal["sport", "prediction", "hybrid"] = "hybrid"
    scanner_interval_s: float = 15.0
    scanner_min_roi: float = 0.005
    scanner_min_liquidity_usd: float = 50.0
    scanner_time_window_hours: float = 2.0
    scanner_title_threshold: int = 82
    scanner_max_opps: int = 40
    scanner_log_level: str = "INFO"

    @property
    def enabled_venues(self) -> set[str] | None:
        if not self.scanner_venues.strip():
            return None
        return {v.strip().lower() for v in self.scanner_venues.split(",") if v.strip()}


def load_settings() -> Settings:
    return Settings()
