"""
Pydantic v2 models for all tools (anonymous + authenticated).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ── Tool 1: search_content ────────────────────────────────────────────────────

class SearchContentInput(BaseModel):
    query: str = Field(..., min_length=1, description="Keywords to search for")
    content_type: Literal["Course", "Resource", "Collection", "QuestionSet"] | None = Field(
        default=None, description="Filter by content type"
    )
    language: str | None = Field(default=None, description="e.g. English, Hindi")
    limit: int = Field(default=10, ge=1, le=50)


class SearchResultItem(BaseModel):
    id: str
    name: str
    description: str
    type: str
    mime_type: str
    thumbnail_url: str
    language: str
    framework: str


class SearchContentOutput(BaseModel):
    total: int
    results: list[SearchResultItem]
    message: str | None = None


# ── Tool 2: get_course_outline ────────────────────────────────────────────────

class GetCourseOutlineInput(BaseModel):
    course_id: str = Field(
        ..., min_length=1, description="Sunbird content identifier, e.g. do_xxxxx"
    )
    batch_id: str | None = Field(
        default=None, description="Enrolled batch ID; enables consume_url per lesson"
    )


class OutlineLesson(BaseModel):
    id: str
    name: str
    type: str
    mime_type: str
    estimated_minutes: float | None
    consume_url: str | None = None


class OutlineUnit(BaseModel):
    name: str
    lesson_count: int
    lessons: list[OutlineLesson]


class GetCourseOutlineOutput(BaseModel):
    course_id: str
    course_name: str
    description: str
    total_units: int
    units: list[OutlineUnit]


# ── Tool 3: get_quiz_questions ────────────────────────────────────────────────

class GetQuizQuestionsInput(BaseModel):
    question_set_id: str = Field(
        ..., min_length=1, description="Sunbird question set identifier"
    )


class QuizOption(BaseModel):
    label: str
    value: str


class QuizQuestion(BaseModel):
    id: str
    text: str
    options: list[QuizOption]
    correct_answer: str
    max_score: float
    hint: str | None


class GetQuizQuestionsOutput(BaseModel):
    question_set_id: str
    title: str
    total_questions: int
    questions: list[QuizQuestion]


# ── Tool 4: build_learning_path ───────────────────────────────────────────────

class BuildLearningPathInput(BaseModel):
    topic: str = Field(..., min_length=1, description="Skill or subject to build a path for")
    level: Literal["beginner", "intermediate", "advanced"] | None = None
    language: str = Field(default="English")
    max_courses: int = Field(default=5, ge=1, le=10)


class CoursePathItem(BaseModel):
    order: int
    course_id: str
    name: str
    why: str
    estimated_hours: float
    unit_count: int
    has_batch: bool


class BuildLearningPathOutput(BaseModel):
    topic: str
    total_courses: int
    path: list[CoursePathItem]
    summary: str


# ── Tool 5: navigate_course ───────────────────────────────────────────────────

class NavigateCourseInput(BaseModel):
    goal: str = Field(
        ...,
        min_length=1,
        description='What the user wants to learn, e.g. "I want to learn Apache Flink"',
    )
    language: str = Field(default="English")
    max_results: int = Field(default=3, ge=1, le=5)


class LessonItem(BaseModel):
    id: str
    name: str
    type: str
    mime_type: str


class UnitOutline(BaseModel):
    unit_name: str
    relevant: bool
    lesson_count: int
    lessons: list[LessonItem]


class CourseNavResult(BaseModel):
    course_id: str
    name: str
    description: str
    relevance_score: int
    total_units: int
    estimated_hours: float
    outline: list[UnitOutline]


class NavigateCourseOutput(BaseModel):
    goal: str
    search_query: str
    courses_found: int
    courses: list[CourseNavResult]
    suggestion: str


# ── Tool 6 (anon): get_batch_list ────────────────────────────────────────────

class GetBatchListInput(BaseModel):
    course_id: str = Field(..., min_length=1, description="Sunbird course identifier")
    status: Literal["all", "upcoming", "active", "expired"] = Field(
        default="active", description="Filter by batch status"
    )


class BatchItem(BaseModel):
    batch_id: str
    name: str
    status: Literal["upcoming", "active", "expired"]
    enrollment_type: str
    start_date: str
    end_date: str
    enrollment_end_date: str
    created_by: str
    is_enrollable: bool


class GetBatchListOutput(BaseModel):
    course_id: str
    total: int
    batches: list[BatchItem]


# ── Tool 7a (auth): login_start — Device Code Flow (RFC 8628) ─────────────────

class LoginStartOutput(BaseModel):
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int
    message: str


# ── Tool 7b (auth): login_poll — Device Code Flow (RFC 8628) ──────────────────

class LoginPollInput(BaseModel):
    device_code: str = Field(..., min_length=1, description="device_code returned by tool_login_start")


class LoginPollOutput(BaseModel):
    success: bool
    pending: bool
    user_id: str
    user_name: str
    access_token: str
    refresh_token: str
    expires_in: int
    message: str


# ── Tool 7c (auth): refresh_token ─────────────────────────────────────────────

class RefreshTokenInput(BaseModel):
    refresh_token: str = Field(..., min_length=1, description="Refresh token from tool_login_poll")


class RefreshTokenOutput(BaseModel):
    success: bool
    access_token: str
    refresh_token: str
    expires_in: int
    message: str


# ── Tool 8 (auth): get_my_enrollments ────────────────────────────────────────

class GetMyEnrollmentsInput(BaseModel):
    user_token: str = Field(..., min_length=1, description="Access token from tool_login_poll")
    status_filter: Literal["all", "in_progress", "completed", "not_started"] = Field(
        default="all", description="Filter by enrollment status"
    )
    limit: int = Field(default=10, ge=1, le=50)


class EnrolledCourse(BaseModel):
    course_id: str
    course_name: str
    completion_percentage: float
    status: Literal["not_started", "in_progress", "completed"]
    enrolled_date: str
    has_certificate: bool
    batch_id: str = ""
    consume_url: str | None = None


class GetMyEnrollmentsOutput(BaseModel):
    user_id: str
    total: int
    courses: list[EnrolledCourse]
    message: str | None = None


# ── Tool 9 (auth): enroll_in_course ──────────────────────────────────────────

class EnrollInCourseInput(BaseModel):
    user_token: str = Field(..., min_length=1, description="Access token from tool_login_poll")
    course_id: str = Field(..., min_length=1, description="Sunbird course identifier")
    batch_id: str | None = Field(
        default=None, description="Specific batch ID; auto-selects open batch if omitted"
    )


class EnrollInCourseOutput(BaseModel):
    success: bool
    course_id: str
    batch_id: str
    message: str
    consume_url: str | None = None


# ── Tool 10 (auth): track_content_progress ───────────────────────────────────

class TrackContentProgressInput(BaseModel):
    user_token: str = Field(..., min_length=1, description="Access token from tool_login_poll")
    course_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    content_id: str = Field(..., min_length=1, description="Lesson or resource identifier")
    status: Literal["in_progress", "completed"] = "completed"
    completion_percentage: int = Field(default=100, ge=0, le=100)


class TrackContentProgressOutput(BaseModel):
    success: bool
    content_id: str
    course_id: str
    new_status: str
    message: str


# ── Tool 11 (auth): submit_assessment ────────────────────────────────────────

class AssessmentQuestion(BaseModel):
    id: str = Field(..., min_length=1, description="Question identifier")
    text: str = Field(default="", description="Question text (for telemetry)")
    index: int = Field(default=1, ge=1, description="Question position in the assessment")
    score: float = Field(default=0.0, ge=0, description="Score achieved on this question")
    max_score: float = Field(default=1.0, ge=0, description="Maximum possible score")
    resvalues: list[dict] = Field(default_factory=list, description="User's response values")
    duration: float = Field(default=0.0, ge=0, description="Time spent on question in seconds")


class SubmitAssessmentInput(BaseModel):
    user_token: str = Field(..., min_length=1, description="Access token from tool_login_poll")
    course_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    content_id: str = Field(..., min_length=1, description="Assessment content identifier")
    questions: list[AssessmentQuestion] = Field(
        ..., min_length=1, max_length=200, description="List of attempted questions with scores (max 200)"
    )
    total_score: float = Field(..., ge=0, description="Total score achieved")
    max_score: float = Field(..., gt=0, description="Maximum possible total score")
    duration_sec: float = Field(default=0.0, ge=0, description="Total time spent in seconds")


class SubmitAssessmentOutput(BaseModel):
    success: bool
    content_id: str
    course_id: str
    total_score: float
    max_score: float
    percentage: float
    pass_status: bool
    telemetry_fired: bool
    message: str


# ── Tool 12 (auth): get_my_learning_summary ───────────────────────────────────

class GetMyLearningSummaryInput(BaseModel):
    user_token: str = Field(..., min_length=1, description="Access token from tool_login_poll")


class GetMyLearningSummaryOutput(BaseModel):
    user_id: str
    total_enrolled: int
    completed: int
    in_progress: int
    not_started: int
    certificates_earned: int
    recent_courses: list[EnrolledCourse]
    message: str | None = None
