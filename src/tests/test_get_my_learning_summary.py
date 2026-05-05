"""Tests for tool_get_my_learning_summary."""
import base64
import json

import pytest
import respx
import httpx

from schemas.tool_schemas import GetMyLearningSummaryInput
from tools.get_my_learning_summary import get_my_learning_summary


def _make_jwt(sub: str = "user-123") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


_MOCK_COURSES = [
    {
        "courseId": "do_c1",
        "contentDetails": {"name": "Course A"},
        "completionPercentage": 100,
        "status": 2,
        "enrolledDate": "2026-01-01",
        "issuedCertificates": [{"name": "cert"}],
    },
    {
        "courseId": "do_c2",
        "contentDetails": {"name": "Course B"},
        "completionPercentage": 60,
        "status": 1,
        "enrolledDate": "2026-02-01",
        "issuedCertificates": [],
    },
    {
        "courseId": "do_c3",
        "contentDetails": {"name": "Course C"},
        "completionPercentage": 0,
        "status": 0,
        "enrolledDate": "2026-03-01",
        "issuedCertificates": [],
    },
]


@pytest.mark.asyncio
@respx.mock
async def test_summary_counts():
    respx.get(url__regex=r".*/course/v1/user/enrollment/list/user-123.*").mock(
        return_value=httpx.Response(200, json={"result": {"courses": _MOCK_COURSES}})
    )

    result = await get_my_learning_summary(GetMyLearningSummaryInput(user_token=_make_jwt()))

    assert result.total_enrolled == 3
    assert result.completed == 1
    assert result.in_progress == 1
    assert result.not_started == 1
    assert result.certificates_earned == 1
    assert len(result.recent_courses) <= 5


@pytest.mark.asyncio
@respx.mock
async def test_summary_empty():
    respx.get(url__regex=r".*/course/v1/user/enrollment/list/user-123.*").mock(
        return_value=httpx.Response(200, json={"result": {"courses": []}})
    )

    result = await get_my_learning_summary(GetMyLearningSummaryInput(user_token=_make_jwt()))

    assert result.total_enrolled == 0
    assert result.certificates_earned == 0
    assert result.recent_courses == []


@pytest.mark.asyncio
async def test_summary_invalid_token():
    result = await get_my_learning_summary(
        GetMyLearningSummaryInput(user_token="not.a.valid.jwt")
    )
    assert result.total_enrolled == 0
    assert result.message is not None
    assert "user ID" in result.message
