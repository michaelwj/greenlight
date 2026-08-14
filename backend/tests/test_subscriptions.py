from typing import Any

import pytest

from app.models.entities import ChannelRule, Child, YoutubeRequest, YoutubeStatus
from app.services.subscriptions import SubscriptionService
from app.youtube.pipeline import YoutubeReviewPipeline


@pytest.fixture
def analyze_stub(monkeypatch):
    """Skip the real pipeline; mark analyzed requests approved."""

    async def fake_analyze(self, request: YoutubeRequest) -> YoutubeRequest:
        request.status = YoutubeStatus.APPROVED.value
        await self.session.commit()
        return request

    monkeypatch.setattr(YoutubeReviewPipeline, "analyze_request", fake_analyze)

    async def fake_dispatch(session, request) -> None:
        return None

    monkeypatch.setattr("app.services.subscriptions.dispatch_after_analysis", fake_dispatch)


async def _setup(db_session, subscribed_child: bool = True):
    child = Child(display_name="Kid")
    db_session.add(child)
    await db_session.commit()

    rule = ChannelRule(
        channel_id="UCabc",
        channel_name="Maker Channel",
        status="trusted",
        subscribed=True,
        subscribed_child_id=child.id if subscribed_child else None,
    )
    db_session.add(rule)
    await db_session.commit()
    return child, rule


def fetcher_returning(videos: list[dict[str, Any]]):
    def fetcher(channel_id: str, limit: int) -> list[dict[str, Any]]:
        return videos[:limit]

    return fetcher


async def test_poll_ingests_new_videos(db_session, analyze_stub) -> None:
    child, rule = await _setup(db_session)
    videos = [{"id": "vid1", "title": "One"}, {"id": "vid2", "title": "Two"}]
    service = SubscriptionService(db_session, fetcher=fetcher_returning(videos))

    ingested = await service.poll_all()

    assert ingested == 2
    assert rule.last_polled_at is not None


async def test_poll_dedupes_known_videos(db_session, analyze_stub) -> None:
    child, rule = await _setup(db_session)
    db_session.add(
        YoutubeRequest(
            requested_by_child_id=child.id,
            youtube_url="https://www.youtube.com/watch?v=vid1",
            video_id="vid1",
            status="available",
        )
    )
    await db_session.commit()

    videos = [{"id": "vid1", "title": "One"}, {"id": "vid2", "title": "Two"}]
    service = SubscriptionService(db_session, fetcher=fetcher_returning(videos))

    assert await service.poll_all() == 1
    assert await service.poll_all() == 0


async def test_poll_respects_per_poll_cap(db_session, analyze_stub, monkeypatch) -> None:
    child, rule = await _setup(db_session)
    videos = [{"id": f"vid{i}", "title": str(i)} for i in range(10)]
    service = SubscriptionService(db_session, fetcher=fetcher_returning(videos))
    monkeypatch.setattr(service.settings, "subscription_max_new_per_poll", 2)

    assert await service.poll_all() == 2


async def test_poll_skips_rule_without_channel_id(db_session, analyze_stub) -> None:
    child = Child(display_name="Kid")
    db_session.add(child)
    db_session.add(ChannelRule(channel_name="No ID", status="trusted", subscribed=True))
    await db_session.commit()

    service = SubscriptionService(db_session, fetcher=fetcher_returning([{"id": "x"}]))
    assert await service.poll_all() == 0


async def test_poll_falls_back_to_first_active_child(db_session, analyze_stub) -> None:
    child, rule = await _setup(db_session, subscribed_child=False)
    videos = [{"id": "vid9", "title": "Nine"}]
    service = SubscriptionService(db_session, fetcher=fetcher_returning(videos))

    assert await service.poll_all() == 1
