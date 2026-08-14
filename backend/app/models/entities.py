from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class YoutubeSafetyStatus(StrEnum):
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class YoutubeParentDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDE = "override"


class YoutubeStatus(StrEnum):
    SUBMITTED = "submitted"
    ANALYZING = "analyzing"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    DOWNLOADING = "downloading"
    AVAILABLE = "available"
    FAILED = "failed"
    REMOVED = "removed"


class ChannelRuleStatus(StrEnum):
    TRUSTED = "trusted"
    BLOCKED = "blocked"


class DecisionSource(StrEnum):
    AUTO = "auto"
    PARENT = "parent"


class RequestSource(StrEnum):
    KID_REQUEST = "kid_request"
    SUBSCRIPTION = "subscription"


class ParentUser(Base):
    __tablename__ = "parent_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    auth_token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    parent_user_id: Mapped[str] = mapped_column(ForeignKey("parent_users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    keys_json: Mapped[dict] = mapped_column(JSON)
    device_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Child(Base):
    __tablename__ = "children"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_name: Mapped[str] = mapped_column(String(120))
    kid_pin_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # None -> fall back to the global DAILY_REQUEST_LIMIT setting.
    daily_request_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChildDevice(Base):
    __tablename__ = "child_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"))
    device_token: Mapped[str] = mapped_column(String(255), unique=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class YoutubeRequest(Base):
    __tablename__ = "youtube_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    requested_by_child_id: Mapped[str] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"))
    youtube_url: Mapped[str] = mapped_column(Text)
    video_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    publish_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    classified_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    allowance_bucket: Mapped[str | None] = mapped_column(String(80), nullable=True)
    safety_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_concerns: Mapped[list | None] = mapped_column(JSON, nullable=True)
    review_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    hard_rule_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    parent_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decision_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    denial_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    minutes_charged: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(20), default=RequestSource.KID_REQUEST.value)
    status: Mapped[str] = mapped_column(String(20), default=YoutubeStatus.SUBMITTED.value)
    local_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    plex_library_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    plex_item_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class YoutubeAsset(Base):
    __tablename__ = "youtube_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    youtube_request_id: Mapped[str] = mapped_column(ForeignKey("youtube_requests.id", ondelete="CASCADE"))
    asset_type: Mapped[str] = mapped_column(String(40))
    file_path: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChannelRule(Base):
    __tablename__ = "channel_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    channel_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    channel_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default=ChannelRuleStatus.TRUSTED.value)
    subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    subscribed_child_id: Mapped[str | None] = mapped_column(ForeignKey("children.id", ondelete="SET NULL"), nullable=True)
    added_by: Mapped[str | None] = mapped_column(ForeignKey("parent_users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CategoryBudget(Base):
    __tablename__ = "category_budgets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id", ondelete="CASCADE"))
    bucket: Mapped[str] = mapped_column(String(40), default="entertainment")
    weekly_minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    request_type: Mapped[str] = mapped_column(String(40))
    request_id: Mapped[str] = mapped_column(String(36))
    parent_user_id: Mapped[str | None] = mapped_column(ForeignKey("parent_users.id"), nullable=True)
    decision: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(120))
    target_type: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WeeklyDigest(Base):
    __tablename__ = "weekly_digests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    week_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    week_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
