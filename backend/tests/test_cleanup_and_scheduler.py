from datetime import UTC, datetime, timedelta

from app.models.entities import Child, YoutubeAsset, YoutubeRequest
from app.services.cleanup import RetentionCleanupService
from app.workers.scheduler import interval_due, weekly_due


async def test_cleanup_removes_expired_entertainment(db_session, tmp_path, monkeypatch) -> None:
    child = Child(display_name="Kid")
    db_session.add(child)
    await db_session.commit()

    old_file = tmp_path / "old.mp4"
    old_file.write_bytes(b"video")
    fresh_file = tmp_path / "fresh.mp4"
    fresh_file.write_bytes(b"video")
    edu_file = tmp_path / "edu.mp4"
    edu_file.write_bytes(b"video")

    now = datetime.now(UTC)
    old = YoutubeRequest(
        requested_by_child_id=child.id,
        youtube_url="u1",
        status="available",
        allowance_bucket="entertainment",
        decided_at=now - timedelta(days=60),
        local_file_path=str(old_file),
    )
    fresh = YoutubeRequest(
        requested_by_child_id=child.id,
        youtube_url="u2",
        status="available",
        allowance_bucket="entertainment",
        decided_at=now - timedelta(days=2),
        local_file_path=str(fresh_file),
    )
    edu = YoutubeRequest(
        requested_by_child_id=child.id,
        youtube_url="u3",
        status="available",
        allowance_bucket="educational",
        decided_at=now - timedelta(days=200),
        local_file_path=str(edu_file),
    )
    db_session.add_all([old, fresh, edu])
    await db_session.commit()

    db_session.add(YoutubeAsset(youtube_request_id=old.id, asset_type="video", file_path=str(old_file)))
    await db_session.commit()

    service = RetentionCleanupService(db_session)
    monkeypatch.setattr(service.settings, "entertainment_retention_days", 30)
    removed = await service.run()

    assert removed == 1
    assert old.status == "removed"
    assert not old_file.exists()
    assert fresh_file.exists()
    assert edu_file.exists()
    assert fresh.status == "available"
    assert edu.status == "available"


async def test_cleanup_disabled_with_zero_retention(db_session, monkeypatch) -> None:
    service = RetentionCleanupService(db_session)
    monkeypatch.setattr(service.settings, "entertainment_retention_days", 0)
    assert await service.run() == 0


def test_interval_due() -> None:
    now = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)
    assert interval_due(None, 6, now) is True
    assert interval_due(now - timedelta(hours=7), 6, now) is True
    assert interval_due(now - timedelta(hours=5), 6, now) is False


def test_weekly_due() -> None:
    sunday_evening = datetime(2026, 7, 12, 19, 0, tzinfo=UTC)  # Sunday, weekday=6
    monday = datetime(2026, 7, 13, 19, 0, tzinfo=UTC)

    assert weekly_due(None, 6, 18, sunday_evening) is True
    assert weekly_due(sunday_evening - timedelta(days=7), 6, 18, sunday_evening) is True
    assert weekly_due(sunday_evening - timedelta(hours=1), 6, 18, sunday_evening) is False
    assert weekly_due(None, 6, 18, monday) is False
    assert weekly_due(None, 6, 20, sunday_evening) is False
