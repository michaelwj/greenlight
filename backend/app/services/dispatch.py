from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import YoutubeRequest, YoutubeStatus
from app.services.notifications import NotificationService


async def dispatch_after_analysis(session: AsyncSession, request: YoutubeRequest) -> None:
    """Act on a screening decision: enqueue approved downloads, ping parents for reviews."""
    if request.status == YoutubeStatus.APPROVED.value:
        from app.workers.queue import enqueue_download

        enqueue_download(request.id)
    elif request.status == YoutubeStatus.NEEDS_REVIEW.value:
        await NotificationService(session).send_youtube_request_notification(request)
