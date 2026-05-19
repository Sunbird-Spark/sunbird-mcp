"""
Async HTTP client layer for Sunbird Kong gateway and Keycloak auth.

Public surface:
  kong_get / kong_post              — anonymous requests
  authenticated_get / post / patch  — requests with a logged-in user token
  keycloak_refresh                  — Keycloak refresh-token grant
  decode_jwt_payload                — decode JWT claims without signature verification
  extract_sunbird_user_id           — extract bare UUID from a Keycloak JWT
  resolve_channel_id                — called once at server startup
  resolve_loggedin_kong_token       — called once at server startup; registers portal_loggedin consumer
"""
from __future__ import annotations

import base64
import binascii
import json
import uuid
from urllib.parse import urlencode

import httpx

from config.env import env

def _portal_base() -> str:
    """Return the portal base URL.
    Uses PORTAL_URL if set; otherwise derives the origin from KONG_URL (strips path)."""
    if env.PORTAL_URL:
        return env.PORTAL_URL.rstrip("/")
    # KONG_URL is always required — derive portal origin from it
    from urllib.parse import urlparse
    parsed = urlparse(env.KONG_URL)
    return f"{parsed.scheme}://{parsed.netloc}"


def build_course_url(course_id: str) -> str | None:
    """Return portal course URL: {portal_base}/collection/{course_id}."""
    base = _portal_base()
    if not base or not course_id:
        return None
    return f"{base}/collection/{course_id}"


def build_consume_url(course_id: str, batch_id: str, content_id: str) -> str | None:
    """Return deep-link consume URL for a specific lesson, or None if any ID is missing."""
    base = _portal_base()
    if not base or not course_id or not batch_id or not content_id:
        return None
    return f"{base}/collection/{course_id}/batch/{batch_id}/content/{content_id}"


# Module-level state
_channel_id: str = ""
_loggedin_kong_token: str = ""   # registered portal_loggedin consumer token
_client: httpx.AsyncClient | None = None


class SunbirdApiError(Exception):
    """Raised when Kong returns a non-2xx response."""

    def __init__(self, status_code: int, response_code: str, message: str) -> None:
        self.status_code = status_code
        self.response_code = response_code
        super().__init__(message)


class KeycloakAuthError(Exception):
    """Raised when Keycloak rejects a login or refresh request."""

    def __init__(self, error: str, message: str, status_code: int = 401) -> None:
        self.error = error
        self.status_code = status_code
        super().__init__(message)


class InvalidTokenError(ValueError):
    """Raised when a token string is not a structurally valid JWT."""


# ── Anonymous Kong client ─────────────────────────────────────────────────────

