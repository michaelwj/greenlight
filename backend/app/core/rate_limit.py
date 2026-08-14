from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_BUCKET: dict[str, list[float]] = defaultdict(list)
WINDOW_SECONDS = 60
MAX_REQUESTS = 20


async def enforce_kid_rate_limit(request: Request) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    key = f"{client_ip}:{request.url.path}"

    now = time.time()
    window_start = now - WINDOW_SECONDS
    _BUCKET[key] = [value for value in _BUCKET[key] if value >= window_start]

    if len(_BUCKET[key]) >= MAX_REQUESTS:
        raise HTTPException(status_code=429, detail="Too many requests")

    _BUCKET[key].append(now)
