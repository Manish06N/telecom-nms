from datetime import datetime, timezone


def utcnow() -> datetime:
    """UTC wall time without tzinfo, so SQLite and PostgreSQL compare the same way.

    JWT expiry still uses an aware UTC datetime. These two clocks are both UTC;
    only the Python object shape differs.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
