"""Winter Arc dashboard: day count, honest streaks, and a clearly labelled weight projection. All code, no model."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import MealLog, WaterLog, WeightLog, WorkoutSession, WorkoutSet
from . import nutrition as nut
from .weekly import PROTEIN_HIT

ARC_START, ARC_END = date(2026, 10, 1), date(2026, 12, 31)
WATER_HIT = 0.9


def _days(db: Session, start: date, end: date) -> dict[date, dict]:
    p = nut.get_profile(db)
    out: dict[date, dict] = defaultdict(lambda: {"cal": 0.0, "protein": 0.0, "meals": 0, "water": 0.0, "sets": 0})
    for d, cal, pro, n in db.execute(select(MealLog.day, func.sum(MealLog.calories), func.sum(MealLog.protein_g), func.count())
                                     .where(MealLog.day >= start, MealLog.day <= end).group_by(MealLog.day)):
        out[d].update(cal=cal or 0, protein=pro or 0, meals=n)
    for d, ml in db.execute(select(WaterLog.day, func.sum(WaterLog.ml)).where(WaterLog.day >= start, WaterLog.day <= end)
                            .group_by(WaterLog.day)):
        out[d]["water"] = ml or 0
    for d, n in db.execute(select(WorkoutSession.day, func.count(WorkoutSet.id)).join(WorkoutSet)
                           .where(WorkoutSession.day >= start, WorkoutSession.day <= end).group_by(WorkoutSession.day)):
        out[d]["sets"] = n
    for v in out.values():
        v["logged"] = v["meals"] > 0
        v["protein_hit"] = v["logged"] and v["protein"] >= PROTEIN_HIT * p.protein_target_g
        v["water_hit"] = v["water"] >= WATER_HIT * (p.water_target_ml or 3000)
        v["trained"] = v["sets"] >= nut.MIN_SETS_FOR_BONUS
    return out


def _streak(flags: dict[date, bool], today: date) -> int:
    """Consecutive days ending today; today not being done yet doesn't break a streak that ran up to yesterday."""
    d = today if flags.get(today) else today - timedelta(days=1)
    n = 0
    while flags.get(d):
        n += 1
        d -= timedelta(days=1)
    return n


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _weight_block(db: Session, start: date, end: date, today: date) -> dict:
    rows = db.scalars(select(WeightLog).where(WeightLog.day <= today).order_by(WeightLog.day)).all()
    if not rows:
        return {"readings": 0}
    in_arc = [r for r in rows if r.day >= start]
    first = in_arc[0] if in_arc else rows[-1]
    last = rows[-1]
    out = {"readings": len(rows), "start_kg": first.weight_kg, "start_day": first.day.isoformat(), "latest_kg": last.weight_kg,
           "latest_day": last.day.isoformat(), "change_kg": round(last.weight_kg - first.weight_kg, 1) if first is not last else None}
    recent = [r for r in rows if r.day > today - timedelta(days=21)]
    if len(recent) >= 3 and (recent[-1].day - recent[0].day).days >= 7:
        span = (recent[-1].day - recent[0].day).days
        rate = (recent[-1].weight_kg - recent[0].weight_kg) * 7 / span
        out["per_week_kg"] = round(rate, 2)
        left = (end - today).days
        if left > 0:
            out["projected_end_kg"] = round(last.weight_kg + rate * left / 7, 1)
    return out


def status(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    p = nut.get_profile(db)
    total = (ARC_END - ARC_START).days + 1
    phase = "before" if today < ARC_START else "finished" if today > ARC_END else "active"
    day_no = 0 if phase == "before" else total if phase == "finished" else (today - ARC_START).days + 1
    upto = min(today, ARC_END)
    per = _days(db, ARC_START, upto) if phase != "before" else {}
    dots = []
    for i in range(total):
        d = ARC_START + timedelta(days=i)
        x = per.get(d)
        state = "future" if d > today else "full" if x and x["logged"] and x["protein_hit"] else "logged" if x and x["logged"] else "missed"
        dots.append({"day": d.isoformat(), "state": state, "trained": bool(x and x["trained"]), "today": d == today})
    flags = lambda key: {d: bool(v[key]) for d, v in per.items()}  # noqa: E731
    protein_streak = _streak(flags("protein_hit"), upto)
    water_streak = _streak(flags("water_hit"), upto)
    log_streak = _streak(flags("logged"), upto)
    goal = max(1, int(p.gym_days_goal or 4))
    ws = _week_start(upto)
    week_trained = sum(1 for d, v in per.items() if d >= ws and v["trained"])
    weeks, w = 0, ws - timedelta(days=7)
    while w >= _week_start(ARC_START) and sum(1 for d, v in per.items() if w <= d < w + timedelta(days=7) and v["trained"]) >= goal:
        weeks += 1
        w -= timedelta(days=7)
    if week_trained >= goal:
        weeks += 1
    full = sum(1 for d in dots if d["state"] == "full")
    weight = _weight_block(db, ARC_START, ARC_END, upto) if phase != "before" else {"readings": 0}
    out = {"phase": phase, "start": ARC_START.isoformat(), "end": ARC_END.isoformat(), "total_days": total, "day_number": day_no,
           "days_left": max(0, (ARC_END - today).days) if phase != "finished" else 0, "pct": round(100 * day_no / total),
           "streaks": {"protein_days": protein_streak, "water_days": water_streak, "logging_days": log_streak, "gym_weeks": weeks},
           "gym_week": {"trained": week_trained, "goal": goal}, "full_days": full, "days_logged": sum(1 for d in dots if d["state"] in ("full", "logged")),
           "weight": weight, "dots": dots}
    out["summary"] = _summary(out)
    return out


def _summary(a: dict) -> str:
    if a["phase"] == "before":
        return f"The Winter Arc starts on {a['start']}."
    s = (f"Winter Arc day {a['day_number']} of {a['total_days']} ({a['days_left']} left). Protein target hit {a['streaks']['protein_days']} "
         f"days in a row, water {a['streaks']['water_days']}, food logged {a['streaks']['logging_days']}. This week: "
         f"{a['gym_week']['trained']} of {a['gym_week']['goal']} gym days. {a['full_days']} days fully on track so far.")
    w = a["weight"]
    if w.get("change_kg") is not None:
        s += f" Weight {w['start_kg']:g} to {w['latest_kg']:g} kg ({w['change_kg']:+g})."
    if w.get("projected_end_kg") is not None:
        s += f" At the last three weeks' pace (about {w['per_week_kg']:+g} kg a week) you would be near {w['projected_end_kg']:g} kg on {a['end']}. This is an estimate, not a promise."
    return s
