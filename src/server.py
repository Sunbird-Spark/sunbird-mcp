"""
Entry point for the Sunbird Spark MCP Server (Python implementation).

Anonymous tools (5):  search_content, get_course_outline, get_quiz_questions,
                      build_learning_path, navigate_course
Auth tools (7):       tool_login_start, tool_login_poll, tool_refresh_token,
                      tool_get_my_enrollments, tool_enroll_in_course,
                      tool_track_content_progress, tool_get_my_learning_summary
"""
import asyncio
import json
import time

from mcp.server.fastmcp import FastMCP

from config.env import env
from client.sunbird_client import SunbirdApiError, KeycloakAuthError, InvalidTokenError, resolve_channel_id, resolve_loggedin_kong_token
from tools.search_content import search_content
from tools.get_course_outline import get_course_outline
from tools.get_quiz_questions import get_quiz_questions
from tools.build_learning_path import build_learning_path
from tools.navigate_course import navigate_course
from tools.get_batch_list import get_batch_list
from tools.login_start import login_start
from tools.login_poll import login_poll
from tools.submit_assessment import submit_assessment
from tools.refresh_token import refresh_token
from tools.get_my_enrollments import get_my_enrollments
from tools.enroll_in_course import enroll_in_course
from tools.track_content_progress import track_content_progress
from tools.get_my_learning_summary import get_my_learning_summary
from schemas.tool_schemas import (
    SearchContentInput,
    GetCourseOutlineInput,
    GetQuizQuestionsInput,
    BuildLearningPathInput,
    NavigateCourseInput,
    GetBatchListInput,
    LoginPollInput,
    SubmitAssessmentInput,
    AssessmentQuestion,
    RefreshTokenInput,
    GetMyEnrollmentsInput,
    EnrollInCourseInput,
    TrackContentProgressInput,
    GetMyLearningSummaryInput,
)

mcp = FastMCP(
    "sunbird-spark-mcp-py",
    host="0.0.0.0",
    port=env.MCP_PORT,
    stateless_http=True,
)

# Minimum seconds between tool_login_start calls — prevents hammering Keycloak
_LOGIN_START_COOLDOWN_SEC = 5.0
_last_login_start: float = 0.0


# ── Anonymous tools ───────────────────────────────────────────────────────────

@mcp.tool()
async def tool_search_content(
    query: str,
    content_type: str | None = None,
    language: str | None = None,
    limit: int = 10,
) -> str:
    """Search Sunbird for courses, resources, or question sets by keyword."""
    params = SearchContentInput(
        query=query,
        content_type=content_type,
        language=language,
        limit=limit,
    )
    try:
        result = await search_content(params)
        return result.model_dump_json(indent=2)
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_get_course_outline(course_id: str) -> str:
    """Get full course structure: units, lessons, and resource types."""
    params = GetCourseOutlineInput(course_id=course_id)
    try:
        result = await get_course_outline(params)
        return result.model_dump_json(indent=2)
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_get_quiz_questions(question_set_id: str) -> str:
    """Fetch all questions from a question set to run a conversational quiz."""
    params = GetQuizQuestionsInput(question_set_id=question_set_id)
    try:
        result = await get_quiz_questions(params)
        return result.model_dump_json(indent=2)
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_build_learning_path(
    topic: str,
    level: str | None = None,
    language: str = "English",
    max_courses: int = 5,
) -> str:
    """Build an ordered multi-course learning path for a topic or skill."""
    params = BuildLearningPathInput(
        topic=topic,
        level=level,
        language=language,
        max_courses=max_courses,
    )
    try:
        result = await build_learning_path(params)
        return result.model_dump_json(indent=2)
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_navigate_course(
    goal: str,
    language: str = "English",
    max_results: int = 3,
) -> str:
    """Find and navigate courses matching a user learning goal."""
    params = NavigateCourseInput(
        goal=goal,
        language=language,
        max_results=max_results,
    )
    try:
        result = await navigate_course(params)
        return result.model_dump_json(indent=2)
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_get_batch_list(
    course_id: str,
    status: str = "active",
) -> str:
    """
    List all batches for a course with status, enrollment type, dates, and
    whether each batch is currently enrollable.
    status: 'active' | 'upcoming' | 'expired' | 'all'
    Use this before tool_enroll_in_course to find a valid batch_id.
    """
    params = GetBatchListInput(course_id=course_id, status=status)
    try:
        result = await get_batch_list(params)
        return result.model_dump_json(indent=2)
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


# ── Auth tools ────────────────────────────────────────────────────────────────

