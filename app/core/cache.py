import json

from app.core.config import settings

_client = None


def _redis():
    global _client
    if not settings.redis_url:
        return None
    if _client is None:
        import redis

        _client = redis.from_url(settings.redis_url, socket_connect_timeout=0.3, socket_timeout=0.3)
    return _client


def cache_get(key: str):
    client = _redis()
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    return json.loads(raw)


def cache_set(key: str, value, ttl_seconds: int) -> None:
    client = _redis()
    if client is None:
        return
    try:
        client.setex(key, ttl_seconds, json.dumps(value, default=str))
    except Exception:
        return


def cache_delete(key: str) -> None:
    client = _redis()
    if client is None:
        return
    try:
        client.delete(key)
    except Exception:
        return
