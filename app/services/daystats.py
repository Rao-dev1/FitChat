"""Sleep (hours) and steps, typed in by hand once a day."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DayStat

MAX_SLEEP_H, MAX_STEPS = 24.0, 100_000
MAX_WINDOW = 120


class StatError(ValueError):
    """Bad input; shown to the user as is."""


def log_stats(db: Session, day: date | None = None, sleep_h: float | None = None, steps: int | None = None) -> dict:
    day = day or date.today()
    if day > date.today():
        raise StatError("Can't log for a future date.")
    if sleep_h is None and steps is None:
        raise StatError("Give sleep hours, steps, or both.")
    if sleep_h is not None and not (0 < float(sleep_h) <= MAX_SLEEP_H):
        raise StatError(f"Sleep must be more than 0 and at most {MAX_SLEEP_H:g} hours.")
    if steps is not None and not (0 <= int(steps) <= MAX_STEPS):
        raise StatError(f"Steps must be between 0 and {MAX_STEPS:,}.")
    row = db.get(DayStat, day) or DayStat(day=day)
    if sleep_h is not None:
        row.sleep_h = round(float(sleep_h), 2)
    if steps is not None:
        row.steps = int(steps)
    db.add(row)
    db.commit()
    bits = ([f"{row.sleep_h:g} h sleep"] if sleep_h is not None else []) + ([f"{row.steps:,} steps"] if steps is not None else [])
    return {**stat_json(row), "summary": f"Saved {' and '.join(bits)} for {day.isoformat()}."}


def delete_stats(db: Session, day: date) -> bool:
    row = db.get(DayStat, day)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True


def stat_json(r: DayStat | None) -> dict | None:
    return None if r is None else {"day": r.day.isoformat(), "sleep_h": r.sleep_h, "steps": r.steps}


def get(db: Session, day: date) -> dict | None:
    return stat_json(db.get(DayStat, day))


def series(db: Session, days: int = 14, end: date | None = None) -> dict:
    days = max(1, min(int(days), MAX_WINDOW))
    end = end or date.today()
    rows = db.scalars(select(DayStat).where(DayStat.day > end - timedelta(days=days), DayStat.day <= end)
                      .order_by(DayStat.day)).all()
    sl = [r.sleep_h for r in rows if r.sleep_h is not None]
    st = [r.steps for r in rows if r.steps is not None]
    avg_sleep = round(sum(sl) / len(sl), 1) if sl else None
    avg_steps = round(sum(st) / len(st)) if st else None
    parts = []
    if avg_sleep is not None:
        parts.append(f"average sleep {avg_sleep:g} h over {len(sl)} logged nights" + (" (under 7 h hurts recovery and appetite)" if avg_sleep < 7 else ""))
    if avg_steps is not None:
        parts.append(f"average {avg_steps:,} steps over {len(st)} logged days")
    return {"days": [stat_json(r) for r in rows], "avg_sleep_h": avg_sleep, "avg_steps": avg_steps,
            "summary": ("Last %d days: " % days + "; ".join(parts) + ".") if parts else "No sleep or steps logged yet."}
