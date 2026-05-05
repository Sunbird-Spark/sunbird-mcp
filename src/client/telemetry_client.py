"""
Telemetry client — fires Sunbird telemetry events to /action/data/v3/telemetry.

Events fired:
  fire_content_telemetry   → START + END  (for regular content consumption)
  fire_assessment_telemetry → START + ASSESS (per question) + END  (for assessments)

The telemetry endpoint lives under /action/ which Kong routes separately from /api/.
We call it via a dedicated httpx client using the same Kong URL base but /action path.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone

import httpx

from config.env import env

_log = logging.getLogger(__name__)

_MAX_TOKEN_LEN = 4096

# Telemetry endpoint — portal uses /action/data/v3/telemetry
_TELEMETRY_PATH = "/action/data/v3/telemetry"

# Derive base URL: strip /api suffix, add nothing (action routes off root)
def _telemetry_base() -> str:
    base = env.KONG_URL.rstrip("/")
    # e.g. https://test.sunbirded.org/api → https://test.sunbirded.org
    if base.endswith("/api"):
        base = base[:-4]
    return base


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _base_event(eid: str, user_id: str, content_id: str, course_id: str, batch_id: str) -> dict:
    return {
        "eid": eid,
        "ets": _now_ms(),
        "ver": "3.0",
        "mid": f"MCP:{uuid.uuid4()}",
        "actor": {"id": user_id, "type": "User"},
        "context": {
            "channel": "mcp",
            "pdata": {"id": env.APP_ID, "ver": "1.0", "pid": "sunbird-mcp"},
            "env": "content",
            "sid": str(uuid.uuid4()),
            "did": "sunbird-mcp-server",
            "cdata": [
                {"id": course_id, "type": "Course"},
                {"id": batch_id, "type": "CourseBatch"},
            ],
            "rollup": {"l1": course_id},
        },
        "object": {
            "id": content_id,
            "type": "Content",
            "ver": "1.0",
            "rollup": {"l1": course_id, "l2": content_id},
        },
        "tags": [],
        "edata": {},
    }


def _start_event(user_id: str, content_id: str, course_id: str, batch_id: str, mode: str = "play") -> dict:
    ev = _base_event("START", user_id, content_id, course_id, batch_id)
    ev["edata"] = {"type": "content", "mode": mode, "pageid": "", "duration": 0}
    return ev


def _end_event(
    user_id: str,
    content_id: str,
    course_id: str,
    batch_id: str,
    duration_sec: float,
    completion_pct: int,
) -> dict:
    ev = _base_event("END", user_id, content_id, course_id, batch_id)
    ev["edata"] = {
        "type": "content",
        "mode": "play",
        "pageid": "",
        "summary": [{"completionpercentage": completion_pct}],
        "duration": round(duration_sec, 2),
    }
    return ev


def _assess_event(
    user_id: str,
    content_id: str,
    course_id: str,
    batch_id: str,
    question: dict,
    score: float,
    max_score: float,
    pass_status: bool,
) -> dict:
    ev = _base_event("ASSESS", user_id, content_id, course_id, batch_id)
    ev["edata"] = {
        "item": {
            "id": question.get("id", ""),
            "title": question.get("text", ""),
            "maxscore": max_score,
            "type": "mcq",
            "exlength": 0,
            "params": [],
        },
        "index": question.get("index", 1),
        "pass": "Yes" if pass_status else "No",
        "score": score,
        "resvalues": question.get("resvalues", []),
        "duration": question.get("duration", 0.0),
    }
    return ev


async def _post_telemetry(events: list[dict], user_token: str) -> None:
    """POST a batch of telemetry events. Failures are logged but never block progress."""
    if not events:
        return

    # Guard against malformed or oversized tokens before sending
    if not user_token or len(user_token) > _MAX_TOKEN_LEN:
        _log.debug("telemetry: skipping — invalid user_token (empty or too long)")
        return

    payload = {
        "id": "api.telemetry",
        "ver": "3.0",
        "params": {"msgid": str(uuid.uuid4())},
        "ets": _now_ms(),
        "events": events,
    }
    headers = {
        "Authorization": f"Bearer {env.KONG_ANONYMOUS_TOKEN}",
        "x-authenticated-user-token": user_token,
        "Content-Type": "application/json",
        "X-App-Id": env.APP_ID,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_telemetry_base()}{_TELEMETRY_PATH}",
                json=payload,
                headers=headers,
            )
            if resp.status_code >= 400:
                _log.warning(
                    "telemetry rejected: status=%d body=%.200s",
                    resp.status_code,
                    resp.text,
                )
    except httpx.TimeoutException:
        _log.debug("telemetry POST timed out (non-fatal)")
    except Exception as exc:
        _log.debug("telemetry POST failed (non-fatal): %s", exc)


async def fire_content_telemetry(
    user_id: str,
    content_id: str,
    course_id: str,
    batch_id: str,
    status: str,
    user_token: str,
    duration_sec: float = 0.0,
    completion_pct: int = 100,
) -> None:
    """Fire START + END events for regular content (video, pdf, epub, etc.)."""
    events = [
        _start_event(user_id, content_id, course_id, batch_id),
        _end_event(user_id, content_id, course_id, batch_id, duration_sec, completion_pct),
    ]
    await _post_telemetry(events, user_token)


async def fire_assessment_telemetry(
    user_id: str,
    content_id: str,
    course_id: str,
    batch_id: str,
    user_token: str,
    questions_attempted: list[dict],
    total_score: float,
    max_score: float,
    duration_sec: float = 0.0,
) -> None:
    """
    Fire START + one ASSESS per question + END for assessment content.
    questions_attempted items:
      { id, text, index, score, max_score, resvalues, duration }
    """
    events: list[dict] = [_start_event(user_id, content_id, course_id, batch_id, mode="assess")]

    for q in questions_attempted:
        q_score = float(q.get("score", 0))
        q_max = float(q.get("max_score", 1))
        events.append(
            _assess_event(
                user_id, content_id, course_id, batch_id,
                question=q,
                score=q_score,
                max_score=q_max,
                pass_status=q_score >= q_max,
            )
        )

    completion_pct = int((total_score / max_score * 100)) if max_score > 0 else 0
    events.append(
        _end_event(user_id, content_id, course_id, batch_id, duration_sec, completion_pct)
    )
    await _post_telemetry(events, user_token)
