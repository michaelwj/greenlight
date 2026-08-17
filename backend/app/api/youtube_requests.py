from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_kid_auth, require_parent_auth
from app.core.config import get_settings
from app.core.rate_limit import enforce_kid_rate_limit
from app.db.session import get_db
from app.models.entities import (
    Child,
    DecisionSource,
    ParentUser,
    YoutubeRequest,
    YoutubeStatus,
)
from app.schemas.youtube_requests import YoutubeDecision, YoutubeRequestCreate, YoutubeRequestRead
from app.services.budgets import minutes_for_duration
from app.services.channel_rules import ChannelRuleService
from app.services.dispatch import dispatch_after_analysis
from app.services.notifications import NotificationService
from app.services.sharing import can_share, clone_request_for_child
from app.workers.queue import enqueue_download
from app.youtube.classifier import bucket_for_category
from app.youtube.pipeline import YoutubeReviewPipeline, extract_video_id

router = APIRouter(prefix="/api/youtube-requests", tags=["youtube-requests"])


def local_day_start_utc(settings=None) -> datetime:
    """Midnight today in the household timezone, expressed in UTC."""
    settings = settings or get_settings()
    tz = ZoneInfo(settings.household_timezone)
    local_midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight.astimezone(UTC)


async def enforce_daily_request_limit(db: AsyncSession, child_id: str) -> None:
    settings = get_settings()
    child = await db.get(Child, child_id)
    limit = (
        child.daily_request_limit
        if child and child.daily_request_limit is not None
        else settings.daily_request_limit
    )
    if limit <= 0:
        return
    count = await db.scalar(
        select(func.count())
        .select_from(YoutubeRequest)
        .where(
            YoutubeRequest.requested_by_child_id == child_id,
            YoutubeRequest.source == "kid_request",
            YoutubeRequest.created_at >= local_day_start_utc(settings),
        )
    )
    if (count or 0) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"You've used all {limit} requests for today — try again tomorrow!",
        )


async def _reads_with_names(
    db: AsyncSession, items: list[YoutubeRequest]
) -> list[YoutubeRequestRead]:
    """Attach the requesting kid's name so parents can see who asked."""
    ids = {item.requested_by_child_id for item in items}
    names: dict[str, str] = {}
    if ids:
        result = await db.execute(select(Child).where(Child.id.in_(ids)))
        names = {child.id: child.display_name for child in result.scalars().all()}
    reads = []
    for item in items:
        read = YoutubeRequestRead.model_validate(item)
        read.requested_by_name = names.get(item.requested_by_child_id)
        reads.append(read)
    return reads


def available_file_missing(item: YoutubeRequest) -> bool:
    """True when a request claims to be on Plex but its file is gone
    (e.g. deleted by hand from the media library)."""
    if item.status != YoutubeStatus.AVAILABLE.value:
        return False
    return not item.local_file_path or not Path(item.local_file_path).exists()


