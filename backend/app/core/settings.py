"""Centralized, environment-driven configuration.

Every security-relevant duration and limit lives here (PHASE_01A_PLAN §22.1).
No other module may hard-code session/token lifetimes or throttling limits.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_INSECURE_DEFAULT_SECRET = "insecure-local-development-secret-change-me-0000"  # noqa: S105
# Development/test key ring only (version 1). Deployed environments must supply their own keys.
_DEV_ENCRYPTION_KEYS = "1:YWR2ZWdheC1sb2NhbC1kZXYtb25seS1rZXktMzJieSE="


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class EmailBackend(StrEnum):
    SMTP = "smtp"
    MEMORY = "memory"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # --- Environment -------------------------------------------------------------
    ENVIRONMENT: Environment = Environment.LOCAL
    SECRET_KEY: SecretStr = SecretStr(_INSECURE_DEFAULT_SECRET)
    LOG_LEVEL: str = "INFO"

    # --- Database (three roles; see DATABASE_SCHEMA §19) ----------------------------
    DATABASE_URL_APP: SecretStr = SecretStr(
        "postgresql+psycopg://advegax_app:advegax_app@localhost:5432/advegax"
    )
    DATABASE_URL_SYSTEM: SecretStr = SecretStr(
        "postgresql+psycopg://advegax_system:advegax_system@localhost:5432/advegax"
    )
    DATABASE_URL_MIGRATOR: SecretStr = SecretStr(
        "postgresql+psycopg://advegax_migrator:advegax_migrator@localhost:5432/advegax"
    )
    DATABASE_POOL_SIZE: int = Field(default=10, ge=1)

    # --- Redis --------------------------------------------------------------------
    REDIS_URL: SecretStr = SecretStr("redis://localhost:6379/0")

    # --- Public URLs and CORS (D13) -------------------------------------------------
    APP_BASE_URL: str = "http://localhost:3000"
    API_BASE_URL: str = "http://localhost:8000"
    CORS_ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )
    TRUSTED_PROXY_COUNT: int = Field(default=0, ge=0, le=5)
    MAX_REQUEST_BYTES: int = Field(default=1_048_576, ge=1024)

    # --- Cookies --------------------------------------------------------------------
    SESSION_COOKIE_NAME: str = "advegax_session"
    CSRF_COOKIE_NAME: str = "advegax_csrf"
    COOKIE_SECURE: bool = False

    # --- Session and token lifetimes (approved defaults, A15) ------------------------
    SESSION_IDLE_TIMEOUT: timedelta = timedelta(hours=24)
    SESSION_ABSOLUTE_TIMEOUT: timedelta = timedelta(days=14)
    SESSION_TOUCH_INTERVAL: timedelta = timedelta(minutes=5)
    EMAIL_VERIFICATION_TTL: timedelta = timedelta(hours=24)
    PASSWORD_RESET_TTL: timedelta = timedelta(minutes=30)
    INVITATION_TTL: timedelta = timedelta(days=7)

    # --- Throttling (PHASE_01A_PLAN §9) ------------------------------------------------
    THROTTLE_LOGIN_PER_ACCOUNT_IP_PER_MINUTE: int = Field(default=5, ge=1)
    THROTTLE_LOGIN_PER_IP_PER_MINUTE: int = Field(default=20, ge=1)
    THROTTLE_REGISTER_PER_IP_PER_HOUR: int = Field(default=5, ge=1)
    THROTTLE_EMAIL_ACTION_PER_EMAIL_PER_HOUR: int = Field(default=3, ge=1)
    THROTTLE_EMAIL_ACTION_PER_IP_PER_HOUR: int = Field(default=10, ge=1)
    THROTTLE_FAIL_OPEN: bool = False
    # Platform webhooks (2A-05): per source IP. Shopify delivers from many addresses, so this
    # only bounds abuse; unsigned requests are rejected before any database work.
    THROTTLE_WEBHOOK_PER_IP_PER_MINUTE: int = Field(default=600, ge=1)
    # Platforms posting generated credentials (WooCommerce key delivery, 2B-04).
    THROTTLE_KEY_DELIVERY_PER_IP_PER_MINUTE: int = Field(default=30, ge=1)
    # "Sync now" on a store (2A-09): each run is a full deep check, so it is limited per store.
    THROTTLE_STORE_RESYNC_PER_HOUR: int = Field(default=6, ge=1)
    THROTTLE_AD_ACCOUNT_RESYNC_PER_HOUR: int = Field(default=6, ge=1)
    THROTTLE_ANALYTICS_PROPERTY_RESYNC_PER_HOUR: int = Field(default=6, ge=1)

    # --- Passwords ------------------------------------------------------------------
    PASSWORD_MIN_LENGTH: int = Field(default=12, ge=8)
    PASSWORD_MAX_LENGTH: int = Field(default=128, le=1024)

    # --- Transactional email (A9) -----------------------------------------------------
    EMAIL_BACKEND: EmailBackend = EmailBackend.SMTP
    EMAIL_FROM: str = "AdVegaX <no-reply@localhost>"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: SecretStr | None = None
    SMTP_USE_SSL: bool = False
    SMTP_STARTTLS: bool = False
    SMTP_TIMEOUT_SECONDS: float = Field(default=10.0, gt=0)
    EMAIL_MAX_ATTEMPTS: int = Field(default=5, ge=1)
    EMAIL_RETRY_BASE_DELAY: timedelta = timedelta(seconds=30)

    # --- Background jobs (Phase 1B) -----------------------------------------------
    CELERY_TASK_ALWAYS_EAGER: bool = False
    JOB_MAX_ATTEMPTS: int = Field(default=5, ge=1)
    JOB_RETRY_BASE_DELAY: timedelta = timedelta(seconds=30)
    JOB_RETRY_MAX_DELAY: timedelta = timedelta(hours=1)
    JOB_STUCK_AFTER: timedelta = timedelta(minutes=15)
    SCHEDULE_EMAIL_SWEEP_INTERVAL: timedelta = timedelta(minutes=1)
    SCHEDULE_JOB_RECOVERY_INTERVAL: timedelta = timedelta(minutes=5)

    # --- External connections and credential encryption (Phase 1B, A6/D15) -----------
    CONNECT_STATE_TTL: timedelta = timedelta(minutes=10)
    # Token lifecycle (Phase 2A, 2A-04): refresh access tokens this long before they expire;
    # refresh at least this often so rotating refresh tokens never lapse; sweep interval.
    TOKEN_REFRESH_MARGIN: timedelta = timedelta(minutes=10)
    TOKEN_KEEPALIVE_INTERVAL: timedelta = timedelta(hours=24)
    SCHEDULE_TOKEN_REFRESH_INTERVAL: timedelta = timedelta(hours=1)
    ENCRYPTION_KEYS: SecretStr = SecretStr(_DEV_ENCRYPTION_KEYS)
    ENCRYPTION_ACTIVE_KEY_VERSION: int = Field(default=1, ge=1)

    # --- Outbound HTTP to externally supplied hosts (A11) ------------------------------
    OUTBOUND_CONNECT_TIMEOUT: timedelta = timedelta(seconds=5)
    OUTBOUND_READ_TIMEOUT: timedelta = timedelta(seconds=20)
    OUTBOUND_MAX_RESPONSE_BYTES: int = Field(default=10_485_760, ge=1024)
    OUTBOUND_MAX_REDIRECTS: int = Field(default=3, ge=0, le=10)
    # Whole-request wall-clock limit (2B-03), on top of the per-read timeout.
    OUTBOUND_REQUEST_TIMEOUT: timedelta = timedelta(seconds=60)
    # Streaming downloads of platform bulk exports (2A-06): overall size and time limits.
    OUTBOUND_MAX_DOWNLOAD_BYTES: int = Field(default=2_147_483_648, ge=1024)
    OUTBOUND_DOWNLOAD_TIMEOUT: timedelta = timedelta(hours=1)

    # --- Shopify (Phase 2A) ------------------------------------------------------------
    # JSON list of Shopify apps: [{"client_id": "...", "client_secret": "...", "shops": ["*"]}].
    # Custom-distribution apps serve one merchant each, so several apps may be configured and
    # "shops" says which store domains each app serves ("*" = any). Unset = Shopify not offered.
    # Secrets come from the environment / secret store only — never committed (D15).
    SHOPIFY_APPS: SecretStr | None = None
    SHOPIFY_API_VERSION: str = Field(default="2026-10", pattern=r"^\d{4}-(01|04|07|10)$")
    SHOPIFY_SCOPES: str = "read_products,read_inventory,read_orders"
    SHOPIFY_INSTALL_MAX_AGE: timedelta = timedelta(minutes=5)
    # Hosts Shopify serves bulk-export files from (signed URLs). Documented example host;
    # to be confirmed on a development store (2A-01). Comma-separated, exact host names.
    SHOPIFY_BULK_DOWNLOAD_HOSTS: str = "storage.googleapis.com"
    # Order history Shopify allows without the ``read_all_orders`` approval (verified).
    SHOPIFY_DEFAULT_ORDER_HISTORY: timedelta = timedelta(days=60)

    # --- WooCommerce (Phase 2B; PHASE_02B_PLAN) ------------------------------------------
    # Offered only when switched on (off until Phase 2B is complete and approved for use).
    WOOCOMMERCE_ENABLED: bool = False
    WOOCOMMERCE_MIN_VERSION: str = Field(default="9.0", pattern=r"^\d{1,3}\.\d{1,3}$")  # Q10a
    WOOCOMMERCE_APP_NAME: str = Field(default="AdVegaX", min_length=1, max_length=64)
    WOOCOMMERCE_RECONCILE_INTERVAL: timedelta = timedelta(minutes=15)  # Q-2B-3

    # --- Google Ads (Phase 3; PHASE_03_PLAN) ---------------------------------------------
    # Offered only when switched on AND the Google Cloud OAuth client and the developer token
    # are configured. The secrets come from the environment / secret store only (D15); in
    # development from the local, untracked settings file — never chat or the repository.
    GOOGLE_ADS_ENABLED: bool = False
    GOOGLE_ADS_CLIENT_ID: str | None = None
    GOOGLE_ADS_CLIENT_SECRET: SecretStr | None = None
    GOOGLE_ADS_DEVELOPER_TOKEN: SecretStr | None = None
    # The newest major version when coding started (Q-3-1); upgraded yearly.
    GOOGLE_ADS_API_VERSION: str = Field(default="v25", pattern=r"^v[0-9]{2,3}$")

    # --- Meta Ads (Phase 4, read-only; PHASE_04_PLAN) ----------------------------------
    # Offered only when switched on AND the Meta app and its Facebook Login for Business
    # configuration are set. The app secret comes from the environment / secret store only
    # (D15); in development from the local, untracked settings file — never chat or the repo.
    META_ADS_ENABLED: bool = False
    META_APP_ID: str | None = Field(default=None, pattern=r"^[0-9]{5,20}$")
    META_APP_SECRET: SecretStr | None = None
    META_LOGIN_CONFIG_ID: str | None = Field(default=None, pattern=r"^[0-9]{5,20}$")
    META_API_VERSION: str = Field(default="v26.0", pattern=r"^v[0-9]{2,3}\.0$")  # Q-4-1

    # --- Google Analytics 4 (Phase 5, read-only; PHASE_05_PLAN) -------------------------
    # Offered only when switched on AND the Google Cloud OAuth client is configured. It is
    # the **same** OAuth client as Google Ads (GOOGLE_ADS_CLIENT_ID / _SECRET, Q-5-2): one
    # consent screen and one verification; each product is still its own connection with its
    # own permission (``analytics.readonly``). No developer token is needed.
    GOOGLE_ANALYTICS_ENABLED: bool = False
    # Data API and Admin API version (Q-5-1): the stable ``v1beta``; alpha is never used.
    GOOGLE_ANALYTICS_API_VERSION: str = Field(default="v1beta", pattern=r"^v1(beta)?$")

    # --- Analytics import (Phase 5, 5-05; PHASE_05_PLAN §9) ------------------------------
    ANALYTICS_HISTORY_WINDOW: timedelta = timedelta(days=395)  # 13 months on first link
    # Re-read windows (the schedule itself is task 5-06): 3-hour today + yesterday, nightly
    # 14 days (Google's late data and attribution changes, Q-5-6), weekly 90 days.
    ANALYTICS_QUICK_WINDOW: timedelta = timedelta(days=2)
    ANALYTICS_NIGHTLY_WINDOW: timedelta = timedelta(days=14)
    ANALYTICS_WEEKLY_WINDOW: timedelta = timedelta(days=90)
    ANALYTICS_CHAIN_STALE_AFTER: timedelta = timedelta(hours=6)
    # The schedule (5-06): each imported property is due 3 hours after its last 3-hour run,
    # nightly after 24 hours and weekly after 7 days; the scheduler looks every tick.
    ANALYTICS_QUICK_INTERVAL: timedelta = timedelta(hours=3)
    ANALYTICS_NIGHTLY_INTERVAL: timedelta = timedelta(hours=24)
    ANALYTICS_WEEKLY_INTERVAL: timedelta = timedelta(days=7)
    SCHEDULE_ANALYTICS_SYNC_TICK: timedelta = timedelta(minutes=5)
    # Pacing from Google's remaining allowance per property (Q-5-7): below the slow share of
    # the hour's or day's tokens each step waits ANALYTICS_QUOTA_SLOW_WAIT; below the pause
    # share the property's run pauses until the next full hour, then continues by itself.
    ANALYTICS_QUOTA_SLOW_SHARE: float = Field(default=0.25, gt=0, le=1)
    ANALYTICS_QUOTA_PAUSE_SHARE: float = Field(default=0.10, gt=0, le=1)
    ANALYTICS_QUOTA_SLOW_WAIT: timedelta = timedelta(minutes=2)
    # Google says a property's quota is used up without saying for how long: it waits this.
    ANALYTICS_PROPERTY_BUSY_WAIT: timedelta = timedelta(minutes=15)
    # The source / medium / campaign view keeps this many values a day (most sessions first);
    # the rest are added into one "(other)" row, marked, with users left unknown (Q-5-5).
    ANALYTICS_SOURCE_ROWS_PER_DAY: int = Field(default=500, ge=10, le=10_000)
    # The last days are shown as "still being processed by Google" (Q-5-6, 5-07).
    ANALYTICS_PROCESSING_DAYS: int = Field(default=3, ge=0, le=30)

    # --- Exchange rates (Phase 6, 6-03; PHASE_06_PLAN Q-6-3) -----------------------------
    # The ECB's daily reference rates and Nepal Rastra Bank's NPR rates, read by a scheduled
    # task. Off until switched on (the deployment must allow the two public addresses).
    FX_ENABLED: bool = False
    FX_HISTORY_WINDOW: timedelta = timedelta(days=400)  # the first read: 13 months and margin
    FX_REFRESH_DAYS: timedelta = timedelta(days=10)  # later reads go back this far
    FX_FETCH_SLICE: timedelta = timedelta(days=92)  # days per request
    # A weekend or holiday uses the last published rate, at most this old; else "no rate".
    FX_MAX_STALE_DAYS: timedelta = timedelta(days=7)
    SCHEDULE_FX_INTERVAL: timedelta = timedelta(hours=6)

    # --- AI campaign planner (Phase 8, PHASE_08_PLAN Q-8-1 … Q-8-8; A26) ---------------------
    # Off until the deployment has an API key. The key lives only in the settings file.
    AI_ENABLED: bool = False
    ANTHROPIC_API_KEY: SecretStr | None = None
    AI_MODEL: str = Field(default="claude-sonnet-5-5", pattern=r"^[a-z0-9][a-z0-9.\-]{2,63}$")
    AI_MAX_OUTPUT_TOKENS: int = Field(default=4000, ge=256, le=32000)
    AI_TIMEOUT: timedelta = timedelta(seconds=60)
    AI_DAILY_RUNS: int = Field(default=20, ge=1, le=10000)  # per organization and UTC day
    AI_MAX_RETRIES: int = Field(default=1, ge=0, le=2)  # an invalid answer is retried this often
    # USD per million tokens, for the usage estimate; None = no estimate is shown.
    AI_PRICE_INPUT_PER_MTOK: Decimal | None = None
    AI_PRICE_OUTPUT_PER_MTOK: Decimal | None = None
    # What the planner shows the model (8-03): the last N complete days, and a recent window.
    PLANNER_CONTEXT_DAYS: int = Field(default=90, ge=14, le=400)
    PLANNER_RECENT_DAYS: int = Field(default=30, ge=7, le=90)
    # Strategy checks (8-04): a target may be at most this many times better or worse than the
    # organization's own history; each platform's minimum daily budget, in US dollars (converted
    # to the reporting currency with the latest rate). The platforms' minimums vary by currency
    # and bidding; these are AdVegaX's floor, checked against the platforms in Step 0.
    PLANNER_TARGET_FACTOR: Decimal = Field(default=Decimal(3), gt=1, le=20)
    PLANNER_MIN_DAILY_GOOGLE_ADS_USD: Decimal = Field(default=Decimal(1), ge=0)
    PLANNER_MIN_DAILY_META_ADS_USD: Decimal = Field(default=Decimal(1), ge=0)

    # --- Creative engine (Phase 9; PHASE_09_PLAN §2, A27) ------------------------------
    # Drafts per platform and their size (Q-9-3); the platforms' text limits (Q-9-4) live in
    # app/domains/creative/specs.py and are checked on every save.
    CREATIVE_CONCEPTS: int = Field(default=3, ge=1, le=5)
    CREATIVE_GOOGLE_HEADLINES: int = Field(default=10, ge=3, le=15)
    CREATIVE_GOOGLE_DESCRIPTIONS: int = Field(default=4, ge=2, le=4)
    CREATIVE_META_PRIMARY_TEXTS: int = Field(default=3, ge=1, le=5)
    CREATIVE_META_HEADLINES: int = Field(default=3, ge=1, le=5)
    CREATIVE_META_DESCRIPTIONS: int = Field(default=2, ge=1, le=5)
    # Uploaded images (Q-9-8): checked by decoding, re-encoded without metadata.
    ASSET_MAX_BYTES: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    ASSET_MIN_SIDE: int = Field(default=600, ge=1, le=4000)
    ASSET_MAX_PIXELS: int = Field(default=40_000_000, ge=1_000_000, le=200_000_000)
    # Where images are kept (Q-9-9): a local folder (development, tests, one server) or an
    # S3-compatible store chosen at the production-readiness gate. Keys only in settings.
    STORAGE_BACKEND: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_ROOT: str = "var/storage"
    S3_BUCKET: str | None = None
    S3_ENDPOINT_URL: str | None = None  # None: AWS; R2 / B2 / MinIO give their own
    S3_REGION: str | None = None
    S3_ACCESS_KEY_ID: SecretStr | None = None
    S3_SECRET_ACCESS_KEY: SecretStr | None = None

    # --- Advertising import (Phase 3; PHASE_03_PLAN §9) ---------------------------------
    ADS_HISTORY_WINDOW: timedelta = timedelta(days=395)  # 13 months on first link (Q-3-6)
    # Ongoing sync (Q-3-5, task 3-07): every 3 hours structure + today and yesterday; nightly
    # the last 30 days; weekly the last 90 days; each re-read replaces the days it covers.
    ADS_QUICK_INTERVAL: timedelta = timedelta(hours=3)
    ADS_QUICK_WINDOW: timedelta = timedelta(days=2)
    ADS_NIGHTLY_INTERVAL: timedelta = timedelta(hours=24)
    ADS_NIGHTLY_WINDOW: timedelta = timedelta(days=30)
    ADS_WEEKLY_INTERVAL: timedelta = timedelta(days=7)
    ADS_WEEKLY_WINDOW: timedelta = timedelta(days=90)
    ADS_CHAIN_STALE_AFTER: timedelta = timedelta(hours=6)
    SCHEDULE_ADS_SYNC_TICK: timedelta = timedelta(minutes=5)
    # The last days are shown as "may still change" (3-08): Google is not settled on them.
    ADS_UNSETTLED_DAYS: int = Field(default=3, ge=0, le=30)
    # The platform allowance shared by every customer (Q-3-2): Google Ads operations a day per
    # developer token (Explorer 2,880; Basic 15,000). At ADS_QUOTA_DEFER_SHARE of it the
    # nightly and weekly re-reads wait; at 100 % every step waits ADS_QUOTA_WAIT and retries.
    GOOGLE_ADS_DAILY_OPERATIONS: int = Field(default=2880, ge=1)
    ADS_QUOTA_WINDOW: timedelta = timedelta(hours=24)
    ADS_QUOTA_DEFER_SHARE: float = Field(default=0.8, gt=0, le=1)
    ADS_QUOTA_WAIT: timedelta = timedelta(minutes=15)
    # A platform that asks one account to wait without saying for how long (Meta, Q-4-12):
    # that account's run pauses this long, then continues by itself.
    ADS_ACCOUNT_BUSY_WAIT: timedelta = timedelta(minutes=10)
    # Sign-ins that cannot be renewed (Meta's ~60-day token): warnings this many days before
    # the end (Q-4-2), largest first.
    SIGN_IN_WARNING_DAYS: tuple[int, ...] = (14, 3)

    # --- Commerce import (Phase 2A, 2A-06; PHASE_02A_PLAN §9) ----------------------------
    # Longest order history imported (13 months, Q9); the platform may allow less (Shopify:
    # 60 days without ``read_all_orders``).
    COMMERCE_HISTORY_WINDOW: timedelta = timedelta(days=395)
    COMMERCE_BULK_POLL_INTERVAL: timedelta = timedelta(seconds=30)
    COMMERCE_IMPORT_BATCH_SIZE: int = Field(default=500, ge=1, le=5000)
    # Paged imports (2B-02): pause between pages (0 = next page at once; the per-store request
    # limiter still applies). Must not be negative.
    COMMERCE_PAGE_INTERVAL: timedelta = timedelta(seconds=0)
    # Reconciliation (2A-07): hourly changes since the last run (minus an overlap), nightly a
    # deeper check of the catalogue and recent orders. A chain silent for longer than
    # COMMERCE_CHAIN_STALE_AFTER is considered dead and may be restarted.
    SCHEDULE_COMMERCE_RECONCILE_INTERVAL: timedelta = timedelta(hours=1)
    # How often the scheduler looks for stores due a check (2B-06). Each store is checked at
    # its platform's interval: the default above, WooCommerce every
    # WOOCOMMERCE_RECONCILE_INTERVAL (no webhooks, Q-2B-3).
    SCHEDULE_COMMERCE_RECONCILE_TICK: timedelta = timedelta(minutes=5)
    SCHEDULE_COMMERCE_DEEP_INTERVAL: timedelta = timedelta(hours=24)
    COMMERCE_RECONCILE_OVERLAP: timedelta = timedelta(minutes=10)
    COMMERCE_DEEP_WINDOW: timedelta = timedelta(days=30)
    COMMERCE_CHAIN_STALE_AFTER: timedelta = timedelta(hours=6)
    # Webhook bursts for one object are coalesced into one fetch within this window.
    COMMERCE_FETCH_COALESCE: timedelta = timedelta(minutes=5)
    # Longest period one daily-figures request may cover (2A-09).
    METRICS_MAX_DAYS: int = Field(default=400, ge=1, le=1000)
    # Funnel drop-off findings (Phase 7, Q-7-7): a same-source step at least this share lower
    # than the previous equal period and below its own average over the baseline days before
    # the period, with at least this many events in its earlier stage.
    FUNNEL_DROP_SHARE: Decimal = Field(default=Decimal("0.25"), gt=0, lt=1)
    FUNNEL_MIN_EVENTS: int = Field(default=200, ge=1)
    FUNNEL_BASELINE_DAYS: int = Field(default=90, ge=7, le=365)

    # --- Webhook intake (Phase 2A, 2A-05; PHASE_02A_PLAN §7) ----------------------------
    # Deliveries triggered longer ago than this are refused (replay limit). Shopify retries
    # for up to 4 hours, so this must stay above that.
    WEBHOOK_MAX_AGE: timedelta = timedelta(hours=6)
    WEBHOOK_CLOCK_SKEW: timedelta = timedelta(minutes=5)
    WEBHOOK_RETENTION: timedelta = timedelta(days=30)  # intake metadata is deleted after this
    SCHEDULE_WEBHOOK_PURGE_INTERVAL: timedelta = timedelta(hours=6)

    @field_validator("CORS_ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate(self) -> Settings:
        durations = {
            "SESSION_IDLE_TIMEOUT": self.SESSION_IDLE_TIMEOUT,
            "SESSION_ABSOLUTE_TIMEOUT": self.SESSION_ABSOLUTE_TIMEOUT,
            "SESSION_TOUCH_INTERVAL": self.SESSION_TOUCH_INTERVAL,
            "EMAIL_VERIFICATION_TTL": self.EMAIL_VERIFICATION_TTL,
            "PASSWORD_RESET_TTL": self.PASSWORD_RESET_TTL,
            "INVITATION_TTL": self.INVITATION_TTL,
            "EMAIL_RETRY_BASE_DELAY": self.EMAIL_RETRY_BASE_DELAY,
            "JOB_RETRY_BASE_DELAY": self.JOB_RETRY_BASE_DELAY,
            "JOB_RETRY_MAX_DELAY": self.JOB_RETRY_MAX_DELAY,
            "JOB_STUCK_AFTER": self.JOB_STUCK_AFTER,
            "SCHEDULE_EMAIL_SWEEP_INTERVAL": self.SCHEDULE_EMAIL_SWEEP_INTERVAL,
            "SCHEDULE_JOB_RECOVERY_INTERVAL": self.SCHEDULE_JOB_RECOVERY_INTERVAL,
            "CONNECT_STATE_TTL": self.CONNECT_STATE_TTL,
            "OUTBOUND_CONNECT_TIMEOUT": self.OUTBOUND_CONNECT_TIMEOUT,
            "OUTBOUND_READ_TIMEOUT": self.OUTBOUND_READ_TIMEOUT,
            "OUTBOUND_REQUEST_TIMEOUT": self.OUTBOUND_REQUEST_TIMEOUT,
            "SHOPIFY_INSTALL_MAX_AGE": self.SHOPIFY_INSTALL_MAX_AGE,
            "TOKEN_REFRESH_MARGIN": self.TOKEN_REFRESH_MARGIN,
            "TOKEN_KEEPALIVE_INTERVAL": self.TOKEN_KEEPALIVE_INTERVAL,
            "SCHEDULE_TOKEN_REFRESH_INTERVAL": self.SCHEDULE_TOKEN_REFRESH_INTERVAL,
            "OUTBOUND_DOWNLOAD_TIMEOUT": self.OUTBOUND_DOWNLOAD_TIMEOUT,
            "COMMERCE_HISTORY_WINDOW": self.COMMERCE_HISTORY_WINDOW,
            "ADS_HISTORY_WINDOW": self.ADS_HISTORY_WINDOW,
            "ADS_QUICK_INTERVAL": self.ADS_QUICK_INTERVAL,
            "ADS_QUICK_WINDOW": self.ADS_QUICK_WINDOW,
            "ADS_NIGHTLY_INTERVAL": self.ADS_NIGHTLY_INTERVAL,
            "ADS_NIGHTLY_WINDOW": self.ADS_NIGHTLY_WINDOW,
            "ADS_WEEKLY_INTERVAL": self.ADS_WEEKLY_INTERVAL,
            "ADS_WEEKLY_WINDOW": self.ADS_WEEKLY_WINDOW,
            "ADS_CHAIN_STALE_AFTER": self.ADS_CHAIN_STALE_AFTER,
            "SCHEDULE_ADS_SYNC_TICK": self.SCHEDULE_ADS_SYNC_TICK,
            "ADS_QUOTA_WINDOW": self.ADS_QUOTA_WINDOW,
            "ADS_QUOTA_WAIT": self.ADS_QUOTA_WAIT,
            "ADS_ACCOUNT_BUSY_WAIT": self.ADS_ACCOUNT_BUSY_WAIT,
            "ANALYTICS_HISTORY_WINDOW": self.ANALYTICS_HISTORY_WINDOW,
            "FX_HISTORY_WINDOW": self.FX_HISTORY_WINDOW,
            "FX_REFRESH_DAYS": self.FX_REFRESH_DAYS,
            "FX_FETCH_SLICE": self.FX_FETCH_SLICE,
            "FX_MAX_STALE_DAYS": self.FX_MAX_STALE_DAYS,
            "SCHEDULE_FX_INTERVAL": self.SCHEDULE_FX_INTERVAL,
            "AI_TIMEOUT": self.AI_TIMEOUT,
            "ANALYTICS_QUICK_WINDOW": self.ANALYTICS_QUICK_WINDOW,
            "ANALYTICS_NIGHTLY_WINDOW": self.ANALYTICS_NIGHTLY_WINDOW,
            "ANALYTICS_WEEKLY_WINDOW": self.ANALYTICS_WEEKLY_WINDOW,
            "ANALYTICS_CHAIN_STALE_AFTER": self.ANALYTICS_CHAIN_STALE_AFTER,
            "ANALYTICS_PROPERTY_BUSY_WAIT": self.ANALYTICS_PROPERTY_BUSY_WAIT,
            "ANALYTICS_QUICK_INTERVAL": self.ANALYTICS_QUICK_INTERVAL,
            "ANALYTICS_NIGHTLY_INTERVAL": self.ANALYTICS_NIGHTLY_INTERVAL,
            "ANALYTICS_WEEKLY_INTERVAL": self.ANALYTICS_WEEKLY_INTERVAL,
            "SCHEDULE_ANALYTICS_SYNC_TICK": self.SCHEDULE_ANALYTICS_SYNC_TICK,
            "ANALYTICS_QUOTA_SLOW_WAIT": self.ANALYTICS_QUOTA_SLOW_WAIT,
            "SHOPIFY_DEFAULT_ORDER_HISTORY": self.SHOPIFY_DEFAULT_ORDER_HISTORY,
            "SCHEDULE_COMMERCE_RECONCILE_INTERVAL": self.SCHEDULE_COMMERCE_RECONCILE_INTERVAL,
            "SCHEDULE_COMMERCE_DEEP_INTERVAL": self.SCHEDULE_COMMERCE_DEEP_INTERVAL,
            "SCHEDULE_COMMERCE_RECONCILE_TICK": self.SCHEDULE_COMMERCE_RECONCILE_TICK,
            "WOOCOMMERCE_RECONCILE_INTERVAL": self.WOOCOMMERCE_RECONCILE_INTERVAL,
            "COMMERCE_RECONCILE_OVERLAP": self.COMMERCE_RECONCILE_OVERLAP,
            "COMMERCE_DEEP_WINDOW": self.COMMERCE_DEEP_WINDOW,
            "COMMERCE_CHAIN_STALE_AFTER": self.COMMERCE_CHAIN_STALE_AFTER,
            "COMMERCE_FETCH_COALESCE": self.COMMERCE_FETCH_COALESCE,
            "COMMERCE_BULK_POLL_INTERVAL": self.COMMERCE_BULK_POLL_INTERVAL,
            "WEBHOOK_MAX_AGE": self.WEBHOOK_MAX_AGE,
            "WEBHOOK_CLOCK_SKEW": self.WEBHOOK_CLOCK_SKEW,
            "WEBHOOK_RETENTION": self.WEBHOOK_RETENTION,
            "SCHEDULE_WEBHOOK_PURGE_INTERVAL": self.SCHEDULE_WEBHOOK_PURGE_INTERVAL,
        }
        for name, value in durations.items():
            if value <= timedelta(0):
                raise ValueError(f"{name} must be a positive duration")
        warnings = self.SIGN_IN_WARNING_DAYS
        if (
            not warnings
            or any(not 1 <= d <= 60 for d in warnings)
            or list(warnings) != sorted(set(warnings), reverse=True)
        ):
            raise ValueError("SIGN_IN_WARNING_DAYS must be distinct days (1-60), largest first")
        if timedelta(0) > self.COMMERCE_PAGE_INTERVAL:
            raise ValueError("COMMERCE_PAGE_INTERVAL must not be negative")
        if self.SESSION_IDLE_TIMEOUT > self.SESSION_ABSOLUTE_TIMEOUT:
            raise ValueError("SESSION_IDLE_TIMEOUT must not exceed SESSION_ABSOLUTE_TIMEOUT")
        if self.JOB_RETRY_BASE_DELAY > self.JOB_RETRY_MAX_DELAY:
            raise ValueError("JOB_RETRY_BASE_DELAY must not exceed JOB_RETRY_MAX_DELAY")
        from app.core.security.encryption import parse_key_ring  # local import: avoids a cycle

        ring = parse_key_ring(self.ENCRYPTION_KEYS.get_secret_value())
        if self.ENCRYPTION_ACTIVE_KEY_VERSION not in ring:
            raise ValueError("ENCRYPTION_ACTIVE_KEY_VERSION must be present in ENCRYPTION_KEYS")
        if self.PASSWORD_MIN_LENGTH > self.PASSWORD_MAX_LENGTH:
            raise ValueError("PASSWORD_MIN_LENGTH must not exceed PASSWORD_MAX_LENGTH")
        if self.STORAGE_BACKEND == "s3" and not (
            self.S3_BUCKET and self.S3_ACCESS_KEY_ID and self.S3_SECRET_ACCESS_KEY
        ):
            raise ValueError(
                "STORAGE_BACKEND=s3 needs S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY"
            )
        if self.is_deployed:
            self._validate_deployed()
        return self

    def _validate_deployed(self) -> None:
        problems: list[str] = []
        secret = self.SECRET_KEY.get_secret_value()
        if secret == _INSECURE_DEFAULT_SECRET or len(secret) < 32:
            problems.append("SECRET_KEY must be set to a random value of at least 32 characters")
        if not self.COOKIE_SECURE:
            problems.append("COOKIE_SECURE must be true")
        if not self.SESSION_COOKIE_NAME.startswith("__Host-"):
            problems.append("SESSION_COOKIE_NAME must use the __Host- prefix")
        if not self.CSRF_COOKIE_NAME.startswith("__Host-"):
            problems.append("CSRF_COOKIE_NAME must use the __Host- prefix")
        if not self.CORS_ALLOWED_ORIGINS:
            problems.append("CORS_ALLOWED_ORIGINS must not be empty")
        if any(o == "*" or not o.startswith("https://") for o in self.CORS_ALLOWED_ORIGINS):
            problems.append("CORS_ALLOWED_ORIGINS must list explicit https:// origins (no '*')")
        if not self.APP_BASE_URL.startswith("https://"):
            problems.append("APP_BASE_URL must use https://")
        if not self.API_BASE_URL.startswith("https://"):
            problems.append("API_BASE_URL must use https://")
        if self.ENCRYPTION_KEYS.get_secret_value() == _DEV_ENCRYPTION_KEYS:
            problems.append("ENCRYPTION_KEYS must be set from the secret store (not the dev key)")
        if self.EMAIL_BACKEND is not EmailBackend.SMTP:
            problems.append("EMAIL_BACKEND must be smtp")
        if self.CELERY_TASK_ALWAYS_EAGER:
            problems.append("CELERY_TASK_ALWAYS_EAGER must be false")
        if problems:
            raise ValueError(
                "Insecure configuration for deployed environment: " + "; ".join(problems)
            )

    @property
    def is_deployed(self) -> bool:
        return self.ENVIRONMENT in {Environment.STAGING, Environment.PRODUCTION}


@lru_cache
def get_settings() -> Settings:
    return Settings()
