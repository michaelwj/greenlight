from app.workers.jobs import _is_permanent_failure
from app.workers.queue import retry_delays


class _Settings:
    download_retry_delays = "30,60,90"


def test_permanent_failures_are_not_retried() -> None:
    assert _is_permanent_failure(RuntimeError("ERROR: [generic] 'pasted text' is not a valid URL"))
    assert _is_permanent_failure(RuntimeError("ERROR: [youtube] abc: Video unavailable. This video is restricted."))
    assert _is_permanent_failure(RuntimeError("ERROR: Private video. Sign in if you've been granted access"))


def test_transient_failures_are_retried() -> None:
    assert not _is_permanent_failure(RuntimeError("ERROR: Unable to download video subtitles for 'en': HTTP Error 429: Too Many Requests"))
    assert not _is_permanent_failure(RuntimeError("ERROR: unable to download video data: HTTP Error 403: Forbidden"))
    assert not _is_permanent_failure(RuntimeError("ERROR: Connection reset by peer"))


def test_retry_delays_parse_progressive_schedule() -> None:
    assert retry_delays(_Settings()) == [30, 60, 90]

    class Empty:
        download_retry_delays = ""

    assert retry_delays(Empty()) == [30]


def test_available_file_missing_detection(tmp_path) -> None:
    from app.api.youtube_requests import available_file_missing
    from app.models.entities import YoutubeRequest

    real = tmp_path / "video.mp4"
    real.write_bytes(b"x")

    on_disk = YoutubeRequest(status="available", local_file_path=str(real))
    deleted = YoutubeRequest(status="available", local_file_path=str(tmp_path / "gone.mp4"))
    no_path = YoutubeRequest(status="available", local_file_path=None)
    not_available = YoutubeRequest(status="failed", local_file_path=None)

    assert not available_file_missing(on_disk)
    assert available_file_missing(deleted)
    assert available_file_missing(no_path)
    assert not available_file_missing(not_available)
