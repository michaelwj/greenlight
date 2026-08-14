from unittest.mock import patch

from app.models.entities import ParentUser, PushSubscription
from app.services.notifications import NotificationService


async def _make_subscription(db_session) -> PushSubscription:
    parent = ParentUser(name="Mom", email="mom@example.com")
    db_session.add(parent)
    await db_session.commit()

    subscription = PushSubscription(
        parent_user_id=parent.id,
        endpoint="https://push.example.test/sub/1",
        keys_json={"p256dh": "key", "auth": "auth"},
    )
    db_session.add(subscription)
    await db_session.commit()
    return subscription


async def test_broadcast_skips_without_vapid_key(db_session, monkeypatch) -> None:
    await _make_subscription(db_session)
    service = NotificationService(db_session)
    monkeypatch.setattr(service.settings, "vapid_private_key", "")

    with patch("app.services.notifications.webpush") as mock_push:
        await service.send_decision_notification("req-1", "approved")

    mock_push.assert_not_called()


async def test_broadcast_sends_to_each_subscription(db_session, monkeypatch) -> None:
    await _make_subscription(db_session)
    service = NotificationService(db_session)
    monkeypatch.setattr(service.settings, "vapid_private_key", "fake-key")
    monkeypatch.setattr(service.settings, "vapid_subject", "mailto:test@example.com")

    with patch("app.services.notifications.webpush") as mock_push:
        await service.send_decision_notification("req-1", "approved")

    assert mock_push.call_count == 1
    kwargs = mock_push.call_args.kwargs
    assert kwargs["subscription_info"]["endpoint"] == "https://push.example.test/sub/1"
    assert kwargs["vapid_private_key"] == "fake-key"
