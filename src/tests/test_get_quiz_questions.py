import json
import pytest
import respx
from httpx import Response

from schemas.tool_schemas import GetQuizQuestionsInput
from tools.get_quiz_questions import get_quiz_questions, _collect_question_ids, _parse_ecml_body
from config.env import env

# Probe response: a v2 QuestionSet (not SelfAssess)
MOCK_QUESTIONSET_PROBE = {
    "result": {"content": {"identifier": "qs_001", "name": "Flink Practice Quiz",
                           "contentType": "QuestionSet", "objectType": "QuestionSet"}}
}

# Probe response: a SelfAssess content
MOCK_SELFASSESS_PROBE = {
    "result": {
        "content": {
            "identifier": "sa_001",
            "name": "Quiz 0604",
            "contentType": "SelfAssess",
            "objectType": "Content",
            "primaryCategory": "Course Assessment",
            "questions": [
                {"identifier": "ai_001", "objectType": "AssessmentItem"},
                {"identifier": "ai_002", "objectType": "AssessmentItem"},
            ],
        }
    }
}

MOCK_MCQ_ITEM = {
    "result": {
        "assessment_item": {
            "identifier": "ai_001",
            "type": "mcq",
            "maxScore": 1,
            "body": json.dumps({
                "data": {
                    "data": {
                        "question": {"text": "<p>Which is not a wonder?</p>", "hint": "Think about it"},
                        "options": [
                            {"text": "<p>Taj Mahal</p>", "isCorrect": False},
                            {"text": "<p>Statue of Liberty</p>", "isCorrect": True},
                            {"text": "<p>Great Wall</p>", "isCorrect": False},
                        ],
                    }
                }
            }),
        }
    }
}

MOCK_MTF_ITEM = {
    "result": {
        "assessment_item": {
            "identifier": "ai_002",
            "type": "mtf",
            "maxScore": 2,
            "body": json.dumps({
                "data": {
                    "data": {
                        "question": {"text": "<p>Match the following</p>"},
                        "option": {
                            "optionsLHS": [{"text": "<p>A</p>"}, {"text": "<p>B</p>"}],
                            "optionsRHS": [{"text": "<p>1</p>"}, {"text": "<p>2</p>"}],
                        },
                    }
                }
            }),
        }
    }
}

MOCK_HIERARCHY = {
    "result": {
        "questionSet": {
            "identifier": "qs_001",
            "name": "Flink Practice Quiz",
            "objectType": "QuestionSet",
            "children": [
                {
                    "identifier": "q_001",
                    "objectType": "Question",
                    "name": "Q1",
                },
                {
                    "identifier": "section_1",
                    "objectType": "Section",
                    "children": [
                        {"identifier": "q_002", "objectType": "Question", "name": "Q2"},
                        {"identifier": "q_003", "objectType": "Question", "name": "Q3"},
                    ],
                },
            ],
        }
    }
}

MOCK_QUESTION_LIST = {
    "result": {
        "questions": [
            {
                "identifier": "q_001",
                "body": "<p>What is Flink?</p>",
                "maxScore": 1,
                "interactions": {
                    "response1": {"correctResponse": {"value": "0"}},
                    "options": [
                        {"label": "A stream processor", "value": "0"},
                        {"label": "A database", "value": "1"},
                    ],
                },
                "hints": {"h1": "Think about real-time data"},
            },
            {
                "identifier": "q_002",
                "body": "<p>What is a DataStream?</p>",
                "maxScore": 2,
                "interactions": {
                    "response1": {"correctResponse": {"value": "1"}},
                    "options": [
                        {"label": "A static dataset", "value": "0"},
                        {"label": "An unbounded sequence of records", "value": "1"},
                    ],
                },
                "hints": {},
            },
            {
                "identifier": "q_003",
                "body": "<p>Flink supports stateful processing?</p>",
                "maxScore": 1,
                "interactions": {
                    "response1": {"correctResponse": {"value": "0"}},
                    "options": [
                        {"label": "True", "value": "0"},
                        {"label": "False", "value": "1"},
                    ],
                },
            },
        ]
    }
}


def test_collect_question_ids():
    ids = _collect_question_ids(MOCK_HIERARCHY["result"]["questionSet"])
    assert ids == ["q_001", "q_002", "q_003"]