def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=env.KONG_URL,
            headers={
                "X-App-Id": env.APP_ID,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
    return _client


def _anon_headers() -> dict[str, str]:
    """Anonymous auth headers — read from env on every call so token rotation works without restart."""
    return {
        "Authorization": f"Bearer {env.KONG_ANONYMOUS_TOKEN}",
        **_channel_header(),
    }


def _channel_header() -> dict[str, str]:
    return {"X-Channel-Id": _channel_id} if _channel_id else {}


async def resolve_channel_id() -> None:
    """Called once at server startup to populate the module-level channel ID."""
    global _channel_id

    if env.SUNBIRD_CHANNEL_ID:
        _channel_id = env.SUNBIRD_CHANNEL_ID
        print(f"[sunbird-mcp] Channel ID loaded from env: {_channel_id}")
        return

    client = _get_client()
    try:
        resp = await client.post(
            "/org/v2/search",
            json={"request": {"filters": {"slug": "sunbird"}}},
            headers=_anon_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        _channel_id = (
            data["result"]["response"]["content"][0]["hashTagId"]
        )
        print(f"[sunbird-mcp] Channel ID resolved: {_channel_id}")
    except httpx.HTTPStatusError as exc:
        raise SunbirdApiError(
            exc.response.status_code,
            "ERR_ORG_SEARCH",
            f"Failed to resolve channel ID: {exc}",
        ) from exc


async def resolve_loggedin_kong_token() -> None:
    """
    Mirrors portal's generateLoggedInKongToken() — registers a portal_loggedin
    consumer credential with Kong and caches the token for the lifetime of this process.
    Falls back to KONG_LOGGEDIN_TOKEN (static fallback) if registration is not configured.
    Called once at server startup alongside resolve_channel_id().
    """
    global _loggedin_kong_token

    if not env.KONG_LOGGEDIN_DEVICE_REGISTER_TOKEN:
        _loggedin_kong_token = env.KONG_LOGGEDIN_TOKEN
        if _loggedin_kong_token:
            print("[sunbird-mcp] Loggedin Kong token loaded from env (static fallback).")
        else:
            print("[sunbird-mcp] WARNING: KONG_LOGGEDIN_DEVICE_REGISTER_TOKEN not set — authenticated tools will use anonymous token and may fail.")
        return

    client = _get_client()
    session_key = f"sunbird-mcp-{uuid.uuid4().hex}"
    try:
        resp = await client.post(
            "/api-manager/v2/consumer/portal_loggedin/credential/register",
            json={"request": {"key": session_key}},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {env.KONG_LOGGEDIN_DEVICE_REGISTER_TOKEN}",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        status = data.get("params", {}).get("status")
        token = data.get("result", {}).get("token")
        if status == "successful" and token:
            _loggedin_kong_token = token
            print("[sunbird-mcp] Loggedin Kong token registered successfully.")
            return
        raise SunbirdApiError(200, "ERR_KONG_REGISTER", f"Unexpected registration response: {data}")
    except (httpx.HTTPStatusError, SunbirdApiError) as exc:
        print(f"[sunbird-mcp] WARNING: Loggedin Kong token registration failed ({exc}). Falling back to static token.")
        _loggedin_kong_token = env.KONG_LOGGEDIN_TOKEN


async def kong_get(path: str) -> dict:
    """HTTP GET to Kong gateway with anonymous auth + channel headers."""
    client = _get_client()
    try:
        resp = await client.get(path, headers=_anon_headers())
        if resp.status_code >= 400:
            raise SunbirdApiError(resp.status_code, "ERR_KONG_RESPONSE", resp.text)
        return resp.json()
    except httpx.TimeoutException as exc:
        raise SunbirdApiError(0, "ERR_TIMEOUT", "Sunbird service unreachable. Verify KONG_URL in .env.") from exc


async def kong_post(path: str, body: dict) -> dict:
    """HTTP POST to Kong gateway with anonymous auth + channel headers."""
    client = _get_client()
    try:
        resp = await client.post(path, json=body, headers=_anon_headers())
        if resp.status_code >= 400:
            raise SunbirdApiError(resp.status_code, "ERR_KONG_RESPONSE", resp.text)
        return resp.json()
    except httpx.TimeoutException as exc:
        raise SunbirdApiError(0, "ERR_TIMEOUT", "Sunbird service unreachable. Verify KONG_URL in .env.") from exc


# ── Authenticated Kong client (logged-in user) ────────────────────────────────

def _auth_headers(user_token: str) -> dict[str, str]:
    """
    Mirrors portal's decorateRequestHeaders() + getBearerToken():
    - Authorization: Bearer = portal_loggedin Kong consumer token (registered at startup)
    - x-authenticated-user-token / x-auth-token = user's Keycloak access token
    - X-Authenticated-Userid = bare user UUID (required by Kong ACL plugin)
    These are two distinct tokens; sending the Keycloak token as Bearer causes
    "You cannot consume this service" because it's not a registered Kong consumer.
    """
    bearer = _loggedin_kong_token or env.KONG_LOGGEDIN_TOKEN or env.KONG_ANONYMOUS_TOKEN
    try:
        user_id = extract_sunbird_user_id(user_token)
    except InvalidTokenError:
        user_id = ""
    return {
        **_channel_header(),
        "Authorization": f"Bearer {bearer}",
        "x-authenticated-user-token": user_token,
        "x-auth-token": user_token,
        "X-Authenticated-Userid": user_id,
    }


async def authenticated_get(path: str, user_token: str) -> dict:
    """HTTP GET to Kong with both anonymous bearer + user identity headers."""
    client = _get_client()
    try:
        resp = await client.get(path, headers=_auth_headers(user_token))
        if resp.status_code >= 400:
            raise SunbirdApiError(resp.status_code, "ERR_KONG_RESPONSE", resp.text)
        return resp.json()
    except httpx.TimeoutException as exc:
        raise SunbirdApiError(0, "ERR_TIMEOUT", "Sunbird service unreachable.") from exc


async def authenticated_post(path: str, body: dict, user_token: str) -> dict:
    """HTTP POST to Kong with both anonymous bearer + user identity headers."""
    client = _get_client()
    try:
        resp = await client.post(path, json=body, headers=_auth_headers(user_token))
        if resp.status_code >= 400:
            raise SunbirdApiError(resp.status_code, "ERR_KONG_RESPONSE", resp.text)
        return resp.json()
    except httpx.TimeoutException as exc:
        raise SunbirdApiError(0, "ERR_TIMEOUT", "Sunbird service unreachable.") from exc


async def authenticated_patch(path: str, body: dict, user_token: str) -> dict:
    """HTTP PATCH to Kong with both anonymous bearer + user identity headers."""
    client = _get_client()
    try:
        resp = await client.patch(path, json=body, headers=_auth_headers(user_token))
        if resp.status_code >= 400:
            raise SunbirdApiError(resp.status_code, "ERR_KONG_RESPONSE", resp.text)
        return resp.json()
    except httpx.TimeoutException as exc:
        raise SunbirdApiError(0, "ERR_TIMEOUT", "Sunbird service unreachable.") from exc


# ── JWT helpers ───────────────────────────────────────────────────────────────

def decode_jwt_payload(token: str) -> dict:
    """
    Base64-decode the JWT payload section.
    Kong validates the signature server-side; we only decode claims for routing purposes.
    Raises InvalidTokenError on malformed input instead of silently returning {}.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise InvalidTokenError(
            f"Token is not a valid JWT: expected 3 dot-separated parts, got {len(parts)}"
        )
    try:
        payload_b64 = parts[1]
        # Restore missing base64 padding
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except (ValueError, binascii.Error, json.JSONDecodeError) as exc:
        raise InvalidTokenError(f"JWT payload could not be decoded: {exc}") from exc


def extract_sunbird_user_id(token: str) -> str:
    """
    Extract the plain Sunbird user UUID from a JWT token.
    Keycloak federates IDs as 'f:cassandrafederationid:<uuid>' — strip the prefix.
    The enrollment/progress APIs expect just the bare UUID.
    Raises InvalidTokenError if the token is malformed or has no sub claim.
    """
    claims = decode_jwt_payload(token)  # raises InvalidTokenError on bad input
    sub: str = claims.get("sub", "")
    if not sub:
        raise InvalidTokenError("JWT token has no 'sub' claim")
    # Strip federation prefix e.g. "f:cassandrafederationid:6a0acaee-..."
    if ":" in sub:
        sub = sub.rsplit(":", 1)[-1]
    return sub


# ── Keycloak direct auth ──────────────────────────────────────────────────────

def _keycloak_token_url() -> str:
    if not env.KEYCLOAK_ISSUER_URL or not env.KEYCLOAK_CLIENT_ID:
        raise KeycloakAuthError(
            "LOGIN_NOT_CONFIGURED",
            "Set KEYCLOAK_ISSUER_URL and KEYCLOAK_CLIENT_ID in .env to enable login.",
            status_code=500,
        )
    return f"{env.KEYCLOAK_ISSUER_URL.rstrip('/')}/protocol/openid-connect/token"


def _map_keycloak_error(error: str, description: str) -> KeycloakAuthError:
    desc_lower = description.lower()
    if error == "invalid_grant" and any(
        w in desc_lower for w in ("disabled", "blocked", "not fully set up")
    ):
        return KeycloakAuthError("USER_ACCOUNT_BLOCKED", "User account is blocked. Contact admin.")
    if error == "invalid_grant":
        return KeycloakAuthError("INVALID_CREDENTIALS", description)
    return KeycloakAuthError(error, description)


async def keycloak_refresh(refresh_token: str) -> dict:
    """
    Keycloak refresh-token grant.
    Returns dict with access_token, refresh_token, expires_in.
    """
    token_url = _keycloak_token_url()
    params: dict[str, str] = {
        "grant_type": "refresh_token",
        "client_id": env.KEYCLOAK_CLIENT_ID,
        "refresh_token": refresh_token,
    }
    if env.KEYCLOAK_CLIENT_SECRET:
        params["client_secret"] = env.KEYCLOAK_CLIENT_SECRET

    async with httpx.AsyncClient(timeout=30.0) as kc:
        try:
            resp = await kc.post(
                token_url,
                content=urlencode(params),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code >= 400:
                err_data = resp.json()
                raise _map_keycloak_error(
                    err_data.get("error", "REFRESH_FAILED"),
                    err_data.get("error_description", "Token refresh failed"),
                )
            return resp.json()
        except KeycloakAuthError:
            raise
        except httpx.TimeoutException as exc:
            raise KeycloakAuthError(
                "KEYCLOAK_UNREACHABLE",
                "Keycloak service timed out.",
                status_code=503,
            ) from exc


# ── Device Authorization Flow (RFC 8628) ─────────────────────────────────────

def _keycloak_device_auth_url() -> str:
    if not env.KEYCLOAK_ISSUER_URL or not env.KEYCLOAK_CLIENT_ID:
        raise KeycloakAuthError(
            "LOGIN_NOT_CONFIGURED",
            "Set KEYCLOAK_ISSUER_URL and KEYCLOAK_CLIENT_ID in .env to enable login.",
            status_code=500,
        )
    return f"{env.KEYCLOAK_ISSUER_URL.rstrip('/')}/protocol/openid-connect/auth/device"


def _map_keycloak_device_error(error: str, description: str) -> KeycloakAuthError:
    """Map RFC 8628 device-flow error codes to typed exceptions."""
    if error == "authorization_pending":
        return KeycloakAuthError("AUTHORIZATION_PENDING", description, status_code=400)
    if error == "slow_down":
        return KeycloakAuthError("SLOW_DOWN", description, status_code=400)
    if error == "expired_token":
        return KeycloakAuthError("DEVICE_CODE_EXPIRED", "The device code has expired. Call tool_login_start again.", status_code=400)
    if error == "access_denied":
        return KeycloakAuthError("ACCESS_DENIED", "Login was denied or cancelled by the user.", status_code=403)
    return KeycloakAuthError(error, description)


async def keycloak_device_auth_start() -> dict:
    """
    RFC 8628 §3.1 — Device Authorization Request.
    Returns: device_code, user_code, verification_uri, verification_uri_complete,
             expires_in, interval.
    """
    device_url = _keycloak_device_auth_url()
    params: dict[str, str] = {
        "client_id": env.KEYCLOAK_CLIENT_ID,
        "scope": "openid",
    }
    if env.KEYCLOAK_CLIENT_SECRET:
        params["client_secret"] = env.KEYCLOAK_CLIENT_SECRET

    async with httpx.AsyncClient(timeout=30.0) as kc:
        try:
            resp = await kc.post(
                device_url,
                content=urlencode(params),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code >= 400:
                err_data = resp.json()
                raise KeycloakAuthError(
                    err_data.get("error", "DEVICE_AUTH_FAILED"),
                    err_data.get("error_description", "Device authorization failed"),
                    status_code=resp.status_code,
                )
            return resp.json()
        except KeycloakAuthError:
            raise
        except httpx.TimeoutException as exc:
            raise KeycloakAuthError(
                "KEYCLOAK_UNREACHABLE",
                "Keycloak service timed out.",
                status_code=503,
            ) from exc


async def keycloak_device_auth_poll(device_code: str) -> dict:
    """
    RFC 8628 §3.4 — Device Access Token Request.
    Returns tokens on approval.
    Raises KeycloakAuthError with error=AUTHORIZATION_PENDING while user hasn't acted yet.
    Raises KeycloakAuthError with error=DEVICE_CODE_EXPIRED or ACCESS_DENIED on terminal failure.
    """
    token_url = _keycloak_token_url()
    params: dict[str, str] = {
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "client_id": env.KEYCLOAK_CLIENT_ID,
        "device_code": device_code,
    }
    if env.KEYCLOAK_CLIENT_SECRET:
        params["client_secret"] = env.KEYCLOAK_CLIENT_SECRET

    async with httpx.AsyncClient(timeout=30.0) as kc:
        try:
            resp = await kc.post(
                token_url,
                content=urlencode(params),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code >= 400:
                err_data = resp.json()
                raise _map_keycloak_device_error(
                    err_data.get("error", "POLL_FAILED"),
                    err_data.get("error_description", "Token poll failed"),
                )
            return resp.json()
        except KeycloakAuthError:
            raise
        except httpx.TimeoutException as exc:
            raise KeycloakAuthError(
                "KEYCLOAK_UNREACHABLE",
                "Keycloak service timed out.",
                status_code=503,
            ) from exc
