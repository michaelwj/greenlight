from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import YoutubeAsset, YoutubeRequest, YoutubeStatus

logger = logging.getLogger(__name__)

REMOVED_STATUS = "removed"


class RetentionCleanupService:
    """Delete entertainment downloads past their retention window; educational stays."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def run(self) -> int:
        days = self.settings.entertainment_retention_days
        if days <= 0:
            return 0

        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self.session.execute(
            select(YoutubeRequest).where(
                YoutubeRequest.status == YoutubeStatus.AVAILABLE.value,
                YoutubeRequest.allowance_bucket == "entertainment",
                YoutubeRequest.decided_at < cutoff,
            )
        )
        expired = result.scalars().all()

        removed = 0
        for request in expired:
            await self._remove_files(request)
            request.status = REMOVED_STATUS
            removed += 1
            logger.info("retention cleanup removed %s (%s)", request.title, request.id)

        if removed:
            await self.session.commit()
        return removed

    async def _remove_files(self, request: YoutubeRequest) -> None:
        result = await self.session.execute(
            select(YoutubeAsset).where(YoutubeAsset.youtube_request_id == request.id)
        )
        assets = result.scalars().all()

        paths = {asset.file_path for asset in assets}
        if request.local_file_path:
            paths.add(request.local_file_path)

        for raw_path in paths:
            try:
                Path(raw_path).unlink(missing_ok=True)
            except OSError as err:
                logger.warning("could not delete %s: %s", raw_path, err)

        for asset in assets:
            await self.session.delete(asset)
