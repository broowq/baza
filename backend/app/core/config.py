from functools import lru_cache
import json
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    secret_key: str = "change-me-super-secret"  # Validated at startup in main.py
    access_token_expire_minutes: int = 30
    refresh_token_expire_minutes: int = 10080
    database_url: str = "postgresql+psycopg2://lead:lead@localhost:5433/lead"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    searxng_url: str = "http://localhost:58080"
    searxng_timeout_seconds: float = 12.0
    searxng_retry_count: int = 3
    bing_api_key: str = ""
    yandex_maps_api_key: str = ""
    yandex_maps_lang: str = "ru_RU"
    twogis_api_key: str = ""  # optional, 2GIS catalog API
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    refresh_cookie_secure: bool = True
    refresh_cookie_samesite: str = "lax"
    refresh_cookie_name: str = "baza_refresh_token"
    email_verification_required: bool = False
    email_verification_expire_minutes: int = 1440
    password_reset_expire_minutes: int = 30
    frontend_app_url: str = "http://localhost:3000"
    log_level: str = "INFO"
    log_file: str = "logs/app.log"
    stripe_secret_key: str = ""
    stripe_public_key: str = ""
    stripe_webhook_secret: str = ""
    scoring_weights_json: str = (
        '{"base":35,"domain":10,"email":20,"phone":10,"address":8,'
        '"no_contacts_penalty":-12,"demo_penalty":-20,"aggregator_penalty":-25,"keyword_bonus":5}'
    )
    scoring_niche_weights_json: str = "{}"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""  # Optional proxy URL for Anthropic API

    @computed_field
    @property
    def cors_origins(self) -> list[str]:
        values = [part.strip() for part in self.frontend_origins.split(",")]
        return [value for value in values if value]

    @computed_field
    @property
    def scoring_weights(self) -> dict[str, int]:
        try:
            payload = json.loads(self.scoring_weights_json)
            return {str(k): int(v) for k, v in payload.items()}
        except Exception:
            return {}

    @computed_field
    @property
    def scoring_niche_weights(self) -> dict[str, dict[str, int]]:
        try:
            payload = json.loads(self.scoring_niche_weights_json)
            return {
                str(niche).lower(): {str(k): int(v) for k, v in config.items()}
                for niche, config in payload.items()
                if isinstance(config, dict)
            }
        except Exception:
            return {}


@lru_cache
def get_settings() -> Settings:
    return Settings()
