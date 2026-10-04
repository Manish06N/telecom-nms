from contextvars import ContextVar

request_ip: ContextVar[str | None] = ContextVar("request_ip", default=None)
