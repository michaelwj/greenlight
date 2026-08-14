from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.entities import Child, YoutubeRequest
from app.services.digest import WeeklyDigestService


async def _seed(db_session) -> Child:
    child = Child(display_name="Kid")
    db_session.add(child)
    await db_session.commit()

    now = datetime.now(UTC)
    rows = [
        YoutubeRequest(
            requested_by_child_id=child.id,
            youtube_url="u1",
            title="Auto approved lesson",
            channel_name="Math Teacher",
            status="available",
            decision_source="auto",
            decided_at=now - timedelta(days=1),
            allowance_bucket="educational",
        ),
        YoutubeRequest(
            requested_by_child_id=child.id,
            youtube_url="u2",
            title="Denied video",
            channel_name="Random Channel",
            status="rejected",
            decision_source="auto",
            denial_reason="This channel is blocked.",
            decided_at=now - timedelta(days=2),
            allowance_bucket="entertainment",
        ),
        YoutubeRequest(
            requested_by_child_id=child.id,
            youtube_url="u3",
            title="Waiting video",
            channel_name="Random Channel",
            status="needs_review",
            allowance_bucket="entertainment",
        ),
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return child


async def test_digest_payload_summarizes_week(db_session) -> None:
    await _seed(db_session)
    service = WeeklyDigestService(db_session)

    now = datetime.now(UTC)
    payload = await service.build_payload(now - timedelta(days=7), now)

    assert payload["total_requests"] == 3
    assert payload["by_status"]["rejected"] == 1
    assert payload["by_status"]["needs_review"] == 1
    assert payload["denials"][0]["reason"] == "This channel is blocked."
    assert payload["top_channels"][0]["channel"] == "Random Channel"
    assert payload["budgets"][0]["child"] == "Kid"
    assert "1 auto-approved" in payload["summary_line"]


async def test_digest_run_persists_and_notifies(db_session) -> None:
    await _seed(db_session)
    service = WeeklyDigestService(db_session)

    with patch(
        "app.services.digest.NotificationService.send_digest_notification"
    ) as mock_notify:
        digest = await service.run()

    assert digest.id
    assert digest.payload_json["total_requests"] == 3
    mock_notify.assert_called_once()
