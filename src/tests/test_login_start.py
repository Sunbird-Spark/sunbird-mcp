"""Tests for tool_login_start (Device Authorization Flow — RFC 8628 §3.1)."""
import pytest
import respx
import httpx

from config.env import env
from tools.login_start import login_start

DEVICE_AUTH_URL = f"{env.KEYCLOAK_ISSUER_URL}/protocol/openid-connect/auth/device"


@pytest.mark.asyncio
@respx.mock
async def test_login_start_success():
    respx.post(DEVICE_AUTH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "dev-code-xyz",
                "user_code": "ABCD-1234",
                "verification_uri": "https://test.sunbirded.org/auth/device",
                "verification_uri_complete": "https://test.sunbirded.org/auth/device?user_code=ABCD-1234",
                "expires_in": 600,
                "interval": 5,
            },
        )
    )

    result = await login_start()

    assert result.device_code == "dev-code-xyz"
    assert result.user_code == "ABCD-1234"
    assert "ABCD-1234" in result.verification_uri
    assert result.expires_in == 600
    assert result.interval == 5
    assert "tool_login_poll" in result.message
    assert "ABCD-1234" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_login_start_uses_verification_uri_complete_when_available():
    """verification_uri_complete (with embedded code) should be preferred over verification_uri."""
    respx.post(DEVICE_AUTH_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "dev-code-xyz",
                "user_code": "EFGH-5678",
                "verification_uri": "https://test.sunbirded.org/auth/device",
                "verification_uri_complete": "https://test.sunbirded.org/auth/device?user_code=EFGH-5678",
                "expires_in": 600,
                "interval": 5,
            },
        )
    )

    result = await login_start()

    assert "EFGH-5678" in result.verification_uri


@pytest.mark.asyncio
@respx.mock
async def test_login_start_keycloak_error():
    """Device flow not enabled on the Keycloak client returns an error response."""
    respx.post(DEVICE_AUTH_URL).mock(
        return_value=httpx.Response(
            400,
            json={
                "error": "invalid_client",
                "error_description": "Device flow not enabled for this client",
            },
        )
    )

    result = await login_start()

    assert result.device_code == ""
    assert result.user_code == ""
    assert "invalid_client" in result.message or "Device flow" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_login_start_timeout():
    respx.post(DEVICE_AUTH_URL).mock(side_effect=httpx.TimeoutException("timed out"))

    result = await login_start()

    assert result.device_code == ""
    assert "KEYCLOAK_UNREACHABLE" in result.message or "timed out" in result.message.lower()
