from datetime import datetime

from pydantic import BaseModel


class ChannelRuleUpsert(BaseModel):
    channel_name: str
    channel_id: str | None = None
    status: str = "trusted"
    subscribed: bool | None = None
    subscribed_child_id: str | None = None
    notes: str | None = None


class ChannelRuleRead(BaseModel):
    id: str
    channel_id: str | None
    channel_name: str
    status: str
    subscribed: bool
    subscribed_child_id: str | None
    notes: str | None
    last_polled_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True
