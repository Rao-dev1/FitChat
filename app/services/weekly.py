"""Weekly view and bodyweight log. Everything here is computed in code, never by the language model."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..tenancy import key_get

from ..models import DayStat, MealLog, WeightLog, WorkoutSession, WorkoutSet
from . import targets as tg
from . import daystats as ds
from . import nutrition as nut
from .. import clock

MIN_WEIGHT_KG, MAX_WEIGHT_KG = 25.0, 400.0
PROTEIN_HIT = 0.9  # a day "hits" protein at 90% of target or more
MAX_WINDOW_DAYS = 90


def log_weight(db: Session, weight_kg: float, day: date | None = None) -> dict:
    day = day or clock.today()
    if not (MIN_WEIGHT_KG <= weight_kg <= MAX_WEIGHT_KG):
        raise ValueError(f"Weight must be between {MIN_WEIGHT_KG:g} and {MAX_WEIGHT_KG:g} kg.")
    if day > clock.today():
        raise ValueError("Can't log a weight for a future date.")
    weight_kg = round(weight_kg, 1)
    row = key_get(db, WeightLog, day=day)
    if row:
        row.weight_kg = weight_kg
    else:
        db.add(WeightLog(day=day, weight_kg=weight_kg))
    db.flush()
    _sync_profile(db)
    db.commit()
    return {"day": day.isoformat(), "weight_kg": weight_kg, "summary": f"Logged {weight_kg:g} kg for {day.isoformat()}."}


def delete_weight(db: Session, day: date) -> bool:
    row = key_get(db, WeightLog, day=day)
    if not row:
        return False
    db.delete(row)
    db.flush()
    _sync_profile(db)
    db.commit()
    return True


def _sync_profile(db: Session) -> None:
    """Profile weight follows the most recent reading, so older features keep working."""
    last = db.scalar(select(WeightLog).order_by(WeightLog.day.desc()))
    if last:
        nut.get_profile(db).weight_kg = last.weight_kg
        from . import profile as profile_svc  # local import: profile imports this package's siblings
        profile_svc.refresh_if_auto(db)


def weight_series(db: Session, days: int = 60, end: date | None = None) -> list[dict]:
    end = end or clock.today()
    rows = db.scalars(select(WeightLog).where(WeightLog.day > end - timedelta(days=days), WeightLog.day <= end)
                      .order_by(WeightLog.day)).all()
    return [{"day": r.day.isoformat(), "weight_kg": r.weight_kg} for r in rows]


def _weight_block(series: list[dict]) -> dict:
    out = {"readings": len(series), "latest": series[-1] if series else None, "change_kg": None, "span_days": 0}
    if len(series) >= 2:
        first, last = series[0], series[-1]
        span = (date.fromisoformat(last["day"]) - date.fromisoformat(first["day"])).days
        out["span_days"] = span
        out["change_kg"] = round(last["weight_kg"] - first["weight_kg"], 1)
        if span >= 5:
            out["per_week_kg"] = round(out["change_kg"] * 7 / span, 2)
    return out


def weekly_summary(db: Session, end: date | None = None, days: int = 7) -> dict:
    days = max(1, min(int(days), MAX_WINDOW_DAYS))
    end = end or clock.today()
    start = end - timedelta(days=days - 1)
    profile = nut.get_profile(db)

    eaten = {}
    for m in db.scalars(select(MealLog).where(MealLog.day >= start, MealLog.day <= end)):
        d = eaten.setdefault(m.day, {"calories": 0.0, "protein_g": 0.0})
        d["calories"] += m.calories
        d["protein_g"] += m.protein_g
    sets = {}
    for s_day, reps, w in db.execute(select(WorkoutSession.day, WorkoutSet.reps, WorkoutSet.weight_kg).join(WorkoutSet)
                                     .where(WorkoutSession.day >= start, WorkoutSession.day <= end)):
        d = sets.setdefault(s_day, {"sets": 0, "volume": 0.0})
        d["sets"] += 1
        d["volume"] += reps * w

    step_rows = dict(db.execute(select(DayStat.day, DayStat.steps).where(DayStat.day >= start, DayStat.day <= end)).all())
    rows = []
    for i in range(days):
        day = start + timedelta(days=i)
        e, w = eaten.get(day), sets.get(day, {"sets": 0, "volume": 0.0})
        trained = w["sets"] >= nut.MIN_SETS_FOR_BONUS
        target = (profile.calorie_target + tg.training_bonus(w["sets"], profile.weight_kg, nut.MIN_SETS_FOR_BONUS)
                  + tg.steps_bonus(step_rows.get(day), profile.weight_kg))
        rows.append({
            "day": day.isoformat(), "weekday": day.strftime("%a"), "logged": e is not None,
            "calories": round(e["calories"]) if e else 0, "protein_g": round(e["protein_g"], 1) if e else 0,
            "calorie_target": target, "protein_target_g": profile.protein_target_g,
            "sets": w["sets"], "volume_kg": round(w["volume"]), "trained": trained,
            "protein_hit": bool(e and e["protein_g"] >= PROTEIN_HIT * profile.protein_target_g),
            "over_calories": bool(e and e["calories"] > target),
        })

    logged = [r for r in rows if r["logged"]]
    n = len(logged)
    avg_cal = round(sum(r["calories"] for r in logged) / n) if n else None
    avg_pro = round(sum(r["protein_g"] for r in logged) / n, 1) if n else None
    session_days = [r for r in rows if r["sets"] > 0]
    totals = {
        "days_in_window": days, "days_logged": n, "avg_calories": avg_cal, "avg_protein_g": avg_pro,
        "calorie_target": profile.calorie_target, "protein_target_g": profile.protein_target_g,
        "protein_hit_days": sum(r["protein_hit"] for r in logged),
        "over_calorie_days": sum(r["over_calories"] for r in logged),
        "training_days": sum(r["trained"] for r in rows), "workout_days": len(session_days),
        "total_sets": sum(r["sets"] for r in rows), "total_volume_kg": sum(r["volume_kg"] for r in rows),
    }
    weight = _weight_block(weight_series(db, days=max(days, 28), end=end))
    return {"start": start.isoformat(), "end": end.isoformat(), "goal": profile.goal, "days": rows, "totals": totals,
            "weight": weight, "lines": _lines(totals, weight, profile.goal), "summary": _summary(totals, weight),
            "sleep_steps": ds.series(db, days, end)}


def _lines(t: dict, w: dict, goal: str) -> list[str]:
    out = []
    if t["days_logged"] == 0:
        return ["No food logged in this period yet."]
    if t["days_logged"] < t["days_in_window"]:
        out.append(f"Food logged on {t['days_logged']} of {t['days_in_window']} days. Averages count only those days.")
    out.append(f"Protein target reached on {t['protein_hit_days']} of {t['days_logged']} logged days.")
    if t["avg_calories"] is not None:
        diff = t["avg_calories"] - t["calorie_target"]
        word = "above" if diff > 0 else "below"
        out.append(f"Average {t['avg_calories']:g} kcal a day, {abs(diff):g} {word} your {t['calorie_target']:g} kcal target.")
    out.append(f"Trained on {t['training_days']} days ({t['total_sets']} sets in total)." if t["total_sets"]
               else "No sets logged in this period.")
    if w.get("per_week_kg"):
        out.append(f"Bodyweight is changing by about {w['per_week_kg']:+g} kg a week. Daily readings swing by 0.5 to 1 kg, so judge the trend over a few weeks.")
    return out


def _summary(t: dict, w: dict) -> str:
    if t["days_logged"] == 0:
        return "No food logged in this period."
    s = (f"Last {t['days_in_window']} days: food logged on {t['days_logged']}, average {t['avg_calories']:g} kcal "
         f"(target {t['calorie_target']:g}) and {t['avg_protein_g']:g} g protein (target {t['protein_target_g']:g}). "
         f"Protein target reached on {t['protein_hit_days']} days. Trained on {t['training_days']} days, {t['total_sets']} sets.")
    if w["latest"]:
        s += f" Latest weight {w['latest']['weight_kg']:g} kg"
        s += f", {w['change_kg']:+g} kg over {w['span_days']} days." if w["change_kg"] is not None else "."
    return s
