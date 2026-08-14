from datetime import UTC, datetime, timedelta

from app.models.entities import Child, YoutubeRequest
from app.services.budgets import BudgetService, minutes_for_duration, week_start


def test_minutes_for_duration_rounds_up() -> None:
    assert minutes_for_duration(0) == 0
    assert minutes_for_duration(None) == 0
    assert minutes_for_duration(59) == 1
    assert minutes_for_duration(600) == 10
    assert minutes_for_duration(601) == 11


def test_week_start_is_monday_utc() -> None:
    start = week_start(datetime(2026, 7, 9, 15, 30, tzinfo=UTC))  # Thursday
    assert start == datetime(2026, 7, 6, 0, 0, tzinfo=UTC)
    assert start.weekday() == 0


async def test_budget_status_counts_only_this_week(db_session) -> None:
    child = Child(display_name="Kid")
    db_session.add(child)
    await db_session.commit()

    now = datetime.now(UTC)
    this_week = YoutubeRequest(
        requested_by_child_id=child.id,
        youtube_url="https://youtube.com/watch?v=1",
        allowance_bucket="entertainment",
        minutes_charged=30,
        decided_at=now,
        status="approved",
    )
    last_week = YoutubeRequest(
        requested_by_child_id=child.id,
        youtube_url="https://youtube.com/watch?v=2",
        allowance_bucket="entertainment",
        minutes_charged=45,
        decided_at=week_start(now) - timedelta(days=1),
        status="approved",
    )
    educational = YoutubeRequest(
        requested_by_child_id=child.id,
        youtube_url="https://youtube.com/watch?v=3",
        allowance_bucket="educational",
        minutes_charged=0,
        decided_at=now,
        status="approved",
    )
    db_session.add_all([this_week, last_week, educational])
    await db_session.commit()

    service = BudgetService(db_session)
    status = await service.status(child.id)

    assert status.used_minutes == 30
    assert status.weekly_minutes == service.settings.default_entertainment_weekly_minutes
    assert status.remaining_minutes == status.weekly_minutes - 30


async def test_set_weekly_minutes_overrides_default(db_session) -> None:
    child = Child(display_name="Kid")
    db_session.add(child)
    await db_session.commit()

    service = BudgetService(db_session)
    await service.set_weekly_minutes(child.id, 60)
    assert await service.weekly_minutes(child.id) == 60

    await service.set_weekly_minutes(child.id, 90)
    assert await service.weekly_minutes(child.id) == 90
