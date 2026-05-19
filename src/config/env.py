"""
Typed environment configuration using pydantic-settings.
Required vars fail fast at import time if missing.
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOCAL_PREFIXES = ("http://localhost", "http://127.0.0.1")


def _require_https(value: str, name: str) -> str:
    """Reject plain-http URLs unless they point to localhost (dev only)."""
    if value and not value.startswith("https://") and not value.startswith(_LOCAL_PREFIXES):
        raise ValueError(
            f"{name} must use https:// in non-local environments. "
            f"Got: {value!r}"
        )
    return value


class Settings(BaseSettings):
    KONG_URL: str
    KONG_ANONYMOUS_TOKEN: str
    KONG_LOGGEDIN_TOKEN: str = ""                # Portal's KONG_LOGGEDIN_FALLBACK_TOKEN
    KONG_LOGGEDIN_DEVICE_REGISTER_TOKEN: str = ""  # Portal's KONG_LOGGEDIN_DEVICE_REGISTER_TOKEN — used to register a portal_loggedin consumer token at startup
    SUNBIRD_CHANNEL_ID: str = ""
    APP_ID: str = "local.sunbird.mcp"
    MCP_PORT: int = 3002
    PORTAL_URL: str = ""  # e.g. https://test.sunbirded.org — used to build course consume URLs

    # Keycloak direct auth — required only when tool_login is used
    KEYCLOAK_ISSUER_URL: str = ""     # e.g. https://host/auth/realms/sunbird
    KEYCLOAK_CLIENT_ID: str = ""      # same as portal's KEYCLOAK_ANDROID_CLIENT_ID
    KEYCLOAK_CLIENT_SECRET: str = ""  # leave empty for public clients

    @field_validator("KONG_URL")
    @classmethod
    def kong_url_must_be_https(cls, v: str) -> str:
        return _require_https(v, "KONG_URL")

    @field_validator("KEYCLOAK_ISSUER_URL")
    @classmethod
    def keycloak_url_must_be_https(cls, v: str) -> str:
        return _require_https(v, "KEYCLOAK_ISSUER_URL")

    @field_validator("PORTAL_URL")
    @classmethod
    def portal_url_must_be_https(cls, v: str) -> str:
        return _require_https(v, "PORTAL_URL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


env = Settings()
