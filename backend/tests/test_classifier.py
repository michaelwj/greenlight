import pytest

from app.youtube.classifier import (
    bucket_for_category,
    classify_heuristic,
    validate_ai_payload,
)


def test_heuristic_never_marks_safe() -> None:
    result = classify_heuristic({"title": "Learn algebra - full course"}, "transcript")
    assert result["safety_status"] == "needs_review"
    assert result["category"] == "education"


def test_validate_ai_payload_accepts_valid() -> None:
    data = validate_ai_payload(
        {
            "category": "music_tutorial",
            "safety_status": "safe",
            "confidence": 0.9,
            "summary": "Piano lesson.",
            "concerns": [],
        }
    )
    assert data["confidence"] == 0.9


@pytest.mark.parametrize(
    "mutation",
    [
        {"category": "unknown_category"},
        {"safety_status": "fine"},
        {"confidence": 1.5},
        {"concerns": "none"},
    ],
)
def test_validate_ai_payload_rejects_invalid(mutation: dict) -> None:
    data = {
        "category": "education",
        "safety_status": "safe",
        "confidence": 0.9,
        "summary": "ok",
        "concerns": [],
    }
    data.update(mutation)
    with pytest.raises(ValueError):
        validate_ai_payload(data)


def test_validate_ai_payload_rejects_missing_fields() -> None:
    with pytest.raises(ValueError):
        validate_ai_payload({"category": "education"})


def test_bucket_mapping() -> None:
    assert bucket_for_category("music_tutorial") == "educational"
    assert bucket_for_category("science") == "educational"
    assert bucket_for_category("gaming") == "entertainment"
    assert bucket_for_category("other") == "entertainment"
