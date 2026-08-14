from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import CategoryBudget, YoutubeRequest

ENTERTAINMENT_BUCKET = "entertainment"


def week_start(now: datetime | None = None) -> datetime:
    """Monday 00:00 UTC of the current week."""
    now = now or datetime.now(UTC)
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def minutes_for_duration(duration_seconds: int | None) -> int:
    if not duration_seconds or duration_seconds <= 0:
        return 0
    return math.ceil(duration_seconds / 60)


@dataclass(slots=True)
class BudgetStatus:
    bucket: str
    weekly_minutes: int
    used_minutes: int

    @property
    def remaining_minutes(self) -> int:
        return max(0, self.weekly_minutes - self.used_minutes)


class BudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def weekly_minutes(self, child_id: str, bucket: str = ENTERTAINMENT_BUCKET) -> int:
        result = await self.session.execute(
            select(CategoryBudget).where(
                CategoryBudget.child_id == child_id,
                CategoryBudget.bucket == bucket,
            )
        )
        budget = result.scalars().first()
        if budget:
            return budget.weekly_minutes
        return self.settings.default_entertainment_weekly_minutes

    async def used_minutes(self, child_id: str, bucket: str = ENTERTAINMENT_BUCKET) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(YoutubeRequest.minutes_charged), 0)).where(
                YoutubeRequest.requested_by_child_id == child_id,
                YoutubeRequest.allowance_bucket == bucket,
                YoutubeRequest.decided_at >= week_start(),
            )
        )
        return int(result.scalar_one())

    async def status(self, child_id: str, bucket: str = ENTERTAINMENT_BUCKET) -> BudgetStatus:
        return BudgetStatus(
            bucket=bucket,
            weekly_minutes=await self.weekly_minutes(child_id, bucket),
            used_minutes=await self.used_minutes(child_id, bucket),
        )

    async def set_weekly_minutes(
        self, child_id: str, weekly_minutes: int, bucket: str = ENTERTAINMENT_BUCKET
    ) -> CategoryBudget:
        result = await self.session.execute(
            select(CategoryBudget).where(
                CategoryBudget.child_id == child_id,
                CategoryBudget.bucket == bucket,
            )
        )
        budget = result.scalars().first()
        if budget is None:
            budget = CategoryBudget(child_id=child_id, bucket=bucket, weekly_minutes=weekly_minutes)
            self.session.add(budget)
        else:
            budget.weekly_minutes = weekly_minutes

        await self.session.commit()
        await self.session.refresh(budget)
        return budget
