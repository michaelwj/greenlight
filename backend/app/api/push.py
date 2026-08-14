from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_parent_auth
from app.core.config import get_settings
from app.db.session import get_db
from app.models.entities import ParentUser, PushSubscription

router = APIRouter(prefix="/api/push", tags=["push"])


class PushSubscribePayload(BaseModel):
    endpoint: str
    keys: dict
    device_label: str | None = None


class PushUnsubscribePayload(BaseModel):
    endpoint: str


@router.get("/public-key")
async def get_public_key(_: ParentUser = Depends(require_parent_auth)) -> dict:
    settings = get_settings()
    if not settings.vapid_public_key:
        raise HTTPException(status_code=503, detail="Web push is not configured (missing VAPID keys)")
    return {"public_key": settings.vapid_public_key}


@router.post("/subscribe")
async def subscribe(
    payload: PushSubscribePayload,
    parent: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    subscription = result.scalars().first()
    if subscription:
        subscription.parent_user_id = parent.id
        subscription.keys_json = payload.keys
        subscription.device_label = payload.device_label
    else:
        subscription = PushSubscription(
            parent_user_id=parent.id,
            endpoint=payload.endpoint,
            keys_json=payload.keys,
            device_label=payload.device_label,
        )
        db.add(subscription)

    await db.commit()
    return {"status": "subscribed"}


@router.post("/unsubscribe")
async def unsubscribe(
    payload: PushUnsubscribePayload,
    parent: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint))
    subscription = result.scalars().first()
    if subscription:
        await db.delete(subscription)
        await db.commit()
    return {"status": "unsubscribed"}
