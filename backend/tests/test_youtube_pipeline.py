from app.youtube.pipeline import HardRuleResult, YoutubeReviewPipeline, extract_video_id


class _FakeSession:
    async def commit(self) -> None:
        return None

    async def refresh(self, _request) -> None:
        return None


BASE_METADATA = {
    "title": "Great lesson",
    "age_limit": 0,
    "is_live": False,
    "was_live": False,
    "availability": "public",
    "duration": 120,
    "channel": "Teacher Channel",
}


def test_hard_rules_pass_on_clean_metadata() -> None:
    pipeline = YoutubeReviewPipeline(_FakeSession())
    result = pipeline._evaluate_hard_rules(BASE_METADATA, channel_status=None)
    assert isinstance(result, HardRuleResult)
    assert result.passed is True
    assert result.decision == "approved"


def test_hard_rules_block_age_restricted() -> None:
    pipeline = YoutubeReviewPipeline(_FakeSession())
    result = pipeline._evaluate_hard_rules(dict(BASE_METADATA, age_limit=18), channel_status=None)
    assert result.decision == "blocked"
    assert "age_restricted" in result.reasons


def test_hard_rules_block_blocked_channel() -> None:
    pipeline = YoutubeReviewPipeline(_FakeSession())
    result = pipeline._evaluate_hard_rules(BASE_METADATA, channel_status="blocked")
    assert result.decision == "blocked"
    assert "blocked_channel" in result.reasons


def test_hard_rules_flag_livestream_and_duration() -> None:
    pipeline = YoutubeReviewPipeline(_FakeSession())
    metadata = dict(BASE_METADATA, is_live=True, duration=999999)
    result = pipeline._evaluate_hard_rules(metadata, channel_status=None)
    assert result.passed is False
    assert result.decision == "needs_review"
    assert "livestream_not_allowed" in result.reasons
    assert "duration_over_limit" in result.reasons


def test_hard_rules_flag_shorts() -> None:
    pipeline = YoutubeReviewPipeline(_FakeSession())
    metadata = dict(BASE_METADATA, title="crazy stunt #shorts")
    result = pipeline._evaluate_hard_rules(metadata, channel_status=None)
    assert "shorts_not_allowed" in result.reasons


def test_extract_video_id_handles_common_url_shapes() -> None:
    vid = "dQw4w9WgXcQ"
    assert extract_video_id(f"https://www.youtube.com/watch?v={vid}") == vid
    assert extract_video_id(f"https://youtu.be/{vid}?t=10") == vid
    assert extract_video_id(f"https://www.youtube.com/shorts/{vid}") == vid
    assert extract_video_id(f"https://www.youtube.com/embed/{vid}") == vid
    assert extract_video_id(f"https://m.youtube.com/watch?v={vid}&list=PL1") == vid
    assert extract_video_id("https://example.com/not-youtube") is None
    assert extract_video_id("") is None


def test_hard_rules_block_shorts_by_url() -> None:
    pipeline = YoutubeReviewPipeline(_FakeSession())
    result = pipeline._evaluate_hard_rules(
        BASE_METADATA, channel_status=None, youtube_url="https://www.youtube.com/shorts/abc12345678"
    )
    assert result.decision == "blocked"
    assert "shorts_not_allowed" in result.reasons


def test_hard_rules_block_shorts_by_duration_and_aspect() -> None:
    pipeline = YoutubeReviewPipeline(_FakeSession())
    assert (
        pipeline._evaluate_hard_rules(dict(BASE_METADATA, duration=45), None).decision == "blocked"
    )
    assert (
        pipeline._evaluate_hard_rules(dict(BASE_METADATA, aspect_ratio=0.56), None).decision
        == "blocked"
    )
    assert pipeline._evaluate_hard_rules(BASE_METADATA, None).decision == "approved"
