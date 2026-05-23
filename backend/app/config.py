from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://mneme:mneme@localhost:5433/mneme"
    redis_url: str = "redis://localhost:6380/0"

    # default embedding provider for tenants/agents that don't override
    embedding_provider: str = "fake"  # "fake" | "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    openai_api_key: str = ""

    # auth + secrets
    jwt_secret: str = "dev-jwt-secret-change-me"
    jwt_alg: str = "HS256"
    jwt_ttl_hours: int = 24 * 7
    # Optional: if blank, a Fernet key is derived from jwt_secret (dev only).
    # Generate prod value: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    fernet_key: str = ""

    seed_on_boot: bool = False

    # Razorpay billing (test mode by default)
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # Comma-separated browser origins allowed to call the API. "*" = allow all (dev default).
    # In production set this to your dashboard origin, e.g. "https://mneme.example.com".
    cors_origins: str = "*"

    # Comma-separated operator/admin emails. These accounts can access /admin
    # (see all users, subscriptions, enable/disable accounts).
    admin_emails: str = "demo@mneme.dev"

    # Open-core licensing: a self-hosted instance with no Business license allows
    # up to this many accounts. A signed license (MNEME_LICENSE_KEY) lifts the cap.
    community_max_users: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def get_fernet_key() -> bytes:
    """Returns a valid Fernet key (32-byte url-safe base64)."""
    import base64
    import hashlib
    if settings.fernet_key:
        return settings.fernet_key.encode()
    # derive from jwt_secret deterministically (dev only)
    digest = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)
