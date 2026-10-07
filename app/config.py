"""Runtime configuration, read once from environment variables (and `.env`)."""

import os
import pathlib
import secrets
from dataclasses import dataclass, field

BASE_DIR = pathlib.Path(__file__).resolve().parent.parent


def _load_dotenv(path: pathlib.Path) -> None:
    """Minimal `.env` loader so local runs need no extra dependency."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    # Empty values (e.g. "DATABASE_URL=" in .env) fall back to the default.
    return os.environ.get(name, "").strip() or default


def _database_url() -> str:
    url = _env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'app.db'}")
    # Render/Heroku hand out postgres:// URLs; SQLAlchemy wants an explicit driver.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@dataclass(frozen=True)
class Settings:
    app_name: str = field(default_factory=lambda: _env("APP_NAME", "Resumora"))
    base_url: str = field(
        default_factory=lambda: (
            _env("BASE_URL") or _env("RENDER_EXTERNAL_URL") or "http://localhost:8000"
        ).rstrip("/")
    )
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY"))
    database_url: str = field(default_factory=_database_url)

    anthropic_api_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-opus-5"))

    stripe_secret_key: str = field(default_factory=lambda: _env("STRIPE_SECRET_KEY"))
    stripe_webhook_secret: str = field(default_factory=lambda: _env("STRIPE_WEBHOOK_SECRET"))
    # STRIPE_PRICE_ID is accepted as an alias for the Pro price (older configs).
    stripe_price_pro: str = field(
        default_factory=lambda: _env("STRIPE_PRICE_PRO") or _env("STRIPE_PRICE_ID"))
    stripe_price_elite: str = field(default_factory=lambda: _env("STRIPE_PRICE_ELITE"))

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def billing_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_price_pro)

    def price_for(self, plan: str) -> str:
        return {"pro": self.stripe_price_pro, "elite": self.stripe_price_elite}.get(plan, "")

    def plan_for_price(self, price_id: str | None) -> str | None:
        if price_id and price_id == self.stripe_price_elite:
            return "elite"
        if price_id and price_id == self.stripe_price_pro:
            return "pro"
        return None


def load_settings() -> Settings:
    s = Settings()
    if not s.secret_key:
        if s.is_production:
            raise RuntimeError("SECRET_KEY must be set in production.")
        # Dev only: a per-process key means sessions reset on restart.
        object.__setattr__(s, "secret_key", secrets.token_urlsafe(32))
    return s


settings = load_settings()