@router.post("", response_model=YoutubeRequestRead)
async def create_youtube_request(
    payload: YoutubeRequestCreate,
    _: None = Depends(require_kid_auth),
    __: None = Depends(enforce_kid_rate_limit),
    db: AsyncSession = Depends(get_db),
) -> YoutubeRequestRead:
    # Duplicate prevention: an active request for the same video is returned as-is
    # instead of creating (and potentially charging) a second one.
    video_id = extract_video_id(payload.youtube_url)
    dup_filter = (
        YoutubeRequest.video_id == video_id
        if video_id
        else YoutubeRequest.youtube_url == payload.youtube_url
    )
    existing = (
        (
            await db.execute(
                select(YoutubeRequest)
                .where(dup_filter, YoutubeRequest.status.notin_(["rejected", "failed", "removed"]))
                .order_by(YoutubeRequest.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if existing:
        # Self-heal: "available" but the file was deleted from the library —
        # re-queue the download instead of pointing at a video that isn't there.
        if available_file_missing(existing):
            existing.status = YoutubeStatus.APPROVED.value
            await db.commit()
            await db.refresh(existing)
            enqueue_download(existing.id)
            return YoutubeRequestRead.model_validate(existing)

        # A sibling already asked for this video: give this kid their own
        # request so it lands in their history and gets their Plex label. The
        # screening verdict is inherited and the downloaded file is shared.
        if existing.requested_by_child_id != payload.requested_by_child_id and can_share(existing):
            await enforce_daily_request_limit(db, payload.requested_by_child_id)
            shared = await clone_request_for_child(
                db, existing, payload.requested_by_child_id, payload.requested_category
            )
            await dispatch_after_analysis(db, shared)
            return YoutubeRequestRead.model_validate(shared)

        return YoutubeRequestRead.model_validate(existing)

    await enforce_daily_request_limit(db, payload.requested_by_child_id)

    item = YoutubeRequest(
        requested_by_child_id=payload.requested_by_child_id,
        youtube_url=payload.youtube_url,
        video_id=video_id,
        requested_category=payload.requested_category,
        status=YoutubeStatus.SUBMITTED.value,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)

    pipeline = YoutubeReviewPipeline(db)
    item = await pipeline.analyze_request(item)
    await dispatch_after_analysis(db, item)

    return YoutubeRequestRead.model_validate(item)


@router.get("/mine", response_model=list[YoutubeRequestRead])
async def list_my_youtube_requests(
    child_id: str = Query(...),
    limit: int = Query(default=50, le=200),
    _: None = Depends(require_kid_auth),
    db: AsyncSession = Depends(get_db),
) -> list[YoutubeRequestRead]:
    result = await db.execute(
        select(YoutubeRequest)
        .where(YoutubeRequest.requested_by_child_id == child_id)
        .order_by(YoutubeRequest.created_at.desc())
        .limit(limit)
    )
    return [YoutubeRequestRead.model_validate(item) for item in result.scalars().all()]


@router.get("/pending", response_model=list[YoutubeRequestRead])
async def list_pending_youtube_requests(
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> list[YoutubeRequestRead]:
    result = await db.execute(
        select(YoutubeRequest)
        .where(YoutubeRequest.status == YoutubeStatus.NEEDS_REVIEW.value)
        .order_by(YoutubeRequest.created_at.asc())
    )
    return await _reads_with_names(db, list(result.scalars().all()))


@router.get("/history", response_model=list[YoutubeRequestRead])
async def list_youtube_request_history(
    limit: int = Query(default=100, le=500),
    days: int = Query(default=3, ge=1, le=90),
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> list[YoutubeRequestRead]:
    since = datetime.now(UTC) - timedelta(days=days)
    result = await db.execute(
        select(YoutubeRequest)
        .where(
            YoutubeRequest.created_at >= since,
            # Removed requests disappear from the parent view entirely; kids
            # still see theirs (with an "ask again" option) in /mine.
            YoutubeRequest.status != YoutubeStatus.REMOVED.value,
        )
        .order_by(YoutubeRequest.created_at.desc())
        .limit(limit)
    )
    return await _reads_with_names(db, list(result.scalars().all()))


@router.get("/{request_id}", response_model=YoutubeRequestRead)
async def get_youtube_request(
    request_id: str,
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> YoutubeRequestRead:
    item = await db.get(YoutubeRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="YouTube request not found")
    return (await _reads_with_names(db, [item]))[0]


@router.post("/{request_id}/approve", response_model=YoutubeRequestRead)
async def approve_youtube_request(
    request_id: str,
    payload: YoutubeDecision,
    parent: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> YoutubeRequestRead:
    item = await db.get(YoutubeRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="YouTube request not found")

    item.status = YoutubeStatus.APPROVED.value
    item.parent_decision = "approved"
    item.decision_source = DecisionSource.PARENT.value
    item.decided_at = datetime.now(UTC)
    item.denial_reason = None
    bucket = item.allowance_bucket or bucket_for_category(item.classified_category or "other")
    if bucket == "entertainment":
        item.allowance_bucket = "entertainment"
        item.minutes_charged = minutes_for_duration(item.duration_seconds)
    await db.commit()
    await db.refresh(item)
    enqueue_download(item.id)
    await NotificationService(db).send_decision_notification(item.id, "approved")
    return YoutubeRequestRead.model_validate(item)


@router.post("/{request_id}/reject", response_model=YoutubeRequestRead)
async def reject_youtube_request(
    request_id: str,
    payload: YoutubeDecision,
    parent: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> YoutubeRequestRead:
    item = await db.get(YoutubeRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="YouTube request not found")

    item.status = YoutubeStatus.REJECTED.value
    item.parent_decision = "rejected"
    item.decision_source = DecisionSource.PARENT.value
    item.decided_at = datetime.now(UTC)
    item.denial_reason = payload.reason or "A parent declined this video."
    item.minutes_charged = 0
    await db.commit()
    await db.refresh(item)
    await NotificationService(db).send_decision_notification(item.id, "rejected")
    return YoutubeRequestRead.model_validate(item)


@router.post("/{request_id}/trust-channel", response_model=YoutubeRequestRead)
async def trust_channel_from_request(
    request_id: str,
    parent: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> YoutubeRequestRead:
    item = await db.get(YoutubeRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="YouTube request not found")
    if not item.channel_name:
        raise HTTPException(status_code=422, detail="Request has no channel metadata")

    await ChannelRuleService(db).upsert(
        channel_name=item.channel_name,
        channel_id=item.channel_id,
        status="trusted",
        added_by=parent.id,
    )

    # Trusting the channel also approves this request if it was waiting on review.
    if item.status == YoutubeStatus.NEEDS_REVIEW.value:
        return await approve_youtube_request(request_id, YoutubeDecision(), parent, db)

    return YoutubeRequestRead.model_validate(item)


@router.post("/{request_id}/retry", response_model=YoutubeRequestRead)
async def retry_youtube_request(
    request_id: str,
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> YoutubeRequestRead:
    item = await db.get(YoutubeRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="YouTube request not found")

    pipeline = YoutubeReviewPipeline(db)
    item = await pipeline.analyze_request(item)
    await dispatch_after_analysis(db, item)
    return YoutubeRequestRead.model_validate(item)


@router.post("/{request_id}/retry-download", response_model=YoutubeRequestRead)
async def retry_youtube_download(
    request_id: str,
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> YoutubeRequestRead:
    """Re-enqueue just the download for an already-approved request — a failed
    or stalled download, or an 'available' video whose file was deleted from
    the library. No re-screening, no budget re-charge."""
    item = await db.get(YoutubeRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="YouTube request not found")
    allowed = {
        YoutubeStatus.FAILED.value,
        YoutubeStatus.DOWNLOADING.value,
        YoutubeStatus.AVAILABLE.value,
    }
    if item.status not in allowed:
        raise HTTPException(
            status_code=422, detail="Only failed, stalled, or downloaded requests can be re-downloaded"
        )

    item.status = YoutubeStatus.APPROVED.value
    item.denial_reason = None
    await db.commit()
    await db.refresh(item)
    # force: an explicit re-download must refetch, not reuse a file on disk.
    enqueue_download(item.id, force=True)
    return YoutubeRequestRead.model_validate(item)


@router.post("/{request_id}/remove", response_model=YoutubeRequestRead)
async def remove_youtube_request(
    request_id: str,
    parent: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> YoutubeRequestRead:
    """Kill a stuck or unwanted request. The 'removed' status frees the
    duplicate check so the video can be requested again, and the download
    worker skips removed requests even if a job is already queued."""
    item = await db.get(YoutubeRequest, request_id)
    if not item:
        raise HTTPException(status_code=404, detail="YouTube request not found")

    item.status = YoutubeStatus.REMOVED.value
    item.decision_source = DecisionSource.PARENT.value
    item.decided_at = datetime.now(UTC)
    item.denial_reason = "Removed by a parent."
    item.minutes_charged = 0
    await db.commit()
    await db.refresh(item)
    return YoutubeRequestRead.model_validate(item)
