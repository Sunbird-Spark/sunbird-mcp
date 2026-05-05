# Sunbird Spark MCP

A Model Context Protocol (MCP) server that bridges Claude (or any MCP-compatible AI) to a Sunbird learning platform. Exposes **13 tools** — 6 anonymous read-only tools and 7 authenticated tools for personalised learning — over a stateless HTTP transport.

---

## Tools

### Anonymous (no login required)

| # | Tool | What You Can Ask |
|---|------|-----------------|
| 1 | `tool_search_content` | *"Find data engineering courses in English"* |
| 2 | `tool_get_course_outline` | *"Show me the structure of course do_xxxxx"* |
| 3 | `tool_get_quiz_questions` | *"Quiz me on the assessment in this course"* |
| 4 | `tool_build_learning_path` | *"Build a beginner learning path for Apache Kafka"* |
| 5 | `tool_navigate_course` | *"I want to learn stream processing — where do I start?"* |
| 6 | `tool_get_batch_list` | *"What batches are open for course do_xxxxx?"* |

### Authenticated (requires login)

| # | Tool | What You Can Ask |
|---|------|-----------------|
| 7 | `tool_login_start` | *"Log me in"* — starts device-code flow, returns URL + code |
| 8 | `tool_login_poll` | *"Check if I've logged in"* — polls until approved, returns tokens |
| 9 | `tool_refresh_token` | *"Refresh my session"* — exchanges refresh token for new access token |
| 10 | `tool_get_my_enrollments` | *"Show my enrolled courses with progress"* |
| 11 | `tool_enroll_in_course` | *"Enrol me in this course"* |
| 12 | `tool_track_content_progress` | *"Mark this lesson as completed"* |
| 13 | `tool_get_my_learning_summary` | *"Give me my learning dashboard"* |
| 14 | `tool_submit_assessment` | *"Submit my quiz results"* |

---

## Authentication Design

Login uses **RFC 8628 OAuth 2.0 Device Authorization Flow** via Keycloak.  
**The user's password never passes through the MCP layer or the AI.**

```
1. tool_login_start()
   → MCP asks Keycloak for a device code
   → Returns: { user_code, verification_uri, device_code, expires_in }

2. User opens verification_uri in their browser, enters user_code, authenticates with Keycloak directly.

3. tool_login_poll(device_code)
   → Polls Keycloak until user approves
   → Returns: { access_token, refresh_token, expires_in }

4. Pass access_token to any authenticated tool.
   Kong gateway validates the token server-side on every request.

5. tool_refresh_token(refresh_token)  — when access_token nears expiry
```

---

## Architecture

```
Claude / MCP Client
       │  POST /mcp  (Streamable HTTP, stateless)
       ▼
 ┌─────────────────────────────────────────────────────────┐
 │  FastMCP Server  :3002                                  │
 │                                                         │
 │  Anonymous Tools (6)          Authenticated Tools (7)   │
 │  ─────────────────            ──────────────────────    │
 │  search_content               login_start  ──────────┐  │
 │  get_course_outline           login_poll   ──────────┤  │
 │  get_quiz_questions           refresh_token ─────────┤  │
 │  build_learning_path          get_my_enrollments      │  │
 │  navigate_course              enroll_in_course        │  │
 │  get_batch_list               track_content_progress  │  │
 │                               get_my_learning_summary │  │
 │                               submit_assessment       │  │
 └──────────────┬────────────────────────┬───────────────┘  │
                │                        │                   │
                │ anon bearer            │ anon bearer       │
                │                        │ + x-authenticated │
                │                        │   -user-token     │
                ▼                        ▼                   │
        Sunbird Kong Gateway ◄───────────┘                   │
                │                                            │
                ▼                                            ▼
       Sunbird Backend APIs                Keycloak (device auth)
                │
                ▼
  Telemetry  /action/data/v3/telemetry
```

**Key architectural decisions:**

