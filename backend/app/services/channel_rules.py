from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import ChannelRule, ChannelRuleStatus


def _env_list(raw: str) -> set[str]:
    return {value.strip().lower() for value in raw.split(",") if value.strip()}


class ChannelRuleService:
    """Channel trust/block lookups. DB rules win; env lists act as seed fallbacks."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()

    async def lookup(self, channel_id: str | None, channel_name: str | None) -> str | None:
        """Return 'trusted', 'blocked', or None for an unknown channel."""
        rule = await self.find_rule(channel_id, channel_name)
        if rule:
            return rule.status

        name = (channel_name or "").strip().lower()
        if name and name in _env_list(self.settings.blocked_channels):
            return ChannelRuleStatus.BLOCKED.value
        if name and name in _env_list(self.settings.trusted_channels):
            return ChannelRuleStatus.TRUSTED.value
        return None

    async def find_rule(self, channel_id: str | None, channel_name: str | None) -> ChannelRule | None:
        conditions = []
        if channel_id:
            conditions.append(ChannelRule.channel_id == channel_id)
        if channel_name:
            conditions.append(func.lower(ChannelRule.channel_name) == channel_name.strip().lower())
        if not conditions:
            return None

        result = await self.session.execute(select(ChannelRule).where(or_(*conditions)))
        rules = result.scalars().all()
        # Prefer an exact channel_id match over a name match.
        for rule in rules:
            if channel_id and rule.channel_id == channel_id:
                return rule
        return rules[0] if rules else None

    async def upsert(
        self,
        channel_name: str,
        channel_id: str | None = None,
        status: str = ChannelRuleStatus.TRUSTED.value,
        added_by: str | None = None,
        subscribed: bool | None = None,
        subscribed_child_id: str | None = None,
        notes: str | None = None,
    ) -> ChannelRule:
        rule = await self.find_rule(channel_id, channel_name)
        if rule is None:
            rule = ChannelRule(channel_name=channel_name, channel_id=channel_id)
            self.session.add(rule)

        rule.channel_name = channel_name
        if channel_id:
            rule.channel_id = channel_id
        rule.status = status
        if added_by:
            rule.added_by = added_by
        if subscribed is not None:
            rule.subscribed = subscribed
        if subscribed_child_id is not None:
            rule.subscribed_child_id = subscribed_child_id
        if notes is not None:
            rule.notes = notes

        await self.session.commit()
        await self.session.refresh(rule)
        return rule
