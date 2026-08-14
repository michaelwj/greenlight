from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_parent_auth
from app.db.session import get_db
from app.models.entities import ChannelRule, ParentUser
from app.schemas.channel_rules import ChannelRuleRead, ChannelRuleUpsert
from app.services.audit import write_audit_log
from app.services.channel_rules import ChannelRuleService

router = APIRouter(prefix="/api/channel-rules", tags=["channel-rules"])


@router.get("", response_model=list[ChannelRuleRead])
async def list_channel_rules(
    _: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> list[ChannelRuleRead]:
    result = await db.execute(select(ChannelRule).order_by(ChannelRule.channel_name))
    return [ChannelRuleRead.model_validate(item) for item in result.scalars().all()]


@router.post("", response_model=ChannelRuleRead)
async def upsert_channel_rule(
    payload: ChannelRuleUpsert,
    parent: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> ChannelRuleRead:
    if payload.status not in {"trusted", "blocked"}:
        raise HTTPException(status_code=422, detail="status must be 'trusted' or 'blocked'")

    rule = await ChannelRuleService(db).upsert(
        channel_name=payload.channel_name,
        channel_id=payload.channel_id,
        status=payload.status,
        added_by=parent.id,
        subscribed=payload.subscribed,
        subscribed_child_id=payload.subscribed_child_id,
        notes=payload.notes,
    )
    await write_audit_log(
        db,
        actor_type="parent",
        actor_id=parent.id,
        action=f"channel_rule_{payload.status}",
        target_type="channel_rule",
        target_id=rule.id,
        metadata_json={"channel_name": rule.channel_name},
    )
    await db.commit()
    return ChannelRuleRead.model_validate(rule)


@router.delete("/{rule_id}")
async def delete_channel_rule(
    rule_id: str,
    parent: ParentUser = Depends(require_parent_auth),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rule = await db.get(ChannelRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Channel rule not found")

    await db.delete(rule)
    await write_audit_log(
        db,
        actor_type="parent",
        actor_id=parent.id,
        action="channel_rule_deleted",
        target_type="channel_rule",
        target_id=rule_id,
        metadata_json={"channel_name": rule.channel_name},
    )
    await db.commit()
    return {"deleted": rule_id}
