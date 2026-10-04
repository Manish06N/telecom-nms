"""Count requests per IP. This process memory resets on restart.

A multi-server deployment would put the same counters in Redis.
"""

import time
from collections import defaultdict
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings

_OPEN_PATHS = {"/health", "/metrics", "/openapi.json", "/docs", "/redoc"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled or request.url.path in _OPEN_PATHS:
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        path = request.url.path
        strict = path.endswith("/auth/login") or path.endswith("/auth/token")
        limit = settings.login_rate_limit_per_minute if strict else settings.rate_limit_per_minute
        key = f"{ip}:{path if strict else 'all'}"
        now = time.monotonic()
        with self._lock:
            window = [stamp for stamp in self._hits[key] if now - stamp < 60]
            if len(window) >= limit:
                self._hits[key] = window
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Try again in a minute.", "code": "rate_limited"},
                )
            window.append(now)
            self._hits[key] = window
        return await call_next(request)
