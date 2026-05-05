"""
Tool: refresh_token
Exchanges a Keycloak refresh token for a new access token.
Call this when the access_token is about to expire instead of re-entering the password.
"""
from __future__ import annotations

from client.sunbird_client import KeycloakAuthError, keycloak_refresh
from schemas.tool_schemas import RefreshTokenInput, RefreshTokenOutput


async def refresh_token(params: RefreshTokenInput) -> RefreshTokenOutput:
    try:
        tokens = await keycloak_refresh(params.refresh_token)
    except KeycloakAuthError as e:
        return RefreshTokenOutput(
            success=False,
            access_token="",
            refresh_token="",
            expires_in=0,
            message=f"{e.error}: {e}",
        )

    return RefreshTokenOutput(
        success=True,
        access_token=tokens.get("access_token", ""),
        refresh_token=tokens.get("refresh_token", ""),
        expires_in=int(tokens.get("expires_in", 0)),
        message="Token refreshed successfully.",
    )
