"""Tests for tool_enroll_in_course."""
import base64
import json

import pytest
import respx
import httpx

from config.env import env
from schemas.tool_schemas import EnrollInCourseInput
from tools.enroll_in_course import enroll_in_course


def _make_jwt(sub: str = "user-123") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


BATCH_LIST_URL = f"{env.KONG_URL}/course/v1/batch/list"
ENROL_URL = f"{env.KONG_URL}/course/v1/enrol"


@pytest.mark.asyncio
@respx.mock
async def test_enroll_with_explicit_batch():
    respx.post(ENROL_URL).mock(
        return_value=httpx.Response(200, json={"responseCode": "OK"})
    )

    result = await enroll_in_course(
        EnrollInCourseInput(
            user_token=_make_jwt(),
            course_id="do_course1",
            batch_id="batch-abc",
        )
    )

    assert result.success is True
    assert result.batch_id == "batch-abc"
    assert result.course_id == "do_course1"


@pytest.mark.asyncio
@respx.mock
async def test_enroll_auto_select_batch():
    respx.post(BATCH_LIST_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "result": {
                    "response": {
                        "content": [{"batchId": "batch-auto", "enrollmentType": "open", "status": 1}]
                    }
                }
            },
        )
    )
    respx.post(ENROL_URL).mock(
        return_value=httpx.Response(200, json={"responseCode": "OK"})
    )

    result = await enroll_in_course(
        EnrollInCourseInput(user_token=_make_jwt(), course_id="do_course1")
    )

    assert result.success is True
    assert result.batch_id == "batch-auto"


@pytest.mark.asyncio
@respx.mock
async def test_enroll_no_open_batch():
    respx.post(BATCH_LIST_URL).mock(
        return_value=httpx.Response(
            200, json={"result": {"response": {"content": []}}}
        )
    )

    result = await enroll_in_course(
        EnrollInCourseInput(user_token=_make_jwt(), course_id="do_course_no_batch")
    )

    assert result.success is False
    assert "No active open batch" in result.message


@pytest.mark.asyncio
@respx.mock
async def test_enroll_already_enrolled():
    respx.post(ENROL_URL).mock(
        return_value=httpx.Response(
            400,
            json={"params": {"err": "USER_ALREADY_ENROLLED_COURSE", "errmsg": "USER_ALREADY_ENROLLED_COURSE"}},
        )
    )

    result = await enroll_in_course(
        EnrollInCourseInput(
            user_token=_make_jwt(),
            course_id="do_course1",
            batch_id="batch-abc",
        )
    )

    assert result.success is True
    assert "Already enrolled" in result.message
