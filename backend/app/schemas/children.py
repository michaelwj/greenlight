from datetime import datetime

from pydantic import BaseModel


class ChildCreate(BaseModel):
    display_name: str
    kid_pin_hash: str | None = None


class ChildUpdate(BaseModel):
    display_name: str | None = None
    kid_pin_hash: str | None = None
    is_active: bool | None = None


class RequestLimitUpdate(BaseModel):
    daily_request_limit: int | None = None  # None -> use the global default


class ChildRead(BaseModel):
    id: str
    display_name: str
    kid_pin_hash: str | None
    is_active: bool
    daily_request_limit: int | None = None
    created_at: datetime

    class Config:
        from_attributes = True
