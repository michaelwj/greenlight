from pydantic import BaseModel, Field


class YoutubeTogglePayload(BaseModel):
    minutes: int = Field(default=30, ge=1, le=1440)


class ActionResultRead(BaseModel):
    provider: str
    action: str
    success: bool
    provider_ref: str | None = None
    error_message: str | None = None
