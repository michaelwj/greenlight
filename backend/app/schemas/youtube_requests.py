from datetime import datetime

from pydantic import BaseModel


class YoutubeRequestCreate(BaseModel):
    requested_by_child_id: str
    youtube_url: str
    requested_category: str | None = None
    notes: str | None = None


class YoutubeDecision(BaseModel):
    parent_user_id: str | None = None
    reason: str | None = None


class YoutubeRequestRead(BaseModel):
    id: str
    requested_by_child_id: str
    requested_by_name: str | None = None
    youtube_url: str
    video_id: str | None
    title: str | None
    channel_name: str | None
    channel_id: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    requested_category: str | None
    classified_category: str | None
    allowance_bucket: str | None
    safety_status: str | None
    ai_confidence: float | None
    ai_summary: str | None
    ai_concerns: list | None
    review_reasons: list | None
    hard_rule_results: dict | None
    parent_decision: str | None
    decision_source: str | None
    decided_at: datetime | None
    denial_reason: str | None
    minutes_charged: int
    source: str
    status: str
    local_file_path: str | None
    plex_library_path: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
