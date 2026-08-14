"""Periodic task loop: subscription polling, retention cleanup, weekly digest.

Run as a dedicated compose service: python -m app.workers.scheduler

Last-run bookkeeping is stored in the system_settings table so restarts don't
re-run everything immediately.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.entities import SystemSetting

logger = logging.getLogger(__name__)

TICK_SECONDS = 300


async def _get_last_run(session: AsyncSession, key: str) -> datetime | None:
    setting = await session.get(SystemSetting, key)
    if not setting or not setting.value:
        return None
    try:
        return datetime.fromisoformat(setting.value)
    except ValueError:
        return None


async def _set_last_run(session: AsyncSession, key: str, moment: datetime) -> None:
    setting = await session.get(SystemSetting, key)
    if setting:
        setting.value = moment.isoformat()
    else:
        session.add(SystemSetting(key=key, value=moment.isoformat()))
    await session.commit()


def interval_due(last_run: datetime | None, hours: int, now: datetime) -> bool:
    if last_run is None:
        return True
    return now - last_run >= timedelta(hours=hours)


def weekly_due(last_run: datetime | None, weekday: int, hour_utc: int, now: datetime) -> bool:
    """Due once per week, on/after the configured weekday+hour."""
    if now.weekday() != weekday or now.hour < hour_utc:
        return False
    return last_run is None or now - last_run >= timedelta(days=6)


async def poll_subscriptions_task(session: AsyncSession) -> None:
    from app.services.subscriptions import SubscriptionService

    ingested = await SubscriptionService(session).poll_all()
    if ingested:
        logger.info("subscription poll ingested %s new videos", ingested)


async def retention_cleanup_task(session: AsyncSession) -> None:
    from app.services.cleanup import RetentionCleanupService

    removed = await RetentionCleanupService(session).run()
    if removed:
        logger.info("retention cleanup removed %s videos", removed)


async def weekly_digest_task(session: AsyncSession) -> None:
    from app.services.digest import WeeklyDigestService

    await WeeklyDigestService(session).run()


async def run_tick(now: datetime | None = None) -> None:
    settings = get_settings()
    now = now or datetime.now(UTC)

    async with SessionLocal() as session:
        if interval_due(
            await _get_last_run(session, "last_subscription_poll"),
            settings.subscription_poll_hours,
            now,
        ):
            await poll_subscriptions_task(session)
            await _set_last_run(session, "last_subscription_poll", now)

        if interval_due(await _get_last_run(session, "last_retention_cleanup"), 24, now):
            await retention_cleanup_task(session)
            await _set_last_run(session, "last_retention_cleanup", now)

        if weekly_due(
            await _get_last_run(session, "last_weekly_digest"),
            settings.digest_weekday,
            settings.digest_hour_utc,
            now,
        ):
            await weekly_digest_task(session)
            await _set_last_run(session, "last_weekly_digest", now)


async def wait_for_migrations() -> None:
    """Block until the api service has applied migrations (fresh-stack boot race)."""
    from sqlalchemy import text

    while True:
        try:
            async with SessionLocal() as session:
                await session.execute(text("SELECT 1 FROM system_settings LIMIT 1"))
            return
        except Exception:  # noqa: BLE001
            logger.info("waiting for database migrations...")
            await asyncio.sleep(5)


async def main() -> None:
    configure_logging()
    logger.info("scheduler started, tick every %ss", TICK_SECONDS)
    await wait_for_migrations()
    while True:
        try:
            await run_tick()
        except Exception:  # noqa: BLE001
            logger.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
