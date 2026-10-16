"""Read-only look at any single day: food, workout, water, fibre, stool, how you felt, weight."""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BowelLog, DailyState, MealLog, WaterLog, WeightLog, WorkoutSession
from . import daystats as ds
from . import digestion as dig
from . import nutrition as nut
from . import progress

MEAL_ORDER = ["breakfast", "lunch", "snack", "dinner"]
MAX_BACK_DAYS = 3650


def day_log(db: Session, day: date) -> dict:
    t = nut.daily_totals(db, day)
    rem = nut.remaining(db, day)
    groups: dict[str, dict] = {}
    for it in t["items"]:
        key = (it.get("meal_type") or "other").lower()
        g = groups.setdefault(key, {"meal_type": key, "items": [], "calories": 0.0, "protein_g": 0.0})
        g["items"].append(it)
        g["calories"] = round(g["calories"] + it["kcal"], 1)
        g["protein_g"] = round(g["protein_g"] + it["protein_g"], 1)
    order = {m: i for i, m in enumerate(MEAL_ORDER)}
    meals = sorted(groups.values(), key=lambda g: order.get(g["meal_type"], 99))
    st = db.get(DailyState, day)
    w = db.get(WeightLog, day)
    water = dig.water_total(db, day)
    today = date.today()
    return {
        "day": day.isoformat(), "is_today": day == today,
        "prev_day": (day - timedelta(days=1)).isoformat(),
        "next_day": (day + timedelta(days=1)).isoformat() if day < today else None,
        "meals": meals,
        "totals": {k: t[k] for k in ("calories", "protein_g", "carbs_g", "fat_g", "fibre_g", "entries")},
        "targets": {"calories": rem["calorie_target"], "protein_g": rem["protein_target_g"],
                    "fibre_g": rem["fibre_target_g"], "training_day_bonus": rem["training_day_bonus"]},
        "any_estimated": t["any_estimated"],
        "workout": progress.today_log(db, day), "trained": nut.trained_today(db, day),
        "water": {"ml": water, "target_ml": nut.get_profile(db).water_target_ml or 3000,
                  "entries": dig.water_entries(db, day)},
        "bowel": dig.bowel_entries(db, day),
        "feeling": {"energy": st.energy, "soreness": st.soreness, "note": st.note} if st else None,
        "weight_kg": w.weight_kg if w else None,
        "stats": ds.get(db, day),
    }


def recent_days(db: Session, limit: int = 14) -> list[dict]:
    """Days that have anything logged, newest first."""
    days = set()
    for model in (MealLog, WaterLog, BowelLog, WorkoutSession, WeightLog):
        days |= {d for (d,) in db.execute(select(model.day).distinct())}
    out = []
    for d in sorted(days, reverse=True)[:max(1, min(limit, 90))]:
        t = nut.daily_totals(db, d)
        out.append({"day": d.isoformat(), "calories": t["calories"], "protein_g": t["protein_g"],
                    "sets": progress.today_log(db, d)["total_sets"], "water_ml": dig.water_total(db, d)})
    return out
