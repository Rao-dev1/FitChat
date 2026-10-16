"""Weekly meal plan and grocery list. The plan reuses the rest-of-day search (code, your own foods, realistic portions)
with a variety penalty so the same dish does not appear day after day; the grocery list adds up what to buy."""
import math
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Food, MealPlan, Recipe
from ..seed.shopping import AISLE_WORDS, DISH_SHOPPING
from . import nutrition as nut
from . import plan as pl
from . import recipes as rc

MAX_DAYS = 7
AISLE_ORDER = ["Vegetables", "Fruit", "Grains and flour", "Pulses and soy", "Dairy and eggs", "Meat and fish",
               "Nuts and spreads", "Pantry", "Other"]
WEEK_TRIPLE_POOL = 9  # keep the 3-item search small: 7 days x 4 meals must stay quick on a laptop


def _aisle(name: str) -> str:
    n = name.lower()
    for aisle, words in AISLE_WORDS:
        if any(w in n for w in words):
            return aisle
    return "Other"


def _friendly(qty: float, unit: str) -> str:
    if unit in ("g", "ml"):
        step = 5 if qty < 100 else 10 if qty < 500 else 50
        q = math.ceil(qty / step) * step
        if q >= 1000:
            return f"{q / 1000:.2f}".rstrip("0").rstrip(".") + (" kg" if unit == "g" else " L")
        return f"{q:g} {unit}"
    return f"{math.ceil(qty - 1e-9):g} {unit}"


def grocery(db: Session, days: list[dict]) -> list[dict]:
    """Add up what to buy. Starter dishes use the built-in table, recipes use their own ingredient lines."""
    need: dict[tuple[str, str, str], float] = {}
    servings: Counter = Counter()
    for d in days:
        for sl in d["slots"]:
            for it in sl["items"]:
                servings[it["food"]] += it["servings"]
    recipes = {r.food.name: r for r in db.scalars(select(Recipe)) if r.food}
    for food, n in servings.items():
        if food in DISH_SHOPPING:
            for item, amt, unit, aisle in DISH_SHOPPING[food]:
                need[(aisle, item, unit)] = need.get((aisle, item, unit), 0) + amt * n
        elif food in recipes:
            r = recipes[food]
            try:
                lines = rc.analyze(db, r.ingredients, r.servings, r.cooked_weight_g).get("lines", [])
            except Exception:  # a damaged recipe must not break the whole list
                lines = []
            for ln in lines:
                name = ln["ingredient"].replace(", dry", "").replace(", raw", "")
                key = (_aisle(name), name, "g")
                need[key] = need.get(key, 0) + ln["grams"] / r.servings * n
            if not lines:
                need[("Other", f"{food} (ingredients)", "servings")] = need.get(("Other", f"{food} (ingredients)", "servings"), 0) + n
        else:
            key = ("Other", f"{food} (ready or your own dish)", "servings")
            need[key] = need.get(key, 0) + n
    out: dict[str, list[dict]] = {}
    for (aisle, item, unit), qty in sorted(need.items(), key=lambda kv: kv[0][1].lower()):
        out.setdefault(aisle, []).append({"name": item, "qty": round(qty, 1), "unit": unit, "text": _friendly(qty, unit)})
    return [{"aisle": a, "items": out[a]} for a in AISLE_ORDER if a in out]


def grocery_text(groups: list[dict]) -> str:
    lines = []
    for g in groups:
        lines.append(g["aisle"].upper())
        lines += [f"- {i['name']}: {i['text']}" for i in g["items"]]
        lines.append("")
    return "\n".join(lines).strip()


def generate(db: Session, start: date | None = None, days: int = MAX_DAYS, reshuffle: bool = False) -> dict:
    start = start or date.today()
    days = max(1, min(int(days), MAX_DAYS))
    p = nut.get_profile(db)
    foods = list(db.scalars(select(Food).order_by(Food.name)))
    if not foods:
        raise ValueError("No foods to plan with yet. Add some foods first.")
    avoid: set[str] = set()
    if reshuffle:
        prev = latest(db)
        if prev:
            c = Counter(i["food"] for d in prev["days"] for s in d["slots"] for i in s["items"])
            avoid = {f for f, n in c.items() if n >= 3}
    total_w = sum(v[1] for v in pl.SLOTS.values())
    history: list[set[str]] = []
    out_days = []
    for k in range(days):
        day = start + timedelta(days=k)
        used = set().union(*history[-2:]) if history else set()
        today_foods: set[str] = set()
        slots = []
        for s, (label, share, _) in pl.SLOTS.items():
            share /= total_w
            target = {"calories": min(pl.MAX_MEAL_KCAL, round(p.calorie_target * share)),
                      "protein_g": round(p.protein_target_g * share, 1), "fibre_g": round((p.fibre_target_g or 30) * share, 1)}
            pool = [f for f in foods if pl._eligible(f, s)]
            best = pl._best(pool, s, target, p.goal, set(), used | today_foods, avoid, max3=WEEK_TRIPLE_POOL) if pool else None
            if not best:
                continue
            today_foods |= {i["food"] for i in best["items"]}
            slots.append({"slot": s, "label": label, "target": target, **best})
        history.append(today_foods)
        tot = {"calories": round(sum(sl["totals"]["calories"] for sl in slots)),
               "protein_g": round(sum(sl["totals"]["protein_g"] for sl in slots), 1),
               "fibre_g": round(sum(sl["totals"]["fibre_g"] for sl in slots), 1)}
        out_days.append({"day": day.isoformat(), "weekday": day.strftime("%a"), "slots": slots, "totals": tot})
    groups = grocery(db, out_days)
    plan = {"start": start.isoformat(), "days": out_days, "grocery": groups, "grocery_text": grocery_text(groups),
            "targets": {"calories": p.calorie_target, "protein_g": p.protein_target_g, "fibre_g": p.fibre_target_g},
            "summary": _summary(out_days, p)}
    db.query(MealPlan).delete()
    db.add(MealPlan(start_day=start, data=plan))
    db.commit()
    return plan


def latest(db: Session) -> dict | None:
    row = db.scalar(select(MealPlan).order_by(MealPlan.id.desc()))
    return row.data if row else None


def _summary(days: list[dict], p) -> str:
    n = len(days)
    cal = sum(d["totals"]["calories"] for d in days) / n
    pro = sum(d["totals"]["protein_g"] for d in days) / n
    distinct = len({i["food"] for d in days for s in d["slots"] for i in s["items"]})
    return (f"{n}-day plan from {days[0]['day']}: about {cal:.0f} kcal and {pro:.0f} g protein a day "
            f"(targets {p.calorie_target:g} kcal, {p.protein_target_g:g} g), using {distinct} different foods. "
            "Portions are by serving; swap anything you like.")
