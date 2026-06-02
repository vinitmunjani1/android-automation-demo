from __future__ import annotations

import random
import time
from datetime import datetime, timedelta


def _parse_hhmm(value: str, base: datetime) -> datetime:
    hour, minute = map(int, value.split(":"))
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def random_time_in_window(start: str, end: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    start_dt = _parse_hhmm(start, now)
    end_dt = _parse_hhmm(end, now)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    if now > end_dt:
        start_dt += timedelta(days=1)
        end_dt += timedelta(days=1)
    earliest = max(now, start_dt)
    seconds = int((end_dt - earliest).total_seconds())
    if seconds <= 0:
        return earliest
    return earliest + timedelta(seconds=random.randint(0, seconds))


def sleep_until(target: datetime) -> None:
    while True:
        remaining = (target - datetime.now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))
