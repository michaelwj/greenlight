from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import httpx
from redis import Redis
from rq import get_current_job
from sqlalchemy import select
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.entities import Child, YoutubeAsset, YoutubeRequest, YoutubeStatus
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)

_YOUTUBE_LAST_HIT_KEY = "greenlight:youtube:last_hit"

# Failures where a retry cannot help — mark failed immediately, never retry.
_PERMANENT_FAILURE_MARKERS = (
    "is not a valid url",
    "video unavailable",
    "private video",
    "age-restricted",
    "sign in to confirm your age",
    "removed by the uploader",
    "has been terminated",
    "video is not available",
)


def _is_permanent_failure(err: Exception) -> bool:
    message = str(err).lower()
    return any(marker in message for marker in _PERMANENT_FAILURE_MARKERS)


def _respect_youtube_gap() -> None:
    """Enforce a minimum gap between YouTube download jobs so a burst of
    approvals doesn't hammer YouTube back-to-back (single worker, so a
    blocking sleep is fine)."""
    settings = get_settings()
    gap = settings.youtube_min_gap_seconds
    if gap <= 0:
        return
    redis_conn = Redis.from_url(settings.redis_url)
    try:
        last_hit = float(redis_conn.get(_YOUTUBE_LAST_HIT_KEY) or 0)
        wait = last_hit + gap - time.time()
        if wait > 0:
            logger.info("youtube gap: sleeping %.0fs before next download", wait)
            time.sleep(wait)
        redis_conn.set(_YOUTUBE_LAST_HIT_KEY, time.time(), ex=max(gap * 10, 600))
    finally:
        redis_conn.close()


def run_download_job(request_id: str, notify: bool = True, force: bool = False) -> None:
    asyncio.run(_run_download_job_async(request_id, notify=notify, force=force))


async def _adopt_sibling_download(session: Any, request: YoutubeRequest) -> bool:
    """Reuse a file another kid already downloaded for the same video.

    Returns True when the file was adopted, so the caller can skip yt-dlp
    entirely and go straight to labeling it for this kid.
    """
    if not request.video_id:
        return False

    result = await session.execute(
        select(YoutubeRequest).where(
            YoutubeRequest.video_id == request.video_id,
            YoutubeRequest.id != request.id,
            YoutubeRequest.status == YoutubeStatus.AVAILABLE.value,
            YoutubeRequest.local_file_path.is_not(None),
        )
    )
    for sibling in result.scalars().all():
        if sibling.local_file_path and Path(sibling.local_file_path).exists():
            request.local_file_path = sibling.local_file_path
            request.plex_library_path = sibling.plex_library_path or sibling.local_file_path
            request.plex_item_id = sibling.plex_item_id
            request.status = YoutubeStatus.AVAILABLE.value
            await session.commit()
            logger.info(
                "request %s shares the existing download at %s",
                request.id, sibling.local_file_path,
            )
            return True
    return False


