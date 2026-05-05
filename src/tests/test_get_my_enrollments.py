"""Tests for tool_get_my_enrollments."""
import base64
import json

import pytest
import respx
import httpx

from config.env import env
from schemas.tool_schemas import GetMyEnrollmentsInput
from tools.get_my_enrollments import get_my_enrollments


def _make_jwt(sub: str = "user-123") -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


_MOCK_COURSES = [
    {
        "courseId": "do_course1",
        "contentDetails": {"name": "Data Science 101"},
        "completionPercentage": 100,
        "status": 2,
        "enrolledDate": "2026-01-10",
        "issuedCertificates": [{"name": "cert"}],
    },
    {
        "courseId": "do_course2",
        "contentDetails": {"name": "Python Basics"},
        "completionPercentage": 40,
        "status": 1,
        "enrolledDate": "2026-02-15",
        "issuedCertificates": [],
    },
    {
        "courseId": "do_course3",
        "contentDetails": {"name": "Machine Learning"},
        "completionPercentage": 0,
        "status": 0,
        "enrolledDate": "2026-03-01",
        "issuedCertificates": [],
    },
]


@pytest.mark.asyncio
@respx.mock
async def test_get_all_enrollments():
    respx.get(url__regex=r".*/course/v1/user/enrollment/list/user-123.*").mock(
        return_value=httpx.Response(200, json={"result": {"courses": _MOCK_COURSES}})
    )

    result = await get_my_enrollments(
        GetMyEnrollmentsInput(user_token=_make_jwt(), status_filter="all", limit=10)
    )

    assert result.total == 3
    assert result.courses[0].course_id == "do_course1"
    assert result.courses[0].status == "completed"
    assert result.courses[0].has_certificate is True
    assert result.courses[1].status == "in_progress"
    assert result.courses[2].status == "not_started"


@pytest.mark.asyncio
@respx.mock
async def test_filter_by_in_progress():
    respx.get(url__regex=r".*/course/v1/user/enrollment/list/user-123.*").mock(
        return_value=httpx.Response(200, json={"result": {"courses": _MOCK_COURSES}})
    )

    result = await get_my_enrollments(
        GetMyEnrollmentsInput(user_token=_make_jwt(), status_filter="in_progress", limit=10)
    )

    assert all(c.status == "in_progress" for c in result.courses)


@pytest.mark.asyncio
@respx.mock
async def test_empty_enrollments():
    respx.get(url__regex=r".*/course/v1/user/enrollment/list/user-123.*").mock(
        return_value=httpx.Response(200, json={"result": {"courses": []}})
    )

    result = await get_my_enrollments(
        GetMyEnrollmentsInput(user_token=_make_jwt(), status_filter="all")
    )

    assert result.total == 0
    assert result.courses == []


@pytest.mark.asyncio
async def test_invalid_token_returns_error():
    result = await get_my_enrollments(
        GetMyEnrollmentsInput(user_token="not.a.jwt", status_filter="all")
    )
    assert result.total == 0
    assert "user ID" in result.message
