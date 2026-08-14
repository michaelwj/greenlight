from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Greenlight"
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_secret_key: str = Field(default="change-me", alias="APP_SECRET_KEY")
    household_code: str = Field(default="0000", alias="HOUSEHOLD_CODE")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@db:5432/greenlight",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    vapid_public_key: str = Field(default="", alias="VAPID_PUBLIC_KEY")
    vapid_private_key: str = Field(default="", alias="VAPID_PRIVATE_KEY")
    vapid_subject: str = Field(default="mailto:admin@example.com", alias="VAPID_SUBJECT")
    kid_web_dir: str = Field(default="../kid-web", alias="KID_WEB_DIR")
    parent_web_dir: str = Field(default="../parent-web", alias="PARENT_WEB_DIR")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    ai_provider: str = Field(default="api", alias="AI_PROVIDER")  # api | anthropic | command
    ai_command: str = Field(default="", alias="AI_COMMAND")
    ai_command_timeout_seconds: int = Field(default=180, alias="AI_COMMAND_TIMEOUT_SECONDS")
    ai_model: str = Field(default="gpt-4.1-mini", alias="AI_MODEL")
    ai_base_url: str = Field(default="https://api.openai.com/v1", alias="AI_BASE_URL")
    ai_confidence_threshold: float = Field(default=0.75, alias="AI_CONFIDENCE_THRESHOLD")
    require_transcript_for_auto_approve: bool = Field(
        default=False, alias="REQUIRE_TRANSCRIPT_FOR_AUTO_APPROVE"
    )
    # Topics that must never auto-approve — anything the classifier flags here
    # goes to a parent, even from trusted channels. Comma-separated.
    sensitive_topics: str = Field(
        default=(
            "health or medical advice, human anatomy, "
            "romantic relationships or dating (girlfriends, boyfriends), "
            "sexual content or sexual innuendo, "
            "neurological or mental-health issues, "
            "LGBTQ topics, "
            "violence or graphic content, "
            "domestic abuse, "
            "law breaking or crime glorification, "
            "legal advice, "
            "misogynistic or manosphere influencer content (Andrew Tate style), "
            "hate speech, racism, or discrimination"
        ),
        alias="SENSITIVE_TOPICS",
    )
    daily_request_limit: int = Field(default=10, alias="DAILY_REQUEST_LIMIT")
    household_timezone: str = Field(default="America/Chicago", alias="HOUSEHOLD_TIMEZONE")
    # Videos shorter than this never auto-approve — short runtimes are a spam /
    # low-depth indicator. 0 disables.
    short_video_review_minutes: int = Field(default=5, alias="SHORT_VIDEO_REVIEW_MINUTES")
    youtube_max_duration_seconds: int = Field(default=1800, alias="YOUTUBE_MAX_DURATION_SECONDS")
    trusted_channels: str = Field(default="", alias="TRUSTED_CHANNELS")
    blocked_channels: str = Field(default="", alias="BLOCKED_CHANNELS")
    auto_approve_entertainment: bool = Field(default=False, alias="AUTO_APPROVE_ENTERTAINMENT")
    default_entertainment_weekly_minutes: int = Field(
        default=120, alias="DEFAULT_ENTERTAINMENT_WEEKLY_MINUTES"
    )
    transcript_max_chars: int = Field(default=12000, alias="TRANSCRIPT_MAX_CHARS")
    subscription_poll_hours: int = Field(default=6, alias="SUBSCRIPTION_POLL_HOURS")
    subscription_max_new_per_poll: int = Field(default=3, alias="SUBSCRIPTION_MAX_NEW_PER_POLL")
    entertainment_retention_days: int = Field(default=30, alias="ENTERTAINMENT_RETENTION_DAYS")
    sponsorblock_enabled: bool = Field(default=True, alias="SPONSORBLOCK_ENABLED")
    download_max_retries: int = Field(default=3, alias="DOWNLOAD_MAX_RETRIES")
    download_retry_delays: str = Field(default="30,60,90", alias="DOWNLOAD_RETRY_DELAYS")
    youtube_min_gap_seconds: int = Field(default=30, alias="YOUTUBE_MIN_GAP_SECONDS")
    digest_weekday: int = Field(default=6, alias="DIGEST_WEEKDAY")  # 0=Mon .. 6=Sun
    digest_hour_utc: int = Field(default=18, alias="DIGEST_HOUR_UTC")
    plex_media_root: str = Field(default="/media/greenlight", alias="PLEX_MEDIA_ROOT")
    plex_url: str = Field(default="", alias="PLEX_URL")
    plex_token: str = Field(default="", alias="PLEX_TOKEN")
    plex_library_section_id: str = Field(default="", alias="PLEX_LIBRARY_SECTION_ID")
    plex_label: str = Field(default="youtube", alias="PLEX_LABEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
