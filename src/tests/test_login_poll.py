"""Tests for tool_login_poll (Device Authorization Flow — RFC 8628 §3.4)."""
import base64
import json

import pytest
import respx
import httpx

from config.env import env
from schemas.tool_schemas import LoginPollInput
from tools.login_poll import login_poll

KEYCLOAK_TOKEN_URL = f"{env.KEYCLOAK_ISSUER_URL}/protocol/openid-connect/token"


def _make_jwt(sub: str = "user-123", name: str = "Test User") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"sub": sub, "name": name, "preferred_username": "testuser"}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


@pytest.mark.asyncio
@respx.mock
async def test_login_poll_success():
    access_token = _make_jwt("user-abc", "Alice")
    respx.post(KEYCLOAK_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": access_token,
                "refresh_token": "refresh-xyz",
                "expires_in": 3600,
            },
        )
    )

    result = await login_poll(LoginPollInput(device_code="dev-code-xyz"))

    assert result.success is True
    assert result.pending is False
    assert result.user_id == "user-abc"
    assert result.user_name == "Alice"
    assert result.access_token == access_token
    assert result.refresh_token == "refresh-xyz"
    assert result.expires_in == 3600


@pytest.mark.asyncio
@respx.mock
async def test_login_poll_authorization_pending():
    """User hasn't approved in the browser yet — should return pending=True, not an error."""
    respx.post(KEYCLOAK_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": "authorization_pending",
                "error_description": "The authorization request is still pending",
            },
        )
    )

    result = await login_poll(LoginPollInput(device_code="dev-code-xyz"))

    assert result.success is False
    assert result.pending is True
    assert result.access_token == ""
    assert "tool_login_poll" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_login_poll_slow_down():
    """Keycloak asks the client to slow down polling — also treated as pending."""
    respx.post(KEYCLOAK_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": "slow_down", "error_description": "Polling too fast"},
        )
    )

    result = await login_poll(LoginPollInput(device_code="dev-code-xyz"))

    assert result.success is False
    assert result.pending is True


@pytest.mark.asyncio
@respx.mock
async def test_login_poll_expired_token():
    """Device code has expired — terminal failure, pending=False."""
    respx.post(KEYCLOAK_TOKEN_URL).mock(
        return_value=httpx.Response(
            400,
            json={"error": "expired_token", "error_description": "Device code expired"},
        )
    )

    result = await login_poll(LoginPollInput(device_code="old-dev-code"))

    assert result.success is False
    assert result.pending is False
    assert "DEVICE_CODE_EXPIRED" in result.message or "expired" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_login_poll_access_denied():
    """User explicitly denied the login request — terminal failure."""
    respx.post(KEYCLOAK_TOKEN_URL).mock(
        return_value=httpx.Response(
            403,
            json={"error": "access_denied", "error_description": "User denied access"},
        )
    )

    result = await login_poll(LoginPollInput(device_code="dev-code-xyz"))

    assert result.success is False
    assert result.pending is False
    assert "ACCESS_DENIED" in result.message or "denied" in result.message.lower()


@pytest.mark.asyncio
@respx.mock
async def test_login_poll_timeout():
    respx.post(KEYCLOAK_TOKEN_URL).mock(side_effect=httpx.TimeoutException("timed out"))

    result = await login_poll(LoginPollInput(device_code="dev-code-xyz"))

    assert result.success is False
    assert result.pending is False
    assert "KEYCLOAK_UNREACHABLE" in result.message or "timed out" in result.message.lower()
