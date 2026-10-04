"""Merge overlapping outage windows so downtime is not counted twice."""

from datetime import datetime


def downtime_minutes(
    windows: list[tuple[datetime, datetime]],
    range_start: datetime,
    range_end: datetime,
) -> float:
    clipped: list[tuple[datetime, datetime]] = []
    for start, end in windows:
        start = max(start, range_start)
        end = min(end, range_end)
        if end > start:
            clipped.append((start, end))
    clipped.sort()
    merged: list[list[datetime]] = []
    for start, end in clipped:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    seconds = sum((end - start).total_seconds() for start, end in merged)
    return seconds / 60


def uptime_percent(downtime: float, range_start: datetime, range_end: datetime) -> float:
    total = (range_end - range_start).total_seconds() / 60
    if total <= 0:
        return 100.0
    ratio = max(0.0, 1 - (downtime / total))
    return round(ratio * 100, 2)