def _safe_file_stem(value: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return stem[:120] or "video"


async def _run_download_job_async(
    request_id: str, notify: bool = True, force: bool = False
) -> None:
    settings = get_settings()
    media_root = Path(settings.plex_media_root)
    media_root.mkdir(parents=True, exist_ok=True)

    async with SessionLocal() as session:
        request = await session.get(YoutubeRequest, request_id)
        if not request:
            return
        if request.status == YoutubeStatus.REMOVED.value:
            return

        # Another kid may already have this exact video on disk — share it
        # rather than downloading a second copy.
        if not force and await _adopt_sibling_download(session, request):
            await _apply_plex_label(settings, request, session)
            if notify:
                await NotificationService(session).send_download_available_notification(request)
            return

        request.status = YoutubeStatus.DOWNLOADING.value
        await session.commit()

        _respect_youtube_gap()

        category = (request.classified_category or "review").lower()
        target_dir = media_root / category
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            title = request.title or request.video_id or "video"
            safe_stem = _safe_file_stem(title)
            output_template = str(target_dir / f"{safe_stem}.%(ext)s")

            postprocessors: list[dict[str, Any]] = []
            if settings.sponsorblock_enabled:
                postprocessors.append(
                    {
                        "key": "SponsorBlock",
                        "categories": ["sponsor", "selfpromo", "interaction"],
                        "when": "after_filter",
                    }
                )
                postprocessors.append(
                    {
                        "key": "ModifyChapters",
                        "remove_sponsor_segments": ["sponsor", "selfpromo", "interaction"],
                    }
                )
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
            postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})

            # Apple/Plex-friendly selection: h264 (avc1) video + AAC (mp4a)
            # audio direct-plays everywhere. yt-dlp's plain "best" picks
            # AV1/VP9 + Opus, which chokes Apple clients inside an mp4.
            compat_format = (
                "bv*[vcodec^=avc1]+ba[acodec^=mp4a]"
                "/bv*[vcodec^=avc1]+ba"
                "/b[ext=mp4]/bv*+ba/b"
            )
            ydl_opts: dict[str, Any] = {
                "outtmpl": output_template,
                "format": compat_format,
                "merge_output_format": "mp4",
                # Re-downloads must replace the existing file (codec upgrades,
                # parent "Re-download"); default is to silently skip.
                "overwrites": True,
                "quiet": True,
                "noplaylist": True,
                "writesubtitles": True,
                "writeautomaticsub": True,
                "writethumbnail": True,
                "postprocessors": postprocessors,
            }
            info, file_path = _download_video(request.youtube_url, ydl_opts)

            metadata_path = file_path.with_suffix(".metadata.json")
            transcript_path = file_path.with_suffix(".transcript.txt")

            metadata_payload = {
                "id": request.id,
                "youtube_url": request.youtube_url,
                "title": request.title,
                "channel_name": request.channel_name,
                "classified_category": request.classified_category,
                "ai_summary": request.ai_summary,
                "hard_rule_results": request.hard_rule_results,
            }
            metadata_path.write_text(json.dumps(metadata_payload, indent=2), encoding="utf-8")
            transcript_path.write_text(request.transcript_text or "", encoding="utf-8")

            request.local_file_path = str(file_path)
            request.plex_library_path = str(file_path)
            request.status = YoutubeStatus.AVAILABLE.value
            await session.flush()

            session.add(
                YoutubeAsset(
                    youtube_request_id=request.id,
                    asset_type="video",
                    file_path=str(file_path),
                    metadata_json=metadata_payload,
                )
            )
            session.add(
                YoutubeAsset(
                    youtube_request_id=request.id,
                    asset_type="metadata",
                    file_path=str(metadata_path),
                )
            )
            session.add(
                YoutubeAsset(
                    youtube_request_id=request.id,
                    asset_type="transcript",
                    file_path=str(transcript_path),
                )
            )
            await session.commit()

            await _refresh_plex_if_configured(settings)
            await _apply_plex_label(settings, request, session)
            if notify:
                await NotificationService(session).send_download_available_notification(request)
        except Exception as err:  # noqa: BLE001
            job = get_current_job()
            retries_left = (job.retries_left or 0) if job else 0
            if retries_left > 0 and not _is_permanent_failure(err):
                # Transient (429/403/network): put the request back in the
                # queued state and re-raise so RQ retries on its delay schedule.
                logger.warning(
                    "transient download failure for %s (%d retries left): %s",
                    request_id, retries_left, err,
                )
                request.status = YoutubeStatus.APPROVED.value
                request.ai_concerns = (request.ai_concerns or []) + [
                    f"download_retry({retries_left} left):{str(err)[:200]}"
                ]
                await session.commit()
                raise
            logger.exception("download failed for request %s", request_id)
            request.status = YoutubeStatus.FAILED.value
            request.ai_concerns = (request.ai_concerns or []) + [f"download_error:{str(err)[:300]}"]
            await session.commit()


def _download_video(url: str, ydl_opts: dict[str, Any]) -> tuple[Any, Path]:
    """Run yt-dlp; a subtitle fetch failure (e.g. HTTP 429) must not sink the
    whole download, so retry once without subtitles."""
    try:
        return _extract(url, ydl_opts)
    except DownloadError as err:
        if "subtitles" not in str(err).lower():
            raise
        logger.warning("subtitle download failed for %s; retrying without subtitles", url)
        retry_opts = {**ydl_opts, "writesubtitles": False, "writeautomaticsub": False}
        return _extract(url, retry_opts)


