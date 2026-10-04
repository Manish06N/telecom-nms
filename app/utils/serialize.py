import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum


def jsonable(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


def snapshot(obj, fields: tuple[str, ...]) -> dict:
    return {name: jsonable(getattr(obj, name)) for name in fields}