| Decision | Choice | Reason |
|----------|--------|--------|
| Transport | Streamable HTTP | Supports multiple concurrent clients; MCP spec 2025-03-26+ |
| Session mode | Stateless | No server-side session state; each call is self-contained |
| Auth flow | RFC 8628 device code | Password never touches AI layer; works with Keycloak out of the box |
| Token validation | Kong server-side | Kong plugin validates JWT against Keycloak JWKS; no client-side crypto needed |
| Anonymous token | Per-request header | Allows token rotation without server restart |
| Channel ID | Resolved once at startup, cached | Avoids per-request org search overhead |
| Level filter | Score-based, not API filter | Sunbird ES maps `level` as numeric; string filter returns HTTP 500 |
| Parallel fetches | `asyncio.gather(return_exceptions=True)` | One failed hierarchy fetch never kills the full response |
| Question format | Auto-detected | Handles QuestionSet v2 and legacy SelfAssess (ECML) transparently |

---

## Security

- **HTTPS enforced at startup** — `KONG_URL` and `KEYCLOAK_ISSUER_URL` reject `http://` (localhost allowed for dev)
- **No credentials in git** — `.env` is gitignored; use `.env.example` as the template
- **JWT format validated** — malformed tokens raise a typed `InvalidTokenError` immediately, not silently
- **Assessment input bounded** — maximum 200 questions per submission
- **Login rate-limited** — 5-second cooldown between `tool_login_start` calls
- **Telemetry non-blocking** — failures are logged (not swallowed silently) and never interrupt tool execution
- **Device-code login** — no password ever flows through the AI conversation

---

## Requirements

- Python 3.11+
- A running Sunbird instance with Kong gateway
- Keycloak with OAuth 2.0 Device Authorization Grant enabled (for auth tools)

---

## Setup

**1. Clone and create a virtual environment**

```bash
git clone <repo-url>
cd sunbird-spark-mcp
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

**2. Install dependencies**

```bash
pip install -r src/requirements.txt
```

**3. Configure environment**

```bash
cp src/.env.example src/.env
```

Edit `src/.env` with your values (see `.env.example` for all variables):

```dotenv
KONG_URL=https://your-sunbird-instance/api
KONG_ANONYMOUS_TOKEN=eyJhbGci...
KEYCLOAK_ISSUER_URL=https://your-keycloak/auth/realms/sunbird
KEYCLOAK_CLIENT_ID=android
MCP_PORT=3002
```

**4. Start the server**

```bash
cd src
python server.py
```

```
[sunbird-mcp] Resolving channel ID...
[sunbird-mcp] Channel ID resolved: 0145163485727375366
[sunbird-mcp] Starting server on port 3002...
INFO: Uvicorn running on http://0.0.0.0:3002 (Press CTRL+C to quit)
```

---

## Connecting to Claude

### Claude Code (VS Code / Terminal)

```bash
claude mcp add --transport http sunbird-spark-py http://localhost:3002/mcp
claude mcp list
# sunbird-spark-py: http://localhost:3002/mcp (HTTP) ✓ Connected
```

Usage:
```
> Build a learning path for Apache Kafka for beginners
> Log me in
> Show my enrolled courses
> Enrol me in course do_xxxxx
```

### Claude Desktop

Claude Desktop only supports stdio-based MCP servers. Use the included `mcp-remote-wrapper.sh` to bridge to the HTTP server.

**Step 1 — Install mcp-remote under Node 20+**

```bash
# Find your Node 20+ path (example using nvm)
ls ~/.nvm/versions/node/
# pick any version >= v20.18.1, e.g. v20.19.4

PREFIX=~/.nvm/versions/node/v20.19.4 \
  ~/.nvm/versions/node/v20.19.4/bin/npm install -g mcp-remote
