from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Child, WeeklyDigest, YoutubeRequest
from app.services.budgets import BudgetService
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)


class WeeklyDigestService:
    """Build and deliver the weekly parent digest."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(self) -> WeeklyDigest:
        now = datetime.now(UTC)
        window_start = now - timedelta(days=7)

        payload = await self.build_payload(window_start, now)

        digest = WeeklyDigest(week_start=window_start, week_end=now, payload_json=payload)
        self.session.add(digest)
        await self.session.commit()
        await self.session.refresh(digest)

        summary = payload["summary_line"]
        await NotificationService(self.session).send_digest_notification("Weekly family digest", summary)
        logger.info("weekly digest generated: %s", summary)
        return digest

    async def build_payload(self, window_start: datetime, window_end: datetime) -> dict:
        result = await self.session.execute(
            select(YoutubeRequest).where(
                YoutubeRequest.created_at >= window_start,
                YoutubeRequest.created_at <= window_end,
            )
        )
        requests = result.scalars().all()

        by_status = Counter(item.status for item in requests)
        by_source = Counter(item.source for item in requests)
        by_decision_source = Counter(
            item.decision_source for item in requests if item.decision_source
        )
        top_channels = Counter(
            item.channel_name for item in requests if item.channel_name
        ).most_common(5)
        denials = [
            {
                "title": item.title or item.youtube_url,
                "reason": item.denial_reason,
                "channel": item.channel_name,
            }
            for item in requests
            if item.status == "rejected"
        ][:10]
        failed = [item.title or item.youtube_url for item in requests if item.status == "failed"][:10]

        budgets = []
        children = (await self.session.execute(select(Child).where(Child.is_active.is_(True)))).scalars().all()
        budget_service = BudgetService(self.session)
        for child in children:
            status = await budget_service.status(child.id)
            budgets.append(
                {
                    "child": child.display_name,
                    "used_minutes": status.used_minutes,
                    "weekly_minutes": status.weekly_minutes,
                }
            )

        total = len(requests)
        auto_approved = sum(
            1
            for item in requests
            if item.decision_source == "auto" and item.status in {"approved", "downloading", "available"}
        )
        needs_review_now = by_status.get("needs_review", 0)
        summary_line = (
            f"{total} video requests this week: "
            f"{auto_approved} auto-approved, "
            f"{by_status.get('rejected', 0)} denied, "
            f"{needs_review_now} still waiting for review."
        )

        return {
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "total_requests": total,
            "by_status": dict(by_status),
            "by_source": dict(by_source),
            "by_decision_source": dict(by_decision_source),
            "top_channels": [{"channel": name, "count": count} for name, count in top_channels],
            "denials": denials,
            "failed_downloads": failed,
            "budgets": budgets,
            "summary_line": summary_line,
        }
