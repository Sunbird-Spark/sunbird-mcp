import pytest
import respx
from httpx import Response

from schemas.tool_schemas import GetCourseOutlineInput
from tools.get_course_outline import get_course_outline
from config.env import env

MOCK_HIERARCHY = {
    "result": {
        "content": {
            "identifier": "do_123",
            "name": "Apache Flink Fundamentals",
            "description": "Comprehensive Flink course",
            "children": [
                {
                    "identifier": "unit_1",
                    "name": "Unit 1: Intro",
                    "contentType": "CourseUnit",
                    "children": [
                        {
                            "identifier": "res_1",
                            "name": "Lesson 1",
                            "contentType": "Resource",
                            "mimeType": "video/mp4",
                            "duration": 1200,
                        },
                        {
                            "identifier": "res_2",
                            "name": "Lesson 2",
                            "contentType": "Resource",
                            "mimeType": "",       # missing — should trigger batch fetch
                            "duration": None,
                        },
                    ],
                },
                {
                    "identifier": "unit_2",
                    "name": "Unit 2: Deep Dive",
                    "contentType": "CourseUnit",
                    "children": [
                        {
                            "identifier": "res_3",
                            "name": "Lesson 3",
                            "contentType": "Resource",
                            "mimeType": "application/pdf",
                            "duration": 600,
                        },
                    ],
                },
            ],
        }
    }
}

MOCK_CONTENT_READ = {
    "result": {"content": {"identifier": "res_2", "mimeType": "video/webm", "duration": 900}}
}


@respx.mock
async def test_get_course_outline_full_tree():
    respx.get(f"{env.KONG_URL}/course/v1/hierarchy/do_123").mock(
        return_value=Response(200, json=MOCK_HIERARCHY)
    )
    # Batch fetch for res_2 (missing mimeType)
    respx.get(f"{env.KONG_URL}/content/v1/read/res_2?fields=mimeType,duration").mock(
        return_value=Response(200, json=MOCK_CONTENT_READ)
    )

    params = GetCourseOutlineInput(course_id="do_123")
    result = await get_course_outline(params)

    assert result.course_id == "do_123"
    assert result.course_name == "Apache Flink Fundamentals"
    assert result.total_units == 2

    unit1 = result.units[0]
    assert unit1.name == "Unit 1: Intro"
    assert unit1.lesson_count == 2

    lesson1 = unit1.lessons[0]
    assert lesson1.id == "res_1"
    assert lesson1.mime_type == "video/mp4"
    assert lesson1.estimated_minutes == 20.0   # 1200 / 60

    # res_2 had empty mimeType — should be filled from batch fetch
    lesson2 = unit1.lessons[1]
    assert lesson2.id == "res_2"
    assert lesson2.mime_type == "video/webm"

    unit2 = result.units[1]
    assert unit2.lesson_count == 1
    assert unit2.lessons[0].estimated_minutes == 10.0   # 600 / 60


@respx.mock
async def test_get_course_outline_empty_course():
    respx.get(f"{env.KONG_URL}/course/v1/hierarchy/do_missing").mock(
        return_value=Response(200, json={"result": {"content": {}}})
    )

    params = GetCourseOutlineInput(course_id="do_missing")
    result = await get_course_outline(params)

    assert result.total_units == 0
    assert result.units == []