```

**Step 2 — Make the wrapper executable**

```bash
chmod +x ~/sunbird-spark-mcp/mcp-remote-wrapper.sh
```

The wrapper at `mcp-remote-wrapper.sh` already points to the Node binary. If you used a different Node version, update the path inside it.

**Step 3 — Edit the Claude Desktop config**

`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sunbird-spark-py": {
      "command": "/Users/YOUR_USERNAME/sunbird-spark-mcp/mcp-remote-wrapper.sh",
      "args": ["http://localhost:3002/mcp"]
    }
  }
}
```

Replace `YOUR_USERNAME` with your macOS username (`whoami`).

**Step 4 — Restart Claude Desktop** (Cmd+Q and reopen)

Verify:
```bash
tail -50 ~/Library/Logs/Claude/mcp-server-sunbird-spark-py.log
# Connected to remote server using StreamableHTTPClientTransport
# Proxy established successfully
```

### Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "sunbird-spark-py": {
      "url": "http://localhost:3002/mcp"
    }
  }
}
```

---

## Tool Reference

### `tool_search_content`
Full-text search across all live Sunbird content.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `query` | string | ✅ | — | Keywords to search for |
| `content_type` | string | ❌ | — | `Course`, `Resource`, `Collection`, `QuestionSet` |
| `language` | string | ❌ | — | e.g. `English`, `Hindi` |
| `limit` | integer | ❌ | 10 | 1–50 |

---

### `tool_get_course_outline`
Full unit/lesson hierarchy of a course.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `course_id` | string | ✅ | Sunbird content ID, e.g. `do_xxxxx` |

> Missing `mimeType` leaves are enriched via parallel `/content/v1/read` calls.

---

### `tool_get_quiz_questions`
Fetches all questions from a question set for a conversational quiz.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `question_set_id` | string | ✅ | Question set or SelfAssess ID |

Supports two formats automatically:
- **QuestionSet v2** (`objectType: QuestionSet`) — `/questionset/v2/hierarchy` + `/question/v2/list`
- **SelfAssess / ECML** — `/content/v1/read` + `/assessment/v1/items/read`; parses MCQ, Match-the-Following, and word-arrangement types

---

### `tool_build_learning_path`
Ordered, scored course set for a topic or skill.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `topic` | string | ✅ | — | Skill or subject |
| `level` | string | ❌ | — | `beginner`, `intermediate`, `advanced` |
| `language` | string | ❌ | `English` | — |
| `max_courses` | integer | ❌ | 5 | 1–10 |

Scoring: +3 name match, +1 description match, +2 level match, +1 language match.

---

### `tool_navigate_course`
Goal-driven course navigator with tagged unit outlines.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `goal` | string | ✅ | — | e.g. `I want to learn Apache Flink` |
| `language` | string | ❌ | `English` | — |
| `max_results` | integer | ❌ | 3 | 1–5 |

---

### `tool_get_batch_list`
Lists all batches for a course with enrollment status.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `course_id` | string | ✅ | — | Sunbird course ID |
| `status` | string | ❌ | `active` | `active`, `upcoming`, `expired`, `all` |

---

### `tool_login_start`
Starts device-code login. Returns `user_code` + `verification_uri` to show the user.  
No parameters. Rate-limited to one call per 5 seconds.

---

### `tool_login_poll`
Polls for login approval.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `device_code` | string | ✅ | `device_code` from `tool_login_start` |

Returns `access_token`, `refresh_token`, `expires_in` once approved. Returns `pending: true` while waiting — call again after the recommended interval.

---

### `tool_refresh_token`
Exchanges a refresh token for a new access token.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `refresh_token_value` | string | ✅ | `refresh_token` from `tool_login_poll` |

---

### `tool_get_my_enrollments`
All enrolled courses with completion percentages.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `user_token` | string | ✅ | — | Access token from `tool_login_poll` |
| `status_filter` | string | ❌ | `all` | `all`, `in_progress`, `completed`, `not_started` |
| `limit` | integer | ❌ | 10 | 1–50 |

---

