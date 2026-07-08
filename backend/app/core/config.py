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
    refresh_token_expire_minutes: int = 10080  # 7 дней — сессия без «Запомнить меня»
    refresh_token_remember_expire_minutes: int = 43200  # 30 дней — с «Запомнить меня»
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
    # Yandex Geosearch ToS: результаты работы API нельзя хранить дольше 30 дней
    # на обычном тарифе (см. docs/unit-economics.md). Строки склада с Яндекс-
    # происхождением, которых не видели столько дней, зачищаются от Яндекс-данных.
    yandex_raw_ttl_days: int = 30
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
    # ── ЮKassa (РФ-провайдер платежей) ─────────────────────────────────
    # shop_id и секретный ключ из ЛК ЮKassa → Настройки → API.
    # Секретный ключ — в .env на сервере, в репо НЕ коммитим.
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    # Чек 54-ФЗ (фискализация). По умолчанию включены, конфигурируется под
    # систему налогообложения ООО «ПРО ЛЕС»:
    #   tax_system_code = 2  → УСН доходы
    #   vat_code        = 7  → НДС 5% (специальная ставка УСН по ФЗ-176/2024,
    #                                  действует с 01.01.2025)
    yookassa_receipts_enabled: bool = True
    yookassa_tax_system_code: int = 2
    yookassa_vat_code: int = 7
    # Проверка IP вебхука по списку ЮKassa (docs.yookassa.ru/developers/
    # using-api/webhooks). Дополнительно к этому, обработчик в любом случае
    # перезапрашивает платёж по id → подделать webhook нельзя.
    yookassa_verify_ip: bool = True
    # no_contacts_penalty: «контакт» = email | телефон | домен (адрес — не контакт, только свои +8; см. scoring.py)
    scoring_weights_json: str = (
        '{"base":35,"domain":10,"email":20,"phone":10,"address":8,'
        '"no_contacts_penalty":-12,"demo_penalty":-20,"aggregator_penalty":-25,"keyword_bonus":12}'
    )
    scoring_niche_weights_json: str = "{}"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    # ── RuSender (РФ transactional email via HTTP API) ────────────────────
    # Preferred over SMTP on prod: Timeweb blocks outbound SMTP ports, but
    # RuSender sends over HTTPS (443). Free up to 100 emails/month. API key
    # from https://beta.rusender.ru/api/ — goes in server .env, NOT committed.
    rusender_api_key: str = ""
    rusender_from_email: str = "support@usebaza.ru"
    rusender_from_name: str = "БАЗА"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""  # Optional proxy URL for Anthropic API
    gigachat_credentials: str = ""  # Authorization key from developers.sber.ru
    gigachat_scope: str = "GIGACHAT_API_PERS"  # PERS (личный) или B2B / CORP
    gigachat_model: str = "GigaChat"  # GigaChat (Lite) | GigaChat-Pro | GigaChat-Max
    # ── YandexGPT (Yandex Cloud Foundation Models) ───────────────────────
    # API-Key auth (simpler than IAM-token rotation). Get one at:
    #   https://console.cloud.yandex.ru/ → IAM → Service accounts → API keys
    # Folder ID is required because the modelUri embeds it: gpt://<folder>/...
    yandex_gpt_api_key: str = ""
    yandex_gpt_folder_id: str = ""
    # Optional per-model LLM price overrides (kopecks per 1M tokens), e.g.
    # LLM_PRICES_KOPECKS_PER_MTOK='{"anthropic_in":25000}'. Empty → built-in
    # defaults in llm_client._DEFAULT_PRICES.
    llm_prices_kopecks_per_mtok: dict[str, int] = {}
    yandex_gpt_model: str = "yandexgpt-lite/latest"   # yandexgpt-lite | yandexgpt | yandexgpt-32k
    yandex_gpt_endpoint: str = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
    # Default provider order is yandex → anthropic → gigachat. Override via env
    # if you need a different primary; the chat() function still cascades
    # through the others on transient failure.
    llm_provider: str = "yandex"  # yandex | gigachat | anthropic

    # ── Company warehouse (cross-org registry) ───────────────────────────
    # When True, lead-collection jobs (1) write every finalized candidate
    # through to the shared `companies` table, and (2) seed each search with
    # warehouse hits for the same niche+geography — reusing previously
    # discovered companies for free (no 2GIS/Yandex/rusprofile API cost) and
    # improving recall on repeat searches. Best-effort: a warehouse failure
    # never blocks or alters normal collection. Set False to disable both.
    warehouse_search_enabled: bool = True

    # Dosed collection: when the warehouse can't fill a dose, a live search is
    # run with THIS limit to (re)seed the warehouse, then the dose is served from
    # it. Bigger = fewer live calls overall (one seed feeds many free doses) but a
    # larger one-time fetch. The number of companies reachable per niche+geo is
    # roughly bounded by this (live sources have no cross-run pagination cursor).
    warehouse_seed_limit: int = 150
    # After a paid live seed yields 0 new companies, skip live re-seeding for this
    # many hours (the warehouse stays the only source). Avoids burning API calls
    # on repeat clicks once a niche+geo is exhausted; new businesses are picked up
    # on the next allowed seed.
    collect_exhaust_cooldown_hours: int = 12
    # Dose per scheduled auto-collection run (same dosed/no-repeat model as the
    # manual button). Kept modest so a daily cron trickles new companies and
    # spreads monthly quota, rather than grabbing a big chunk each tick.
    auto_collect_dose: int = 25

    # ── 152-ФЗ compliance guard ──────────────────────────────────────
    # When False (default), the LLM client REFUSES to call any provider
    # whose data plane is outside the Russian Federation (currently:
    # Anthropic). This prevents accidental трансграничная передача to a
    # country not on the «adequate protection» list, which under Приказ
    # РКН №178 requires a separate notification BEFORE the first transfer.
    #
    # Set to True only if you have filed «Уведомление о трансграничной
    # передаче ПД» AND have explicit consent from data subjects covering
    # the destination country.
    llm_allow_foreign_providers: bool = False

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
