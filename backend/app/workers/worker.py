import os

from redis import Redis
from rq import Worker

from app.core.logging import configure_logging


def run_worker() -> None:
    configure_logging()
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    redis_conn = Redis.from_url(redis_url)

    worker = Worker(["default"], connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    run_worker()