@respx.mock
async def test_get_quiz_questions_v2_full():
    """Path A: QuestionSet v2 format."""
    respx.get(f"{env.KONG_URL}/content/v1/read/qs_001").mock(
        return_value=Response(200, json=MOCK_QUESTIONSET_PROBE)
    )
    respx.get(f"{env.KONG_URL}/questionset/v2/hierarchy/qs_001").mock(
        return_value=Response(200, json=MOCK_HIERARCHY)
    )
    respx.post(f"{env.KONG_URL}/question/v2/list").mock(
        return_value=Response(200, json=MOCK_QUESTION_LIST)
    )

    params = GetQuizQuestionsInput(question_set_id="qs_001")
    result = await get_quiz_questions(params)

    assert result.question_set_id == "qs_001"
    assert result.title == "Flink Practice Quiz"
    assert result.total_questions == 3

    q1 = result.questions[0]
    assert q1.id == "q_001"
    assert q1.text == "<p>What is Flink?</p>"
    assert len(q1.options) == 2
    assert q1.correct_answer == "A stream processor"
    assert q1.max_score == 1.0
    assert q1.hint == "Think about real-time data"

    q2 = result.questions[1]
    assert q2.correct_answer == "An unbounded sequence of records"
    assert q2.max_score == 2.0
    assert q2.hint is None

    q3 = result.questions[2]
    assert q3.correct_answer == "True"


@respx.mock
async def test_get_quiz_questions_v2_empty():
    """Path A: QuestionSet v2 with no questions."""
    respx.get(f"{env.KONG_URL}/content/v1/read/qs_empty").mock(
        return_value=Response(200, json={
            "result": {"content": {"identifier": "qs_empty", "name": "Empty Quiz",
                                   "contentType": "QuestionSet", "objectType": "QuestionSet"}}
        })
    )
    respx.get(f"{env.KONG_URL}/questionset/v2/hierarchy/qs_empty").mock(
        return_value=Response(200, json={
            "result": {"questionSet": {"identifier": "qs_empty", "name": "Empty Quiz", "children": []}}
        })
    )

    params = GetQuizQuestionsInput(question_set_id="qs_empty")
    result = await get_quiz_questions(params)

    assert result.total_questions == 0
    assert result.questions == []


@respx.mock
async def test_get_quiz_questions_selfassess():
    """Path B: SelfAssess (ECML) format — MCQ and MTF items."""
    respx.get(f"{env.KONG_URL}/content/v1/read/sa_001").mock(
        return_value=Response(200, json=MOCK_SELFASSESS_PROBE)
    )
    respx.get(f"{env.KONG_URL}/assessment/v1/items/read/ai_001").mock(
        return_value=Response(200, json=MOCK_MCQ_ITEM)
    )
    respx.get(f"{env.KONG_URL}/assessment/v1/items/read/ai_002").mock(
        return_value=Response(200, json=MOCK_MTF_ITEM)
    )

    params = GetQuizQuestionsInput(question_set_id="sa_001")
    result = await get_quiz_questions(params)

    assert result.title == "Quiz 0604"
    assert result.total_questions == 2

    q1 = result.questions[0]
    assert q1.id == "ai_001"
    assert "Which is not a wonder" in q1.text
    assert len(q1.options) == 3
    assert q1.correct_answer == "<p>Statue of Liberty</p>"
    assert q1.hint == "Think about it"

    q2 = result.questions[1]
    assert q2.id == "ai_002"
    assert len(q2.options) == 2         # 2 LHS→RHS pairs
    assert "→" in q2.options[0].label


def test_parse_ecml_body_mcq():
    """Unit test for ECML MCQ parser."""
    body = json.dumps({
        "data": {
            "data": {
                "question": {"text": "<p>Capital of France?</p>", "hint": "European city"},
                "options": [
                    {"text": "<p>London</p>", "isCorrect": False},
                    {"text": "<p>Paris</p>", "isCorrect": True},
                ],
            }
        }
    })
    text, options, correct, hint = _parse_ecml_body(body)
    assert "France" in text
    assert len(options) == 2
    assert correct == "<p>Paris</p>"
    assert hint == "European city"
