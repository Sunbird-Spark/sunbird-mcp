import os
import sys
from pathlib import Path

# Set required env vars before pydantic-settings loads at module import time.
# Tests use respx to mock all HTTP, so these values are never sent to a real server.
os.environ.setdefault("KONG_URL", "http://localhost:8000")
os.environ.setdefault("KONG_ANONYMOUS_TOKEN", "test-anonymous-token")
os.environ.setdefault("KEYCLOAK_ISSUER_URL", "http://localhost:8080/auth/realms/sunbird")
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "android")
os.environ.setdefault("KEYCLOAK_CLIENT_SECRET", "")

# Make src/ the importable root so `from client.`, `from tools.`, etc. all resolve.
sys.path.insert(0, str(Path(__file__).parent))

import pytest
import client.sunbird_client as _sunbird_client_mod


@pytest.fixture(autouse=True)
def _reset_sunbird_client():
    """Reset the httpx singleton before each test so respx intercepts a fresh client."""
    _sunbird_client_mod._client = None
    _sunbird_client_mod._channel_id = ""
    yield
    _sunbird_client_mod._client = None
    _sunbird_client_mod._channel_id = ""
