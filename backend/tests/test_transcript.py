import json

from app.youtube.transcript import parse_json3, parse_srv1, parse_vtt, select_caption_track


def test_parse_json3_joins_segments() -> None:
    payload = json.dumps(
        {
            "events": [
                {"segs": [{"utf8": "Hello"}, {"utf8": " world"}]},
                {"segs": [{"utf8": "\n"}]},
                {"segs": [{"utf8": "second line"}]},
            ]
        }
    )
    assert parse_json3(payload) == "Hello world second line"


def test_parse_vtt_strips_cues_and_dedupes() -> None:
    payload = "\n".join(
        [
            "WEBVTT",
            "Kind: captions",
            "",
            "00:00:00.000 --> 00:00:02.000",
            "Hello <c>everyone</c>",
            "",
            "00:00:02.000 --> 00:00:04.000",
            "Hello everyone",
            "welcome to class",
        ]
    )
    assert parse_vtt(payload) == "Hello everyone welcome to class"


def test_parse_srv1_unescapes_entities() -> None:
    payload = '<transcript><text start="0" dur="2">Let&amp;#39;s learn</text><text start="2">math</text></transcript>'
    text = parse_srv1(payload)
    assert "learn" in text
    assert "math" in text


def test_select_caption_track_prefers_manual_english_json3() -> None:
    metadata = {
        "subtitles": {
            "en": [
                {"ext": "vtt", "url": "https://example.test/manual.vtt"},
                {"ext": "json3", "url": "https://example.test/manual.json3"},
            ]
        },
        "automatic_captions": {
            "en": [{"ext": "json3", "url": "https://example.test/auto.json3"}]
        },
    }
    track = select_caption_track(metadata)
    assert track is not None
    assert track["source"] == "subtitles"
    assert track["ext"] == "json3"
    assert track["url"] == "https://example.test/manual.json3"


def test_select_caption_track_falls_back_to_auto_captions() -> None:
    metadata = {
        "subtitles": {},
        "automatic_captions": {"en-US": [{"ext": "vtt", "url": "https://example.test/auto.vtt"}]},
    }
    track = select_caption_track(metadata)
    assert track is not None
    assert track["source"] == "automatic_captions"


def test_select_caption_track_returns_none_without_captions() -> None:
    assert select_caption_track({"subtitles": {}, "automatic_captions": {}}) is None
