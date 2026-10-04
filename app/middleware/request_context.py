from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.context import request_ip


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = request_ip.set(request.client.host if request.client else None)
        try:
            return await call_next(request)
        finally:
            request_ip.reset(token)
