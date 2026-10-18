"""One place that decides what 'today' and 'now' mean.

A hosted server usually runs in UTC, which would flip the day at 5:30 am for someone in India. The browser sends its
time zone with every request (X-TZ header); we remember it for the duration of the request here. With no time zone
(local use, tests) this falls back to the computer's own clock, exactly like before.
"""
from contextvars import ContextVar
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import get_settings

_tz: ContextVar[str | None] = ContextVar("fitchat_tz", default=None)


def set_tz(name: str | None) -> None:
    """Remember the caller's time zone for this request. Unknown names are ignored."""
    if name:
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            name = None
    _tz.set(name or None)


def _zone() -> ZoneInfo | None:
    name = _tz.get() or get_settings().app_tz
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def now() -> datetime:
    z = _zone()
    return datetime.now(z).replace(tzinfo=None) if z else datetime.now()


def today() -> date:
    return now().date()