### `tool_enroll_in_course`
Enrols the user in a course. Auto-selects the first open batch if `batch_id` is omitted.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_token` | string | ✅ | Access token |
| `course_id` | string | ✅ | Sunbird course ID |
| `batch_id` | string | ❌ | Specific batch; auto-selected if omitted |

---

### `tool_track_content_progress`
Marks a lesson or resource as consumed and updates course progress.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `user_token` | string | ✅ | — | Access token |
| `course_id` | string | ✅ | — | — |
| `batch_id` | string | ✅ | — | — |
| `content_id` | string | ✅ | — | Lesson/resource ID |
| `status` | string | ❌ | `completed` | `in_progress` or `completed` |
| `completion_percentage` | integer | ❌ | 100 | 0–100 |

---

### `tool_get_my_learning_summary`
Learning snapshot: enrolled, completed, in-progress counts + last 5 courses.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_token` | string | ✅ | Access token |

---

### `tool_submit_assessment`
Submits a completed assessment with per-question scores and fires telemetry.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `user_token` | string | ✅ | Access token |
| `course_id` | string | ✅ | — |
| `batch_id` | string | ✅ | — |
| `content_id` | string | ✅ | Assessment content ID |
| `questions` | list | ✅ | Max 200 items. Each: `{ id, text, index, score, max_score, resvalues, duration }` |
| `total_score` | float | ✅ | Total score achieved |
| `max_score` | float | ✅ | Maximum possible score |
| `duration_sec` | float | ❌ | Total time spent in seconds |

Fires: `START` + `ASSESS` (one per question) + `END` to `/action/data/v3/telemetry`.

---

## Testing

```bash
cd src
source ../venv/bin/activate
python -m pytest tests/ -v
```

Tests use `respx` to mock all HTTP calls — no real Sunbird connection needed.

---

## Project Structure

```
sunbird-spark-mcp/
├── mcp-remote-wrapper.sh           # Bridge for Claude Desktop (stdio → HTTP)
└── src/
    ├── server.py                   # FastMCP entry point, all 13 tool registrations
    ├── .env                        # Your credentials (gitignored — never commit)
    ├── .env.example                # Template — copy to .env and fill in values
    ├── requirements.txt            # Python dependencies
    ├── pytest.ini                  # Test configuration
    ├── conftest.py                 # Test fixtures and sys.path setup
    ├── config/
    │   └── env.py                  # Pydantic-settings env validation (HTTPS enforced)
    ├── client/
    │   ├── sunbird_client.py       # httpx async client, Keycloak device flow, JWT helpers
    │   └── telemetry_client.py     # Sunbird telemetry event builder and poster
    ├── schemas/
    │   └── tool_schemas.py         # Pydantic v2 input/output models for all 13 tools
    ├── tools/
    │   ├── search_content.py
    │   ├── get_course_outline.py
    │   ├── get_quiz_questions.py
    │   ├── build_learning_path.py
    │   ├── navigate_course.py
    │   ├── get_batch_list.py
    │   ├── login_start.py
    │   ├── login_poll.py
    │   ├── refresh_token.py
    │   ├── get_my_enrollments.py
    │   ├── enroll_in_course.py
    │   ├── track_content_progress.py
    │   ├── get_my_learning_summary.py
    │   └── submit_assessment.py
    └── tests/
        ├── test_search_content.py
        ├── test_get_course_outline.py
        ├── test_get_quiz_questions.py
        ├── test_build_learning_path.py
        ├── test_navigate_course.py
        ├── test_get_batch_list.py (if present)
        ├── test_login_start.py
        ├── test_login_poll.py
        ├── test_refresh_token.py
        ├── test_enroll_in_course.py
        ├── test_get_my_enrollments.py
        ├── test_get_my_learning_summary.py
        └── test_track_content_progress.py
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `mcp[cli]` | ≥1.6.0 | MCP server SDK (FastMCP + Streamable HTTP transport) |
| `httpx` | ≥0.27.0 | Async HTTP client for Kong and Keycloak calls |
| `pydantic` | ≥2.7.0 | Input/output schema validation |
| `pydantic-settings` | ≥2.3.0 | Typed env var loading with fail-fast HTTPS validation |
| `python-dotenv` | ≥1.0.0 | `.env` file loading |
| `pytest` + `pytest-asyncio` + `respx` | — | Async tests with mocked HTTP |
