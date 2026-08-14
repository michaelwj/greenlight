from redis import Redis
from rq import Queue, Retry
from rq.job import Job

from app.core.config import get_settings


def get_default_queue() -> Queue:
    settings = get_settings()
    redis_conn = Redis.from_url(settings.redis_url)
    return Queue("default", connection=redis_conn)


def retry_delays(settings=None) -> list[int]:
    settings = settings or get_settings()
    delays = [int(part) for part in settings.download_retry_delays.split(",") if part.strip()]
    return delays or [30]


def enqueue_download(request_id: str) -> Job:
    """Enqueue a download with transient-failure retries on a progressive delay.

    The job re-raises transient errors (429/403/network) so RQ reschedules it;
    permanent failures (invalid URL, unavailable video) are marked failed
    immediately by the job and never retried.
    """
    from app.workers.jobs import run_download_job

    settings = get_settings()
    retry = Retry(max=settings.download_max_retries, interval=retry_delays(settings))
    # Generous timeout: a long video download + the pre-download gap sleep
    # must not trip RQ's 180s default.
    return get_default_queue().enqueue(
        run_download_job, request_id, retry=retry, job_timeout=1800
    )
