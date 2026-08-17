from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    DecisionSource,
    YoutubeRequest,
    YoutubeSafetyStatus,
    YoutubeStatus,
)
from app.services.budgets import BudgetService, minutes_for_duration

# Statuses where the source request has a finished screening verdict that a
# second kid can inherit.
_SETTLED = {
    YoutubeStatus.APPROVED.value,
    YoutubeStatus.DOWNLOADING.value,
    YoutubeStatus.AVAILABLE.value,
    YoutubeStatus.NEEDS_REVIEW.value,
}


def can_share(source: YoutubeRequest) -> bool:
    return source.status in _SETTLED


async def clone_request_for_child(
    session: AsyncSession,
    source: YoutubeRequest,
    child_id: str,
    requested_category: str | None = None,
) -> YoutubeRequest:
    """Give another kid their own request for a video a sibling already asked for.

    The screening verdict is inherited (no second AI call, no second download —
    the file is shared), but this kid's own entertainment budget still applies,
    and an unreviewed video still needs its own parent decision.
    """
    item = YoutubeRequest(
        requested_by_child_id=child_id,
        youtube_url=source.youtube_url,
        video_id=source.video_id,
        title=source.title,
        channel_name=source.channel_name,
        channel_id=source.channel_id,
        duration_seconds=source.duration_seconds,
        description=source.description,
        publish_date=source.publish_date,
        thumbnail_url=source.thumbnail_url,
        transcript_text=source.transcript_text,
        requested_category=requested_category,
        classified_category=source.classified_category,
        allowance_bucket=source.allowance_bucket,
        safety_status=source.safety_status,
        ai_confidence=source.ai_confidence,
        ai_summary=source.ai_summary,
        ai_concerns=source.ai_concerns,
        hard_rule_results=source.hard_rule_results,
        status=YoutubeStatus.SUBMITTED.value,
    )

    if source.status == YoutubeStatus.NEEDS_REVIEW.value:
        # Approving a video for one kid isn't approval for another.
        item.status = YoutubeStatus.NEEDS_REVIEW.value
        item.safety_status = YoutubeSafetyStatus.NEEDS_REVIEW.value
        item.review_reasons = list(source.review_reasons or []) + [
            "Already waiting for review from another kid's request"
        ]
    else:
        # Already approved for a sibling: inherit that, but charge this kid's
        # own budget for entertainment.
        minutes = 0
        if (source.allowance_bucket or "") == "entertainment":
            minutes = minutes_for_duration(source.duration_seconds)
            budget = await BudgetService(session).status(child_id)
            if minutes > budget.remaining_minutes:
                item.status = YoutubeStatus.REJECTED.value
                item.safety_status = YoutubeSafetyStatus.BLOCKED.value
                item.decision_source = DecisionSource.AUTO.value
                item.decided_at = datetime.now(UTC)
                item.denial_reason = (
                    "You're out of fun-video minutes this week. "
                    "Educational videos are always open!"
                )
                item.minutes_charged = 0
                session.add(item)
                await session.commit()
                await session.refresh(item)
                return item

        item.status = YoutubeStatus.APPROVED.value
        item.decision_source = DecisionSource.AUTO.value
        item.decided_at = datetime.now(UTC)
        item.minutes_charged = minutes

    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item
