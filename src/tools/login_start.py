"""
Tool: login_start
Initiates an OAuth2 Device Authorization Flow (RFC 8628) with Keycloak.
Returns a short user_code and verification_uri the user opens in their browser —
no password is ever passed through the AI.
After the user approves, call tool_login_poll with the returned device_code.
"""
from __future__ import annotations

from client.sunbird_client import KeycloakAuthError, keycloak_device_auth_start
from schemas.tool_schemas import LoginStartOutput


async def login_start() -> LoginStartOutput:
    try:
        data = await keycloak_device_auth_start()
    except KeycloakAuthError as e:
        return LoginStartOutput(
            device_code="",
            user_code="",
            verification_uri="",
            expires_in=0,
            interval=5,
            message=f"{e.error}: {e}",
        )

    user_code: str = data.get("user_code", "")
    verification_uri: str = data.get("verification_uri_complete") or data.get("verification_uri", "")
    expires_in: int = int(data.get("expires_in", 600))
    interval: int = int(data.get("interval", 5))

    return LoginStartOutput(
        device_code=data.get("device_code", ""),
        user_code=user_code,
        verification_uri=verification_uri,
        expires_in=expires_in,
        interval=interval,
        message=(
            f"Open this URL in your browser and enter the code when prompted:\n"
            f"  URL:  {verification_uri}\n"
            f"  Code: {user_code}\n"
            f"Then call tool_login_poll with the device_code. "
            f"The code expires in {expires_in}s. Poll every {interval}s."
        ),
    )
