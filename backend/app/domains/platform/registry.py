"""What the Admin portal may change (Phase 16, Q-16-4; A35).

Only these settings; each must exist on ``Settings``. ``secret``: stored encrypted and never
shown again (only "set ••••1234"); ``text``: an identifier, shown; ``switch``: on or off.
Everything applies the next time AdVegaX starts (the portal says so).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.settings import Settings


@dataclass(frozen=True)
class Entry:
    name: str
    label: str
    group: str
    kind: str  # secret | text | switch


ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="SHOPIFY_APPS",
        label="Shopify apps (JSON from the Partner dashboard)",
        group="Shopify",
        kind="secret",
    ),
    Entry(
        name="WOOCOMMERCE_ENABLED",
        label="Offer WooCommerce stores",
        group="WooCommerce",
        kind="switch",
    ),
    Entry(name="GOOGLE_ADS_ENABLED", label="Offer Google Ads", group="Google", kind="switch"),
    Entry(
        name="GOOGLE_ANALYTICS_ENABLED",
        label="Offer Google Analytics",
        group="Google",
        kind="switch",
    ),
    Entry(name="GOOGLE_ADS_CLIENT_ID", label="OAuth client ID", group="Google", kind="text"),
    Entry(
        name="GOOGLE_ADS_CLIENT_SECRET", label="OAuth client secret", group="Google", kind="secret"
    ),
    Entry(
        name="GOOGLE_ADS_DEVELOPER_TOKEN",
        label="Google Ads developer token",
        group="Google",
        kind="secret",
    ),
    Entry(name="META_ADS_ENABLED", label="Offer Meta ads", group="Meta", kind="switch"),
    Entry(name="META_APP_ID", label="App ID", group="Meta", kind="text"),
    Entry(name="META_APP_SECRET", label="App secret", group="Meta", kind="secret"),
    Entry(
        name="META_LOGIN_CONFIG_ID",
        label="Login configuration ID (read)",
        group="Meta",
        kind="text",
    ),
    Entry(
        name="META_WRITE_LOGIN_CONFIG_ID",
        label="Login configuration ID (changes)",
        group="Meta",
        kind="text",
    ),
    Entry(name="AI_ENABLED", label="AI features", group="AI (Anthropic)", kind="switch"),
    Entry(
        name="ANTHROPIC_API_KEY", label="Anthropic API key", group="AI (Anthropic)", kind="secret"
    ),
    Entry(name="BILLING_ENABLED", label="Charge for plans", group="Stripe", kind="switch"),
    Entry(name="STRIPE_SECRET_KEY", label="Secret key", group="Stripe", kind="secret"),
    Entry(
        name="STRIPE_WEBHOOK_SECRET", label="Webhook signing secret", group="Stripe", kind="secret"
    ),
    Entry(name="STRIPE_API_VERSION", label="API version", group="Stripe", kind="text"),
    Entry(name="SMTP_HOST", label="SMTP server", group="Email (Amazon SES)", kind="text"),
    Entry(name="SMTP_USERNAME", label="SMTP user name", group="Email (Amazon SES)", kind="text"),
    Entry(name="SMTP_PASSWORD", label="SMTP password", group="Email (Amazon SES)", kind="secret"),
    Entry(
        name="EMAIL_FROM",
        label="Sender, e.g. AdVegaX <no-reply@yourdomain>",
        group="Email (Amazon SES)",
        kind="text",
    ),
    Entry(name="FX_ENABLED", label="Read exchange rates", group="Features", kind="switch"),
    Entry(name="ACTIONS_ENABLED", label="Changes to ad accounts", group="Features", kind="switch"),
    Entry(name="OPTIMIZATION_ENABLED", label="Recommendations", group="Features", kind="switch"),
    Entry(name="AUTOPILOT_ENABLED", label="Autopilot", group="Features", kind="switch"),
    Entry(name="AGENCY_ENABLED", label="Agency mode", group="Features", kind="switch"),
    Entry(
        name="RETENTION_ENABLED",
        label="Delete removed data after 90 days",
        group="Features",
        kind="switch",
    ),
)
BY_NAME = {e.name: e for e in ENTRIES}

missing = [e.name for e in ENTRIES if e.name not in Settings.model_fields]
if missing:  # pragma: no cover - caught by the tests
    raise RuntimeError(f"unknown settings in the Admin registry: {missing}")
