"""Smart reminders: a few rule-based nudges for right now. In-app only: a phone can't be pushed to without HTTPS hosting.
Each nudge is {kind, text, action}. Capped so the screen never feels like a to-do list."""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WeightLog
from . import body as body_svc
from . import daystats as ds
from . import digestion as dig
from . import nutrition as nut
from . import routines as rt
from .. import clock

MAX_NUDGES = 4
KINDS = ["food", "water", "protein", "gym", "weight", "measure", "sleep", "steps", "gut"]


def compute(db: Session, now: datetime | None = None) -> list[dict]:
    now = now or clock.now()
    day, h = now.date(), now.hour + now.minute / 60
    out: list[dict] = []
    rem = nut.remaining(db, day)
    totals = nut.daily_totals(db, day)
    gut = dig.status(db, day)

    if gut["alert"] == "see_doctor":
        out.append({"kind": "gut", "priority": 0, "text": "You marked warning signs. Please see a doctor.", "action": {"type": "open", "target": "gut"}})
    elif (gut["days_since_bowel"] or 0) >= 3:
        out.append({"kind": "gut", "priority": 3, "text": f"No bowel movement logged for {gut['days_since_bowel']} days. Water, fibre and a walk help.",
                    "action": {"type": "open", "target": "gut"}})
    if h >= 11 and not totals["items"]:
        out.append({"kind": "food", "priority": 1, "text": "Nothing logged yet today. Log what you ate, or plan your next meal.",
                    "action": {"type": "open", "target": "food"}})
    target_w = gut["water_target_ml"]
    expected = max(0.0, min(1.0, (h - 8) / 14)) * target_w
    if h >= 12 and gut["water_ml"] < expected - 500:
        out.append({"kind": "water", "priority": 2, "text": f"Water is behind: {gut['water_ml']:g} of {target_w:g} ml. Have a glass now.",
                    "action": {"type": "water", "ml": 250}})
    if h >= 18 and rem["protein_remaining_g"] >= 30 and rem["calories_remaining"] > 150:
        out.append({"kind": "protein", "priority": 2, "text": f"Protein is {rem['protein_remaining_g']:.0f} g short. Plan the rest of the day.",
                    "action": {"type": "open", "target": "plan"}})
    sg = rt.suggest(db)
    if sg and sg.get("routine_id") and h >= 16 and not nut.trained_today(db, day):
        out.append({"kind": "gym", "priority": 2, "text": f"Gym time? {sg['name']} is up next.", "action": {"type": "open", "target": "gym"}})
    last_w = db.scalar(select(WeightLog).order_by(WeightLog.day.desc()))
    if h >= 6 and (last_w is None or (day - last_w.day).days >= 7):
        out.append({"kind": "weight", "priority": 4, "text": "Time for a weigh-in. Once a week, same time of day.", "action": {"type": "open", "target": "weight"}})
    dm = body_svc.overview(db)["days_since_measure"]
    if dm is None or dm >= 14:
        out.append({"kind": "measure", "priority": 5, "text": "Time for tape measurements and a progress photo.", "action": {"type": "open", "target": "body"}})
    st = ds.get(db, day) or {}
    if h < 14 and st.get("sleep_h") is None:
        out.append({"kind": "sleep", "priority": 4, "text": "How long did you sleep last night?", "action": {"type": "open", "target": "sleep"}})
    if h >= 20 and st.get("steps") is None:
        out.append({"kind": "steps", "priority": 5, "text": "Log today's steps before you sleep.", "action": {"type": "open", "target": "sleep"}})
    out.sort(key=lambda n: n["priority"])
    return out[:MAX_NUDGES]