def _extract(url: str, ydl_opts: dict[str, Any]) -> tuple[Any, Path]:
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        requested = (info or {}).get("requested_downloads") or []
        if requested and requested[0].get("filepath"):
            file_path = Path(requested[0]["filepath"])
        else:
            file_path = Path(ydl.prepare_filename(info))
        return info, file_path


def _plex_configured(settings: Any) -> bool:
    return bool(settings.plex_url and settings.plex_token and settings.plex_library_section_id)


async def _apply_plex_label(settings: Any, request: YoutubeRequest, session: Any) -> None:
    """Tag the newly indexed Plex item with the requesting kid's name
    (falls back to the configured PLEX_LABEL if the child is gone).

    Best-effort: the library scan is async, so poll briefly for the item to appear;
    a labeling failure never fails the download job.
    """
    if not _plex_configured(settings) or not request.local_file_path:
        return

    child = await session.get(Child, request.requested_by_child_id)
    label = (child.display_name if child else "") or settings.plex_label
    if not label:
        return

    base = settings.plex_url.rstrip("/")
    section = settings.plex_library_section_id
    filename = Path(request.local_file_path).name

    try:
        async with httpx.AsyncClient(timeout=20.0, headers={"Accept": "application/json"}) as client:
            rating_key = None
            for _ in range(10):
                response = await client.get(
                    f"{base}/library/sections/{section}/all",
                    params={"X-Plex-Token": settings.plex_token},
                )
                if response.status_code == 200:
                    items = (response.json().get("MediaContainer") or {}).get("Metadata") or []
                    for item in items:
                        parts = [
                            part
                            for media in item.get("Media") or []
                            for part in media.get("Part") or []
                        ]
                        if any(Path(part.get("file", "")).name == filename for part in parts):
                            rating_key = item.get("ratingKey")
                            break
                if rating_key:
                    break
                await asyncio.sleep(3)

            if not rating_key:
                logger.warning("plex item for %s not found; label not applied", filename)
                return

            # Labels are additive: a video two kids asked for carries both
            # names, so a Plex account restricted to either label can see it.
            # A bare PUT replaces the whole set, so send existing labels too.
            existing_labels: list[str] = []
            meta = await client.get(
                f"{base}/library/metadata/{rating_key}",
                params={"X-Plex-Token": settings.plex_token},
            )
            if meta.status_code == 200:
                entries = ((meta.json().get("MediaContainer") or {}).get("Metadata") or [{}])[0]
                existing_labels = [
                    tag for tag in (entry.get("tag") for entry in entries.get("Label") or []) if tag
                ]

            if any(tag.lower() == label.lower() for tag in existing_labels):
                request.plex_item_id = str(rating_key)
                await session.commit()
                return

            labels = existing_labels + [label]
            params = {
                "type": 1,
                "id": rating_key,
                "label.locked": 1,
                "X-Plex-Token": settings.plex_token,
            }
            for index, tag in enumerate(labels):
                params[f"label[{index}].tag.tag"] = tag

            await client.put(f"{base}/library/sections/{section}/all", params=params)
            request.plex_item_id = str(rating_key)
            await session.commit()
            logger.info("labeled plex item %s with %s", rating_key, labels)
    except Exception as err:  # noqa: BLE001
        logger.warning("plex labeling failed for %s: %s", filename, err)


async def _refresh_plex_if_configured(settings: Any) -> None:
    """Best-effort library refresh — an unreachable Plex must not fail a finished download."""
    if not _plex_configured(settings):
        return

    refresh_url = (
        f"{settings.plex_url}/library/sections/{settings.plex_library_section_id}/refresh"
        f"?X-Plex-Token={settings.plex_token}"
    )
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.get(refresh_url)
    except Exception as err:  # noqa: BLE001
        logger.warning("plex refresh failed (is PLEX_URL reachable from the container?): %s", err)
