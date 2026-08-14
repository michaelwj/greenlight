from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CATEGORIES = (
    "education",
    "tutorial",
    "music_tutorial",
    "science",
    "documentary",
    "entertainment",
    "gaming",
    "music_video",
    "other",
)

EDUCATIONAL_CATEGORIES = {"education", "tutorial", "music_tutorial", "science", "documentary"}

SAFETY_STATUSES = ("safe", "needs_review", "unsafe")

_SYSTEM_PROMPT_TEMPLATE = """You are a strict content screener for a family's YouTube-to-Plex pipeline.
Parents allow educational content (lessons, tutorials, music tutorials, science, documentaries)
to auto-download; entertainment is limited; unsafe content must be flagged.

Given a video's title, channel, description, and transcript, respond with ONLY a JSON object:
{
  "category": one of %s,
  "safety_status": "safe" | "needs_review" | "unsafe",
  "confidence": number between 0 and 1,
  "summary": one-sentence summary a parent can skim,
  "concerns": array of short strings (empty if none),
  "flagged_topics": array of short strings (empty if none)
}

Rules:
- "safe" means appropriate for children with no profanity, violence, sexual content,
  dangerous activities, gambling/consumerism pressure, or mature themes.
- Use "needs_review" when uncertain or when content is borderline.
- Use "unsafe" only when the transcript or metadata clearly shows inappropriate content.
- Category reflects the actual content, not the title's claims. Clickbait "learning" titles
  with entertainment content are "entertainment".
- "music_tutorial" covers anything that teaches or demonstrates how to play music: piano
  tutorials (including Synthesia-style falling-note videos), instrument lessons, covers
  presented as practice/technique material, sheet-music play-alongs. "music_video" is for
  produced music entertainment (official videos, lyric videos, concerts, compilations).
- Many legitimate videos have NO transcript because they contain no speech — instrumental
  tutorials, performances, timelapses. Do not lower confidence just because the transcript
  is missing; judge from the title, channel, description, tags, and category instead.
- Lower your confidence when a transcript exists but is short or truncated.
- This pipeline exists primarily for education and learning. Low-value noise — hype,
  drama, reaction content, pranks, clickbait compilations, "influencer" lifestyle filler —
  is NEVER an educational category; classify it as "entertainment" or "other" no matter
  how the title frames it.

Parent-review topics: the parents require a human decision on these subjects:
%s.
If the video touches ANY of them — even briefly, jokingly, or as innuendo — list each
matching topic (short phrase) in "flagged_topics". A flagged topic does NOT by itself make
the video "unsafe" or change its category; it just routes the video to a parent. Leave
"flagged_topics" empty when none apply."""


def build_system_prompt(sensitive_topics: str | None = None) -> str:
    topics = sensitive_topics if sensitive_topics is not None else get_settings().sensitive_topics
    return _SYSTEM_PROMPT_TEMPLATE % (
        " | ".join(f'"{c}"' for c in CATEGORIES),
        topics or "(none configured)",
    )


def classify_heuristic(metadata: dict[str, Any], transcript_text: str | None) -> dict[str, Any]:
    """Deterministic fallback used when no AI key is configured or the AI call fails.

    Never returns "safe" — without an AI read of the transcript, borderline content must
    land on a parent.
    """
    title = (metadata.get("title") or "").lower()
    educational_words = ("learn", "lesson", "tutorial", "course", "how to", "explained", "science")
    category = "education" if any(word in title for word in educational_words) else "other"
    return {
        "category": category,
        "safety_status": "needs_review",
        "confidence": 0.3,
        "summary": "Heuristic classification only; AI screening unavailable.",
        "concerns": ["ai_unavailable"],
        "flagged_topics": [],
    }


