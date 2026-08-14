from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.entities import (
    ChannelRuleStatus,
    DecisionSource,
    YoutubeRequest,
    YoutubeSafetyStatus,
    YoutubeStatus,
)
from app.services.budgets import BudgetService, minutes_for_duration
from app.services.channel_rules import ChannelRuleService
from app.youtube.classifier import AIClassifier, bucket_for_category
from app.youtube.transcript import fetch_transcript

try:
    from yt_dlp import YoutubeDL
except Exception:  # noqa: BLE001
    YoutubeDL = None

_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})")


def extract_video_id(url: str) -> str | None:
    """Parse the 11-char YouTube video id out of any common URL shape."""
    match = _YT_ID_RE.search(url or "")
    return match.group(1) if match else None


@dataclass(slots=True)
class HardRuleResult:
    passed: bool
    decision: str
    reasons: list[str]


# Kid-visible denial messages keyed by machine reason.
DENIAL_MESSAGES = {
    "blocked_channel": "This channel is blocked.",
    "age_restricted": "This video is age-restricted.",
    "shorts_not_allowed": "Shorts aren't allowed — pick a full video.",
    "livestream_not_allowed": "Livestreams aren't allowed.",
    "duration_over_limit": "This video is longer than the allowed limit.",
    "unavailable_video": "This video isn't publicly available.",
    "budget_exhausted": "You're out of fun-video minutes this week. Educational videos are always open!",
    "flagged_by_screening": "The content screener flagged this video.",
}


