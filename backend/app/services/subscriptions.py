from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import (
    ChannelRule,
    ChannelRuleStatus,
    Child,
    RequestSource,
    YoutubeRequest,
    YoutubeStatus,
)
from app.services.dispatch import dispatch_after_analysis
from app.youtube.pipeline import YoutubeReviewPipeline

logger = logging.getLogger(__name__)


def _fetch_latest_video_ids(channel_id: str, limit: int) -> list[dict[str, Any]]:
    """Return [{'id': ..., 'title': ...}] for a channel's most recent uploads."""
    from yt_dlp import YoutubeDL

    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlistend": limit,
        "skip_download": True,
    }
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = (info or {}).get("entries") or []
    videos = []
    for entry in entries:
        video_id = entry.get("id")
        if video_id:
            videos.append({"id": video_id, "title": entry.get("title")})
    return videos


class SubscriptionService:
    """Ingest new uploads from subscribed trusted channels through the screening pipeline."""

    def __init__(self, session: AsyncSession, fetcher=_fetch_latest_video_ids) -> None:
        self.session = session
        self.settings = get_settings()
        self.fetcher = fetcher

    async def poll_all(self) -> int:
        result = await self.session.execute(
            select(ChannelRule).where(
                ChannelRule.subscribed.is_(True),
                ChannelRule.status == ChannelRuleStatus.TRUSTED.value,
            )
        )
        rules = result.scalars().all()
        ingested = 0
        for rule in rules:
            try:
                ingested += await self.poll_rule(rule)
            except Exception:  # noqa: BLE001
                logger.exception("subscription poll failed for channel %s", rule.channel_name)
        return ingested

    async def poll_rule(self, rule: ChannelRule) -> int:
        if not rule.channel_id:
            logger.warning(
                "subscribed channel %s has no channel_id; skipping (re-add via a request's trust button)",
                rule.channel_name,
            )
            return 0

        child_id = rule.subscribed_child_id or await self._default_child_id()
        if not child_id:
            logger.warning("no active child to attach subscription requests to; skipping")
            return 0

        limit = self.settings.subscription_max_new_per_poll
        videos = self.fetcher(rule.channel_id, limit * 2)

        ingested = 0
        for video in videos:
            if ingested >= limit:
                break
            if await self._already_ingested(video["id"]):
                continue

            request = YoutubeRequest(
                requested_by_child_id=child_id,
                youtube_url=f"https://www.youtube.com/watch?v={video['id']}",
                video_id=video["id"],
                source=RequestSource.SUBSCRIPTION.value,
                status=YoutubeStatus.SUBMITTED.value,
            )
            self.session.add(request)
            await self.session.commit()
            await self.session.refresh(request)

            pipeline = YoutubeReviewPipeline(self.session)
            request = await pipeline.analyze_request(request)
            await dispatch_after_analysis(self.session, request)
            ingested += 1
            logger.info(
                "subscription ingested %s (%s) -> %s",
                video["id"],
                rule.channel_name,
                request.status,
            )

        rule.last_polled_at = datetime.now(UTC)
        await self.session.commit()
        return ingested

    async def _already_ingested(self, video_id: str) -> bool:
        result = await self.session.execute(
            select(YoutubeRequest.id).where(YoutubeRequest.video_id == video_id).limit(1)
        )
        return result.scalars().first() is not None

    async def _default_child_id(self) -> str | None:
        result = await self.session.execute(
            select(Child.id).where(Child.is_active.is_(True)).order_by(Child.created_at).limit(1)
        )
        return result.scalars().first()
