import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest

from app.youtube.classifier import AIClassifier

METADATA = {"title": "Learn piano", "channel": "Piano Teacher", "duration": 300}

VALID_PAYLOAD = {
    "category": "music_tutorial",
    "safety_status": "safe",
    "confidence": 0.9,
    "summary": "Piano lesson.",
    "concerns": [],
}


class FakeAnthropicClient:
    def __init__(self, response, capture: dict) -> None:
        self.messages = SimpleNamespace(create=AsyncMock(return_value=response))
        self.close = AsyncMock()
        capture["client"] = self


def _response(stop_reason: str = "end_turn", text: str | None = None):
    blocks = []
    if text is not None:
        blocks.append(SimpleNamespace(type="text", text=text))
    return SimpleNamespace(stop_reason=stop_reason, content=blocks)


def _classifier(monkeypatch: pytest.MonkeyPatch) -> AIClassifier:
    classifier = AIClassifier()
    monkeypatch.setattr(classifier.settings, "ai_provider", "anthropic")
    monkeypatch.setattr(classifier.settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(classifier.settings, "ai_model", "claude-haiku-4-5")
    return classifier


async def test_anthropic_mode_parses_structured_output(monkeypatch) -> None:
    capture: dict = {}
    monkeypatch.setattr(
        anthropic,
        "AsyncAnthropic",
        lambda api_key: FakeAnthropicClient(_response(text=json.dumps(VALID_PAYLOAD)), capture),
    )
    classifier = _classifier(monkeypatch)

    result = await classifier.classify(METADATA, "transcript text")

    assert result["category"] == "music_tutorial"
    assert result["safety_status"] == "safe"

    kwargs = capture["client"].messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    capture["client"].close.assert_awaited()


async def test_anthropic_refusal_falls_back_to_heuristic(monkeypatch) -> None:
    capture: dict = {}
    monkeypatch.setattr(
        anthropic,
        "AsyncAnthropic",
        lambda api_key: FakeAnthropicClient(_response(stop_reason="refusal"), capture),
    )
    classifier = _classifier(monkeypatch)

    result = await classifier.classify(METADATA, "transcript text")

    assert result["safety_status"] == "needs_review"
    assert any(c.startswith("ai_error:") for c in result["concerns"])


async def test_anthropic_mode_without_key_uses_heuristic(monkeypatch) -> None:
    classifier = AIClassifier()
    monkeypatch.setattr(classifier.settings, "ai_provider", "anthropic")
    monkeypatch.setattr(classifier.settings, "anthropic_api_key", "")

    assert classifier.enabled is False
    result = await classifier.classify(METADATA, "transcript")
    assert result["safety_status"] == "needs_review"
