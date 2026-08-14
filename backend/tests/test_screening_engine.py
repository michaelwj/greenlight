from typing import Any

import pytest

from app.models.entities import Child, ChannelRule, YoutubeRequest, YoutubeStatus
from app.services.budgets import BudgetService
from app.services.channel_rules import ChannelRuleService
from app.youtube.pipeline import YoutubeReviewPipeline


class StubClassifier:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    async def classify(self, metadata: dict[str, Any], transcript_text: str | None) -> dict[str, Any]:
        return self.result


def make_pipeline(
    session,
    metadata: dict[str, Any],
    transcript: str | None,
    ai_result: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> YoutubeReviewPipeline:
    pipeline = YoutubeReviewPipeline(session, classifier=StubClassifier(ai_result))
    monkeypatch.setattr(pipeline, "_extract_metadata", lambda url: metadata)

    async def fake_transcript(_metadata: dict[str, Any]) -> str | None:
        return transcript

    monkeypatch.setattr(pipeline, "_get_transcript", fake_transcript)
    return pipeline


async def make_child(session) -> Child:
    child = Child(display_name="Kid")
    session.add(child)
    await session.commit()
    await session.refresh(child)
    return child


def make_request(child_id: str, url: str = "https://youtube.com/watch?v=abc") -> YoutubeRequest:
    return YoutubeRequest(requested_by_child_id=child_id, youtube_url=url, status="submitted")


CLEAN_METADATA = {
    "id": "abc",
    "title": "Learn fractions",
    "channel": "Math Teacher",
    "channel_id": "UC123",
    "duration": 600,
    "age_limit": 0,
    "availability": "public",
    "is_live": False,
    "was_live": False,
}

SAFE_EDU = {
    "category": "education",
    "safety_status": "safe",
    "confidence": 0.92,
    "summary": "Fractions lesson.",
    "concerns": [],
}


async def test_educational_clean_transcript_auto_approves(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    pipeline = make_pipeline(db_session, CLEAN_METADATA, "full transcript text", SAFE_EDU, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.APPROVED.value
    assert result.decision_source == "auto"
    assert result.allowance_bucket == "educational"
    assert result.minutes_charged == 0


async def test_educational_without_transcript_auto_approves_by_default(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    pipeline = make_pipeline(db_session, CLEAN_METADATA, None, SAFE_EDU, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.APPROVED.value


async def test_educational_without_transcript_needs_review_when_required(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    pipeline = make_pipeline(db_session, CLEAN_METADATA, None, SAFE_EDU, monkeypatch)
    monkeypatch.setattr(pipeline.settings, "require_transcript_for_auto_approve", True)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.NEEDS_REVIEW.value


async def test_low_confidence_needs_review(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    ai = dict(SAFE_EDU, confidence=0.4)
    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", ai, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.NEEDS_REVIEW.value


async def test_blocked_channel_auto_denies(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    db_session.add(ChannelRule(channel_id="UC123", channel_name="Math Teacher", status="blocked"))
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", SAFE_EDU, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.REJECTED.value
    assert result.denial_reason == "This channel is blocked."
    assert result.decision_source == "auto"


async def test_trusted_channel_entertainment_charges_budget(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    db_session.add(ChannelRule(channel_id="UC123", channel_name="Math Teacher", status="trusted"))
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    ai = {
        "category": "entertainment",
        "safety_status": "safe",
        "confidence": 0.9,
        "summary": "Cartoon.",
        "concerns": [],
    }
    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", ai, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.APPROVED.value
    assert result.allowance_bucket == "entertainment"
    assert result.minutes_charged == 10

    status = await BudgetService(db_session).status(child.id)
    assert status.used_minutes == 10


async def test_entertainment_over_budget_auto_denies(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    db_session.add(ChannelRule(channel_id="UC123", channel_name="Math Teacher", status="trusted"))
    await BudgetService(db_session).set_weekly_minutes(child.id, 5)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    ai = {
        "category": "gaming",
        "safety_status": "safe",
        "confidence": 0.9,
        "summary": "Gameplay.",
        "concerns": [],
    }
    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", ai, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.REJECTED.value
    assert "fun-video minutes" in (result.denial_reason or "")


async def test_entertainment_unknown_channel_needs_review(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    ai = {
        "category": "entertainment",
        "safety_status": "safe",
        "confidence": 0.9,
        "summary": "Cartoon.",
        "concerns": [],
    }
    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", ai, monkeypatch)
    result = await pipeline.analyze_request(request)

    # AUTO_APPROVE_ENTERTAINMENT defaults to false -> parent review.
    assert result.status == YoutubeStatus.NEEDS_REVIEW.value


async def test_confident_unsafe_auto_denies(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    ai = {
        "category": "education",
        "safety_status": "unsafe",
        "confidence": 0.95,
        "summary": "Inappropriate.",
        "concerns": ["profanity"],
    }
    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", ai, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.REJECTED.value
    assert result.denial_reason == "The content screener flagged this video."


async def test_age_restricted_hard_rule_blocks(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    metadata = dict(CLEAN_METADATA, age_limit=18)
    pipeline = make_pipeline(db_session, metadata, "transcript", SAFE_EDU, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.REJECTED.value
    assert result.denial_reason == "This video is age-restricted."


async def test_channel_rule_service_env_fallback(db_session, monkeypatch) -> None:
    service = ChannelRuleService(db_session)
    monkeypatch.setattr(service.settings, "trusted_channels", "Khan Academy")
    monkeypatch.setattr(service.settings, "blocked_channels", "Bad Channel")

    assert await service.lookup(None, "Khan Academy") == "trusted"
    assert await service.lookup(None, "bad channel") == "blocked"
    assert await service.lookup(None, "Unknown") is None


async def test_channel_rule_upsert_updates_existing(db_session) -> None:
    service = ChannelRuleService(db_session)
    rule = await service.upsert(channel_name="Maker Kids", channel_id="UC9", status="trusted")
    updated = await service.upsert(channel_name="Maker Kids", channel_id="UC9", status="blocked")

    assert updated.id == rule.id
    assert updated.status == "blocked"


async def test_metadata_extraction_failure_marks_failed_not_stuck(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    pipeline = YoutubeReviewPipeline(db_session, classifier=StubClassifier(SAFE_EDU))

    def boom(url: str) -> dict[str, Any]:
        raise RuntimeError("ERROR: [generic] 'pasted search text' is not a valid URL")

    monkeypatch.setattr(pipeline, "_extract_metadata", boom)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.FAILED.value
    assert "YouTube link" in result.denial_reason
    assert any("analysis_error:" in c for c in result.ai_concerns)


async def test_restricted_video_failure_gets_availability_message(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    pipeline = YoutubeReviewPipeline(db_session, classifier=StubClassifier(SAFE_EDU))

    def boom(url: str) -> dict[str, Any]:
        raise RuntimeError("ERROR: [youtube] abc: Video unavailable. This video is restricted.")

    monkeypatch.setattr(pipeline, "_extract_metadata", boom)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.FAILED.value
    assert "isn't available" in result.denial_reason


async def test_flagged_topic_forces_review_even_on_trusted_channel(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    await ChannelRuleService(db_session).upsert(
        channel_name="Math Teacher", channel_id="UC123", status="trusted"
    )
    ai = dict(SAFE_EDU, flagged_topics=["romantic relationships"])
    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", ai, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.NEEDS_REVIEW.value
    assert any("romantic relationships" in r for r in result.review_reasons)


async def test_low_confidence_review_reason_is_explicit(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    ai = dict(SAFE_EDU, confidence=0.6)
    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", ai, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.NEEDS_REVIEW.value
    assert any("AI confidence 60%" in r for r in result.review_reasons)


async def test_entertainment_review_reason_explains_policy(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    ai = dict(SAFE_EDU, category="gaming")
    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", ai, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.NEEDS_REVIEW.value
    assert any("parent decision" in r for r in result.review_reasons)


async def test_auto_approve_clears_review_reasons(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    pipeline = make_pipeline(db_session, CLEAN_METADATA, "transcript", SAFE_EDU, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.APPROVED.value
    assert result.review_reasons is None


async def test_short_video_forces_depth_review(db_session, monkeypatch) -> None:
    child = await make_child(db_session)
    request = make_request(child.id)
    db_session.add(request)
    await db_session.commit()

    metadata = dict(CLEAN_METADATA, duration=180)  # 3 min: above Shorts, below depth check
    pipeline = make_pipeline(db_session, metadata, "transcript", SAFE_EDU, monkeypatch)
    result = await pipeline.analyze_request(request)

    assert result.status == YoutubeStatus.NEEDS_REVIEW.value
    assert any("depth check" in r for r in result.review_reasons)


async def test_daily_request_limit_enforced(db_session, monkeypatch) -> None:
    import pytest as _pytest
    from fastapi import HTTPException

    from app.api.youtube_requests import enforce_daily_request_limit
    from app.core.config import get_settings

    child = await make_child(db_session)
    monkeypatch.setattr(get_settings(), "daily_request_limit", 2)

    for _ in range(2):
        db_session.add(make_request(child.id))
    await db_session.commit()

    with _pytest.raises(HTTPException) as excinfo:
        await enforce_daily_request_limit(db_session, child.id)
    assert excinfo.value.status_code == 429
    assert "2 requests" in excinfo.value.detail

    monkeypatch.setattr(get_settings(), "daily_request_limit", 10)
    await enforce_daily_request_limit(db_session, child.id)  # under limit: no raise


async def test_per_kid_limit_overrides_global(db_session, monkeypatch) -> None:
    import pytest as _pytest
    from fastapi import HTTPException

    from app.api.youtube_requests import enforce_daily_request_limit
    from app.core.config import get_settings

    child = await make_child(db_session)
    child.daily_request_limit = 1
    db_session.add(make_request(child.id))
    await db_session.commit()

    monkeypatch.setattr(get_settings(), "daily_request_limit", 10)
    with _pytest.raises(HTTPException) as excinfo:
        await enforce_daily_request_limit(db_session, child.id)
    assert "1 request" in excinfo.value.detail

    child.daily_request_limit = None  # falls back to global (10) -> passes
    await db_session.commit()
    await enforce_daily_request_limit(db_session, child.id)