class YoutubeReviewPipeline:
    """Screening engine: metadata -> transcript -> hard rules -> channel trust ->
    AI classification -> budget -> decision tier (auto_approved / needs_review / auto_denied)."""

    def __init__(self, session: AsyncSession, classifier: AIClassifier | None = None) -> None:
        self.session = session
        self.settings = get_settings()
        self.classifier = classifier or AIClassifier()

    async def analyze_request(self, request: YoutubeRequest) -> YoutubeRequest:
        request.status = YoutubeStatus.ANALYZING.value
        request.denial_reason = None
        request.decision_source = None
        request.decided_at = None
        request.minutes_charged = 0
        request.review_reasons = None
        await self.session.commit()

        try:
            return await self._analyze(request)
        except Exception as err:  # noqa: BLE001
            await self.session.rollback()
            self._fail_analysis(request, err)
            await self.session.commit()
            await self.session.refresh(request)
            return request

    async def _analyze(self, request: YoutubeRequest) -> YoutubeRequest:
        metadata = self._extract_metadata(request.youtube_url)
        request.video_id = metadata.get("id")
        request.title = metadata.get("title")
        request.channel_name = metadata.get("channel")
        request.channel_id = metadata.get("channel_id")
        request.duration_seconds = metadata.get("duration")
        request.description = metadata.get("description")
        request.publish_date = metadata.get("upload_date")
        request.thumbnail_url = metadata.get("thumbnail")

        transcript_text = await self._get_transcript(metadata)
        request.transcript_text = transcript_text

        channel_status = await ChannelRuleService(self.session).lookup(
            request.channel_id, request.channel_name
        )

        hard_rules = self._evaluate_hard_rules(metadata, channel_status, request.youtube_url)
        request.hard_rule_results = {
            "passed": hard_rules.passed,
            "decision": hard_rules.decision,
            "reasons": hard_rules.reasons,
            "channel_status": channel_status,
        }

        if hard_rules.decision == "blocked":
            request.classified_category = "other"
            request.allowance_bucket = "blocked"
            request.safety_status = YoutubeSafetyStatus.BLOCKED.value
            request.ai_summary = "Blocked by hard rules."
            request.ai_concerns = hard_rules.reasons
            self._deny(request, hard_rules.reasons[0] if hard_rules.reasons else "blocked_channel")
            await self.session.commit()
            await self.session.refresh(request)
            return request

        ai_result = await self.classifier.classify(metadata, transcript_text)
        request.classified_category = ai_result["category"]
        request.ai_confidence = ai_result["confidence"]
        request.ai_summary = ai_result["summary"]
        request.ai_concerns = ai_result["concerns"]

        bucket = bucket_for_category(ai_result["category"])
        request.allowance_bucket = bucket

        await self._decide(request, metadata, transcript_text, channel_status, hard_rules, ai_result, bucket)

        await self.session.commit()
        await self.session.refresh(request)
        return request

    async def _decide(
        self,
        request: YoutubeRequest,
        metadata: dict[str, Any],
        transcript_text: str | None,
        channel_status: str | None,
        hard_rules: HardRuleResult,
        ai_result: dict[str, Any],
        bucket: str,
    ) -> None:
        trusted = channel_status == ChannelRuleStatus.TRUSTED.value
        threshold = self.settings.ai_confidence_threshold
        safety = ai_result["safety_status"]
        confident = ai_result["confidence"] >= threshold
        flagged_topics = [str(t) for t in ai_result.get("flagged_topics") or []]

        # AI is confident the content is unsafe -> deny outright; parents see it in history.
        if safety == "unsafe" and confident:
            request.safety_status = YoutubeSafetyStatus.BLOCKED.value
            self._deny(request, "flagged_by_screening")
            return

        transcript_ok = (
            transcript_text is not None or not self.settings.require_transcript_for_auto_approve
        )
        clean_and_confident = safety == "safe" and confident and transcript_ok

        # Short runtimes are a spam / low-depth indicator: never auto-approve,
        # let a parent judge. (True Shorts <= 60s are hard-blocked earlier.)
        short_min = self.settings.short_video_review_minutes
        duration = request.duration_seconds or 0
        too_short = bool(short_min) and 0 < duration < short_min * 60

        # Why auto-approval is not happening — shown to the parent verbatim.
        reasons: list[str] = []
        pct = round(ai_result["confidence"] * 100)
        if flagged_topics:
            reasons.extend(f"Flagged topic: {topic}" for topic in flagged_topics)
        if too_short:
            reasons.append(
                f"Short video ({max(1, round(duration / 60))} min) — under the "
                f"{short_min}-minute depth check"
            )
        if not hard_rules.passed:
            reasons.extend(f"Rule flag: {r}" for r in hard_rules.reasons)
        if safety == "needs_review":
            reasons.append("The screener judged the content borderline")
        elif safety == "unsafe":
            reasons.append(f"The screener suspects unsafe content but confidence ({pct}%) is below the {round(threshold * 100)}% threshold")
        if not confident and safety == "safe":
            reasons.append(
                f"AI confidence {pct}% is below the {round(threshold * 100)}% auto-approve threshold"
            )
        if not transcript_ok:
            reasons.append("No transcript available (transcript required for auto-approve)")

        def needs_review() -> None:
            request.safety_status = YoutubeSafetyStatus.NEEDS_REVIEW.value
            request.status = YoutubeStatus.NEEDS_REVIEW.value
            request.review_reasons = reasons or ["Did not meet any auto-approve rule"]

        # Sensitive topics and short videos never auto-approve — not even from
        # trusted channels.
        if flagged_topics or too_short:
            needs_review()
            return

        if bucket == "educational":
            if hard_rules.passed and (trusted or clean_and_confident):
                request.safety_status = YoutubeSafetyStatus.APPROVED.value
                self._approve(request, charge_minutes=0)
            else:
                if not trusted and not reasons:
                    reasons.append("Channel is not on the trusted list")
                needs_review()
            return

        # Entertainment bucket: budget applies.
        minutes = minutes_for_duration(request.duration_seconds)
        budget = await BudgetService(self.session).status(request.requested_by_child_id)
        if minutes > budget.remaining_minutes:
            request.safety_status = YoutubeSafetyStatus.BLOCKED.value
            self._deny(request, "budget_exhausted")
            return

        auto_ok = trusted or (self.settings.auto_approve_entertainment and clean_and_confident)
        if hard_rules.passed and auto_ok:
            request.safety_status = YoutubeSafetyStatus.APPROVED.value
            self._approve(request, charge_minutes=minutes)
        else:
            if not trusted:
                if self.settings.auto_approve_entertainment:
                    reasons.append("Channel is not on the trusted list")
                else:
                    reasons.append(
                        "Entertainment videos always need a parent decision (channel not trusted)"
                    )
            needs_review()

    def _approve(self, request: YoutubeRequest, charge_minutes: int) -> None:
        request.status = YoutubeStatus.APPROVED.value
        request.decision_source = DecisionSource.AUTO.value
        request.decided_at = datetime.now(UTC)
        request.minutes_charged = charge_minutes

    def _deny(self, request: YoutubeRequest, reason: str) -> None:
        request.status = YoutubeStatus.REJECTED.value
        request.decision_source = DecisionSource.AUTO.value
        request.decided_at = datetime.now(UTC)
        request.denial_reason = DENIAL_MESSAGES.get(reason, reason)

    def _fail_analysis(self, request: YoutubeRequest, err: Exception) -> None:
        message = str(err)
        lowered = message.lower()
        if "is not a valid url" in lowered:
            reason = (
                "That doesn't look like a YouTube link — use the Share button "
                "to copy the video URL and try again."
            )
        elif "restricted" in lowered or "unavailable" in lowered or "private" in lowered:
            reason = "YouTube says this video isn't available here. A parent can look into it."
        else:
            reason = "Something went wrong while checking this video. Try again in a bit."
        request.status = YoutubeStatus.FAILED.value
        request.denial_reason = reason
        request.ai_concerns = (request.ai_concerns or []) + [f"analysis_error:{message[:300]}"]

    def _extract_metadata(self, youtube_url: str) -> dict[str, Any]:
        if YoutubeDL is None:
            return {"title": "Unknown", "channel": "Unknown", "duration": None}

        options = {
            "quiet": True,
            "skip_download": True,
            "no_warnings": True,
        }
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            if not isinstance(info, dict):
                return {}
            return info

    async def _get_transcript(self, metadata: dict[str, Any]) -> str | None:
        try:
            return await fetch_transcript(metadata)
        except Exception:  # noqa: BLE001
            return None

    def _evaluate_hard_rules(
        self, metadata: dict[str, Any], channel_status: str | None, youtube_url: str = ""
    ) -> HardRuleResult:
        reasons: list[str] = []

        title = (metadata.get("title") or "").lower()
        duration = int(metadata.get("duration") or 0)
        aspect_ratio = metadata.get("aspect_ratio")
        looks_like_short = (
            "/shorts/" in (youtube_url or "")
            or "#shorts" in title
            or re.search(r"\bshorts\b", title)
            or (0 < duration <= 60)
            or (aspect_ratio is not None and float(aspect_ratio) < 1)
        )
        if looks_like_short:
            reasons.append("shorts_not_allowed")

        if metadata.get("is_live") or metadata.get("was_live"):
            reasons.append("livestream_not_allowed")

        if int(metadata.get("age_limit") or 0) > 0:
            reasons.append("age_restricted")

        availability = (metadata.get("availability") or "public").lower()
        if availability in {"private", "subscriber_only", "premium_only", "needs_auth"}:
            reasons.append("unavailable_video")

        max_duration = self.settings.youtube_max_duration_seconds
        duration = metadata.get("duration")
        if duration and max_duration and int(duration) > max_duration:
            reasons.append("duration_over_limit")

        if channel_status == ChannelRuleStatus.BLOCKED.value:
            reasons.append("blocked_channel")

        if "blocked_channel" in reasons or "age_restricted" in reasons or "shorts_not_allowed" in reasons:
            return HardRuleResult(passed=False, decision="blocked", reasons=reasons)

        if reasons:
            return HardRuleResult(passed=False, decision="needs_review", reasons=reasons)

        return HardRuleResult(passed=True, decision="approved", reasons=[])
