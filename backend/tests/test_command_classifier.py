import json

import pytest

from app.youtube.classifier import AIClassifier, extract_json_object

METADATA = {"title": "Learn piano", "channel": "Piano Teacher", "duration": 300}

VALID_JSON = json.dumps(
    {
        "category": "music_tutorial",
        "safety_status": "safe",
        "confidence": 0.9,
        "summary": "Piano lesson.",
        "concerns": [],
    }
)


def test_extract_json_object_from_noisy_output() -> None:
    noisy = f"thinking...\nsome log line {{not json}}\n{VALID_JSON}\ndone\n"
    data = extract_json_object(noisy)
    assert data["category"] == "music_tutorial"


def test_extract_json_object_raises_without_json() -> None:
    with pytest.raises(ValueError):
        extract_json_object("no json here")


def _command_classifier(monkeypatch: pytest.MonkeyPatch, command: str) -> AIClassifier:
    classifier = AIClassifier()
    monkeypatch.setattr(classifier.settings, "ai_provider", "command")
    monkeypatch.setattr(classifier.settings, "ai_command", command)
    monkeypatch.setattr(classifier.settings, "ai_command_timeout_seconds", 30)
    return classifier


async def test_command_mode_parses_output(monkeypatch) -> None:
    # Stand-in for `codex exec -`: consumes the prompt on stdin, prints JSON.
    command = f"cat >/dev/null; echo preamble; printf '%s\\n' '{VALID_JSON}'"
    classifier = _command_classifier(monkeypatch, command)
    result = await classifier.classify(METADATA, "transcript text")

    assert result["category"] == "music_tutorial"
    assert result["safety_status"] == "safe"


async def test_command_mode_failure_falls_back_to_heuristic(monkeypatch) -> None:
    classifier = _command_classifier(monkeypatch, "false")
    result = await classifier.classify(METADATA, "transcript text")

    assert result["safety_status"] == "needs_review"
    assert any(concern.startswith("ai_error:") for concern in result["concerns"])


async def test_command_mode_invalid_json_falls_back(monkeypatch) -> None:
    classifier = _command_classifier(monkeypatch, "echo not-json-at-all")
    result = await classifier.classify(METADATA, "transcript text")

    assert result["safety_status"] == "needs_review"


async def test_command_provider_without_command_uses_heuristic(monkeypatch) -> None:
    classifier = AIClassifier()
    monkeypatch.setattr(classifier.settings, "ai_provider", "command")
    monkeypatch.setattr(classifier.settings, "ai_command", "")

    result = await classifier.classify(METADATA, "transcript")
    assert result["safety_status"] == "needs_review"
    assert classifier.enabled is False