def validate_ai_payload(data: dict[str, Any]) -> dict[str, Any]:
    required = {"category", "safety_status", "confidence", "summary", "concerns"}
    missing = required - set(data.keys())
    if missing:
        raise ValueError(f"Missing AI fields: {sorted(missing)}")
    if data["category"] not in CATEGORIES:
        raise ValueError(f"Unknown category: {data['category']}")
    if data["safety_status"] not in SAFETY_STATUSES:
        raise ValueError(f"Unknown safety_status: {data['safety_status']}")
    confidence = float(data["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"Confidence out of range: {confidence}")
    if not isinstance(data["concerns"], list):
        raise ValueError("concerns must be a list")
    if not isinstance(data.get("flagged_topics", []), list):
        raise ValueError("flagged_topics must be a list")
    data.setdefault("flagged_topics", [])
    data["confidence"] = confidence
    return data


def extract_json_object(text: str) -> dict[str, Any]:
    """Pull the last parseable JSON object out of arbitrary CLI output."""
    decoder = json.JSONDecoder()
    candidates = [i for i, char in enumerate(text) if char == "{"]
    result: dict[str, Any] | None = None
    for start in candidates:
        try:
            parsed, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(parsed, dict):
            result = parsed
    if result is None:
        raise ValueError("No JSON object found in command output")
    return result


class AIClassifier:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        if self.settings.ai_provider == "command":
            return bool(self.settings.ai_command)
        if self.settings.ai_provider == "anthropic":
            return bool(self.settings.anthropic_api_key)
        return bool(self.settings.openai_api_key)

    async def classify(self, metadata: dict[str, Any], transcript_text: str | None) -> dict[str, Any]:
        if not self.enabled:
            return classify_heuristic(metadata, transcript_text)

        try:
            if self.settings.ai_provider == "command":
                return await self._classify_with_command(metadata, transcript_text)
            if self.settings.ai_provider == "anthropic":
                return await self._classify_with_anthropic(metadata, transcript_text)
            return await self._classify_with_ai(metadata, transcript_text)
        except Exception as err:  # noqa: BLE001
            logger.warning("AI classification failed, using heuristic fallback: %s", err)
            result = classify_heuristic(metadata, transcript_text)
            result["concerns"] = [f"ai_error:{type(err).__name__}"]
            return result

    def _user_content(self, metadata: dict[str, Any], transcript_text: str | None) -> str:
        return json.dumps(
            {
                "title": metadata.get("title"),
                "channel": metadata.get("channel"),
                "description": (metadata.get("description") or "")[:4000],
                "duration_seconds": metadata.get("duration"),
                "youtube_categories": metadata.get("categories"),
                "tags": (metadata.get("tags") or [])[:20],
                "transcript": transcript_text
                or "(no transcript — likely a video without speech, e.g. instrumental music)",
            }
        )

    async def _classify_with_command(
        self, metadata: dict[str, Any], transcript_text: str | None
    ) -> dict[str, Any]:
        import asyncio

        prompt = (
            f"{build_system_prompt()}\n\n"
            "Respond with ONLY the JSON object — no prose, no markdown fences.\n\n"
            f"Video to screen:\n{self._user_content(metadata, transcript_text)}\n"
        )
        process = await asyncio.create_subprocess_shell(
            self.settings.ai_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")),
                timeout=self.settings.ai_command_timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            raise ValueError("AI command timed out") from None

        if process.returncode != 0:
            raise ValueError(
                f"AI command exited {process.returncode}: {stderr.decode('utf-8', 'replace')[:500]}"
            )
        return validate_ai_payload(extract_json_object(stdout.decode("utf-8", "replace")))

    async def _classify_with_anthropic(
        self, metadata: dict[str, Any], transcript_text: str | None
    ) -> dict[str, Any]:
        from anthropic import AsyncAnthropic

        schema = {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "safety_status": {"type": "string", "enum": list(SAFETY_STATUSES)},
                "confidence": {"type": "number"},
                "summary": {"type": "string"},
                "concerns": {"type": "array", "items": {"type": "string"}},
                "flagged_topics": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "category", "safety_status", "confidence", "summary", "concerns", "flagged_topics"
            ],
            "additionalProperties": False,
        }

        client = AsyncAnthropic(api_key=self.settings.anthropic_api_key)
        try:
            response = await client.messages.create(
                model=self.settings.ai_model,
                max_tokens=1024,
                system=build_system_prompt(),
                output_config={"format": {"type": "json_schema", "schema": schema}},
                messages=[
                    {"role": "user", "content": self._user_content(metadata, transcript_text)}
                ],
            )
        finally:
            await client.close()

        if response.stop_reason == "refusal":
            raise ValueError("Anthropic classifier refused the request")

        text = next(block.text for block in response.content if block.type == "text")
        return validate_ai_payload(json.loads(text))

    async def _classify_with_ai(self, metadata: dict[str, Any], transcript_text: str | None) -> dict[str, Any]:
        user_content = self._user_content(metadata, transcript_text)
        body = {
            "model": self.settings.ai_model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": build_system_prompt()},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.openai_api_key}"}
        url = f"{self.settings.ai_base_url.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()

        content = payload["choices"][0]["message"]["content"]
        return validate_ai_payload(json.loads(content))


def bucket_for_category(category: str) -> str:
    return "educational" if category in EDUCATIONAL_CATEGORIES else "entertainment"
