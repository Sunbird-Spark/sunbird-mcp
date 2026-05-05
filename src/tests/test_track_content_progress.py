"""Tests for tool_track_content_progress."""
import base64
import json

import pytest
import respx
import httpx

from config.env import env
from schemas.tool_schemas import TrackContentProgressInput
from tools.track_content_progress import track_content_progress


def _make_jwt(sub: str = "user-123") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


STATE_UPDATE_URL = f"{env.KONG_URL}/course/v1/content/state/update"


@pytest.mark.asyncio
@respx.mock
async def test_mark_content_completed():
    respx.patch(STATE_UPDATE_URL).mock(
        return_value=httpx.Response(200, json={"responseCode": "OK"})
    )

    result = await track_content_progress(
        TrackContentProgressInput(
            user_token=_make_jwt(),
            course_id="do_course1",
            batch_id="batch-abc",
            content_id="do_content1",
            status="completed",
            completion_percentage=100,
        )
    )

    assert result.success is True
    assert result.new_status == "completed"
    assert result.content_id == "do_content1"


@pytest.mark.asyncio
@respx.mock
async def test_mark_content_in_progress():
    respx.patch(STATE_UPDATE_URL).mock(
        return_value=httpx.Response(200, json={"responseCode": "OK"})
    )

    result = await track_content_progress(
        TrackContentProgressInput(
            user_token=_make_jwt(),
            course_id="do_course1",
            batch_id="batch-abc",
            content_id="do_content2",
            status="in_progress",
            completion_percentage=50,
        )
    )

    assert result.success is True
    assert result.new_status == "in_progress"


@pytest.mark.asyncio
@respx.mock
async def test_track_api_error():
    respx.patch(STATE_UPDATE_URL).mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    result = await track_content_progress(
        TrackContentProgressInput(
            user_token=_make_jwt(),
            course_id="do_course1",
            batch_id="batch-abc",
            content_id="do_content1",
        )
    )

    assert result.success is False
    assert "Progress update failed" in result.message
