"""
Tool: login_poll
Polls Keycloak for the Device Authorization Flow result (RFC 8628 §3.4).

Call this after tool_login_start. If pending=True the user hasn't approved yet —
wait `interval` seconds (from login_start output) and call again.
Returns access_token + refresh_token once the user approves in their browser.
"""
from __future__ import annotations

from client.sunbird_client import (
    KeycloakAuthError,
    decode_jwt_payload,
    keycloak_device_auth_poll,
)
from schemas.tool_schemas import LoginPollInput, LoginPollOutput

_PENDING_ERRORS = {"AUTHORIZATION_PENDING", "SLOW_DOWN"}


async def login_poll(params: LoginPollInput) -> LoginPollOutput:
    try:
        tokens = await keycloak_device_auth_poll(params.device_code)
    except KeycloakAuthError as e:
        if e.error in _PENDING_ERRORS:
            return LoginPollOutput(
                success=False,
                pending=True,
                user_id="",
                user_name="",
                access_token="",
                refresh_token="",
                expires_in=0,
                message="User hasn't approved yet. Wait the recommended interval and call tool_login_poll again.",
            )
        return LoginPollOutput(
            success=False,
            pending=False,
            user_id="",
            user_name="",
            access_token="",
            refresh_token="",
            expires_in=0,
            message=f"{e.error}: {e}",
        )

    access_token: str = tokens.get("access_token", "")
    claims = decode_jwt_payload(access_token)

    user_id: str = claims.get("sub", "")
    user_name: str = (
        claims.get("name")
        or claims.get("preferred_username")
        or claims.get("email")
        or ""
    )

    return LoginPollOutput(
        success=True,
        pending=False,
        user_id=user_id,
        user_name=user_name,
        access_token=access_token,
        refresh_token=tokens.get("refresh_token", ""),
        expires_in=int(tokens.get("expires_in", 0)),
        message="Login successful. Use access_token in all user-scoped tools.",
    )
