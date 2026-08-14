from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import PushSubscription

logger = logging.getLogger(__name__)


class NotificationService:
    """Web Push (VAPID) notifications to parent PWA subscriptions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def send_youtube_request_notification(self, request: Any) -> None:
        title = "Video needs review"
        body = request.title or request.youtube_url
        await self._broadcast(title, body, {"type": "youtube_request", "request_id": request.id})

    async def send_decision_notification(self, request_id: str, decision: str) -> None:
        title = f"Request {decision}"
        body = f"Request {request_id} was {decision}"
        await self._broadcast(title, body, {"type": "decision", "request_id": request_id, "decision": decision})

    async def send_download_available_notification(self, request: Any) -> None:
        title = "New video on Plex"
        body = request.title or "Approved video is ready"
        await self._broadcast(title, body, {"type": "download_available", "request_id": request.id})

    async def send_digest_notification(self, subject: str, body: str) -> None:
        await self._broadcast(subject, body, {"type": "weekly_digest"})

    async def _broadcast(self, title: str, body: str, data: dict[str, Any]) -> None:
        if not self.settings.vapid_private_key:
            return

        result = await self.session.execute(select(PushSubscription))
        subscriptions = result.scalars().all()
        if not subscriptions:
            return

        payload = json.dumps({"title": title, "body": body, "data": data})
        stale: list[PushSubscription] = []
        for subscription in subscriptions:
            try:
                await asyncio.to_thread(
                    self._send_one,
                    {"endpoint": subscription.endpoint, "keys": subscription.keys_json},
                    payload,
                )
            except WebPushException as err:
                status_code = err.response.status_code if err.response is not None else None
                if status_code in (404, 410):
                    stale.append(subscription)
                else:
                    logger.warning("Web push delivery failed: %s", err)
            except Exception as err:  # noqa: BLE001
                logger.warning("Web push delivery error: %s", err)

        for subscription in stale:
            await self.session.delete(subscription)
        if stale:
            await self.session.commit()

    def _send_one(self, subscription_info: dict[str, Any], payload: str) -> None:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=self.settings.vapid_private_key,
            vapid_claims={"sub": self.settings.vapid_subject},
        )
