"""Tests for tool_refresh_token."""
import pytest
import respx
import httpx

from config.env import env
from schemas.tool_schemas import RefreshTokenInput
from tools.refresh_token import refresh_token

KEYCLOAK_TOKEN_URL = f"{env.KEYCLOAK_ISSUER_URL}/protocol/openid-connect/token"


@pytest.mark.asyncio
@respx.mock
async def test_refresh_success():
    respx.post(KEYCLOAK_TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "expires_in": 3600,
            },
        )
    )

    result = await refresh_token(RefreshTokenInput(refresh_token="old-refresh-token"))

    assert result.success is True
    assert result.access_token == "new-access-token"
    assert result.refresh_token == "new-refresh-token"
    assert result.expires_in == 3600


@pytest.mark.asyncio
@respx.mock
async def test_refresh_expired_token():
    respx.post(KEYCLOAK_TOKEN_URL).mock(
        return_value=httpx.Response(
            401,
            json={"error": "invalid_grant", "error_description": "Token expired"},
        )
    )

    result = await refresh_token(RefreshTokenInput(refresh_token="expired-token"))

    assert result.success is False
    assert result.access_token == ""
    assert "INVALID_CREDENTIALS" in result.message or "invalid_grant" in result.message.lower()