@mcp.tool()
async def tool_login_start() -> str:
    """
    Start a password-free login using the OAuth2 Device Authorization Flow (RFC 8628).
    Returns a short user_code and a verification_uri the user opens in their browser.
    No password is ever shared with the AI.
    After the user approves in the browser, call tool_login_poll with the device_code.
    """
    global _last_login_start
    now = time.monotonic()
    elapsed = now - _last_login_start
    if elapsed < _LOGIN_START_COOLDOWN_SEC:
        wait = int(_LOGIN_START_COOLDOWN_SEC - elapsed) + 1
        return json.dumps({
            "error": True,
            "code": "RATE_LIMITED",
            "message": f"Please wait {wait} second(s) before requesting a new login code.",
        })
    _last_login_start = now
    try:
        result = await login_start()
        return result.model_dump_json(indent=2)
    except KeycloakAuthError as e:
        return json.dumps({"error": True, "code": e.error, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_login_poll(device_code: str) -> str:
    """
    Poll for login approval after the user visits the URL from tool_login_start.
    If pending=True the user hasn't approved yet — wait the recommended interval
    and call this tool again with the same device_code.
    Returns access_token + refresh_token once the user approves.
    """
    params = LoginPollInput(device_code=device_code)
    try:
        result = await login_poll(params)
        return result.model_dump_json(indent=2)
    except KeycloakAuthError as e:
        return json.dumps({"error": True, "code": e.error, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_refresh_token(refresh_token_value: str) -> str:
    """
    Exchange a refresh_token (from tool_login_poll) for a new access_token.
    Call this when the current access_token is about to expire.
    """
    params = RefreshTokenInput(refresh_token=refresh_token_value)
    try:
        result = await refresh_token(params)
        return result.model_dump_json(indent=2)
    except KeycloakAuthError as e:
        return json.dumps({"error": True, "code": e.error, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_get_my_enrollments(
    user_token: str,
    status_filter: str = "all",
    limit: int = 10,
) -> str:
    """
    Get all courses the logged-in user is enrolled in, with progress percentages.
    Requires access_token from tool_login_poll.
    status_filter: 'all' | 'in_progress' | 'completed' | 'not_started'
    """
    params = GetMyEnrollmentsInput(
        user_token=user_token,
        status_filter=status_filter,
        limit=limit,
    )
    try:
        result = await get_my_enrollments(params)
        return result.model_dump_json(indent=2)
    except InvalidTokenError as e:
        return json.dumps({"error": True, "code": "INVALID_TOKEN", "message": str(e)})
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_enroll_in_course(
    user_token: str,
    course_id: str,
    batch_id: str | None = None,
) -> str:
    """
    Enroll the logged-in user in a course. Auto-selects the first open batch
    if batch_id is not provided. Requires access_token from tool_login_poll.
    """
    params = EnrollInCourseInput(
        user_token=user_token,
        course_id=course_id,
        batch_id=batch_id,
    )
    try:
        result = await enroll_in_course(params)
        return result.model_dump_json(indent=2)
    except InvalidTokenError as e:
        return json.dumps({"error": True, "code": "INVALID_TOKEN", "message": str(e)})
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_track_content_progress(
    user_token: str,
    course_id: str,
    batch_id: str,
    content_id: str,
    status: str = "completed",
    completion_percentage: int = 100,
) -> str:
    """
    Mark a lesson or resource as consumed and update the user's course progress.
    status: 'in_progress' | 'completed'. Requires access_token from tool_login_poll.
    """
    params = TrackContentProgressInput(
        user_token=user_token,
        course_id=course_id,
        batch_id=batch_id,
        content_id=content_id,
        status=status,
        completion_percentage=completion_percentage,
    )
    try:
        result = await track_content_progress(params)
        return result.model_dump_json(indent=2)
    except InvalidTokenError as e:
        return json.dumps({"error": True, "code": "INVALID_TOKEN", "message": str(e)})
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_submit_assessment(
    user_token: str,
    course_id: str,
    batch_id: str,
    content_id: str,
    questions: list[dict],
    total_score: float,
    max_score: float,
    duration_sec: float = 0.0,
) -> str:
    """
    Submit a completed assessment with per-question scores and save progress to profile.
    Fires START + ASSESS (one per question) + END telemetry to analytics.
    Saves score via the assessments[] array so certificates can be issued.

    questions: list of { id, text, index, score, max_score, resvalues, duration }
    Requires access_token from tool_login_poll.
    """
    if len(questions) > 200:
        return json.dumps({
            "error": True,
            "code": "TOO_MANY_QUESTIONS",
            "message": "Cannot submit more than 200 questions in a single assessment.",
        })
    try:
        parsed_questions = [AssessmentQuestion(**q) for q in questions]
        params = SubmitAssessmentInput(
            user_token=user_token,
            course_id=course_id,
            batch_id=batch_id,
            content_id=content_id,
            questions=parsed_questions,
            total_score=total_score,
            max_score=max_score,
            duration_sec=duration_sec,
        )
        result = await submit_assessment(params)
        return result.model_dump_json(indent=2)
    except InvalidTokenError as e:
        return json.dumps({"error": True, "code": "INVALID_TOKEN", "message": str(e)})
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


@mcp.tool()
async def tool_get_my_learning_summary(user_token: str) -> str:
    """
    Get a learning snapshot: total enrolled, completed, in-progress, certificates earned,
    and the 5 most recent courses. Requires access_token from tool_login_poll.
    """
    params = GetMyLearningSummaryInput(user_token=user_token)
    try:
        result = await get_my_learning_summary(params)
        return result.model_dump_json(indent=2)
    except InvalidTokenError as e:
        return json.dumps({"error": True, "code": "INVALID_TOKEN", "message": str(e)})
    except SunbirdApiError as e:
        return json.dumps({"error": True, "code": e.response_code, "message": str(e)})
    except Exception as e:
        return json.dumps({"error": True, "message": f"Unexpected error: {e}"})


# ── Startup ───────────────────────────────────────────────────────────────────

async def main() -> None:
    print("[sunbird-mcp] Resolving channel ID...")
    await resolve_channel_id()
    print("[sunbird-mcp] Registering loggedin Kong consumer token...")
    await resolve_loggedin_kong_token()
    print(f"[sunbird-mcp] Starting server on port {env.MCP_PORT}...")
    await mcp.run_streamable_http_async()


if __name__ == "__main__":
    asyncio.run(main())
