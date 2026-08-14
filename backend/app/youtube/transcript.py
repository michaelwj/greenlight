from __future__ import annotations

import html
import json
import re
from typing import Any

import httpx

from app.core.config import get_settings

_PREFERRED_LANGS = ("en", "en-US", "en-GB", "en-orig")
_PREFERRED_FORMATS = ("json3", "vtt", "srv1")


def select_caption_track(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the best caption track from yt-dlp metadata.

    Manual subtitles win over automatic captions; English variants win over other
    languages; json3 wins over vtt/srv1.
    """
    for source_key in ("subtitles", "automatic_captions"):
        tracks = metadata.get(source_key) or {}
        if not isinstance(tracks, dict):
            continue

        lang_keys = [lang for lang in _PREFERRED_LANGS if lang in tracks]
        lang_keys += [lang for lang in tracks if lang.startswith("en") and lang not in lang_keys]
        for lang in lang_keys:
            entries = tracks.get(lang) or []
            for fmt in _PREFERRED_FORMATS:
                for entry in entries:
                    if entry.get("ext") == fmt and entry.get("url"):
                        return {"lang": lang, "ext": fmt, "url": entry["url"], "source": source_key}
    return None


def parse_json3(payload: str) -> str:
    data = json.loads(payload)
    parts: list[str] = []
    for event in data.get("events") or []:
        for seg in event.get("segs") or []:
            text = seg.get("utf8") or ""
            if text.strip():
                parts.append(text)
    return _normalize(" ".join(parts))


def parse_vtt(payload: str) -> str:
    lines: list[str] = []
    for raw_line in payload.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("WEBVTT", "NOTE", "STYLE", "Kind:", "Language:")):
            continue
        if "-->" in line or re.fullmatch(r"\d+", line):
            continue
        line = re.sub(r"<[^>]+>", "", line)
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return _normalize(" ".join(lines))


def parse_srv1(payload: str) -> str:
    texts = re.findall(r"<text[^>]*>(.*?)</text>", payload, flags=re.S)
    return _normalize(" ".join(html.unescape(t) for t in texts))


def _normalize(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


async def fetch_transcript(metadata: dict[str, Any]) -> str | None:
    """Fetch and parse the full transcript for a video, or None if unavailable."""
    track = select_caption_track(metadata)
    if not track:
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(track["url"])
        response.raise_for_status()
        payload = response.text

    if track["ext"] == "json3":
        text = parse_json3(payload)
    elif track["ext"] == "vtt":
        text = parse_vtt(payload)
    else:
        text = parse_srv1(payload)

    if not text:
        return None

    max_chars = get_settings().transcript_max_chars
    return text[:max_chars]
