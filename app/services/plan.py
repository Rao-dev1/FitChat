"""Rest-of-day meal plan: fills what is left of today's calories, protein and fibre with your own foods and recipes,
split across the meals still to come. Pure code search over the food table; the language model only words it."""
from datetime import date, datetime
from itertools import combinations, product

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Food
from . import digestion as dig
from . import nutrition as nut

SLOTS = {  # slot -> (label, share of the rest of the day, last hour it is still worth planning)
    "breakfast": ("Breakfast", 0.25, 11), "lunch": ("Lunch", 0.33, 16), "snack": ("Snack", 0.12, 19),
    "dinner": ("Dinner", 0.30, 23),
}
# Which starter foods suit which slot, and what role they play on a plate. Anything not listed (your own foods and
# recipes) is placed by its numbers: light foods fit anywhere, heavy ones go to lunch or dinner.
SLOT_FOODS = {
    "breakfast": {"Oats", "Poha", "Upma", "Idli", "Plain dosa", "Sambar", "Brown bread", "Boiled egg", "Omelette", "Milk",
                  "Curd", "Banana", "Apple", "Whey protein", "Peanut butter", "Moong sprouts", "Paneer bhurji", "Peanuts"},
    "lunch": {"Roti", "Steamed rice", "Plain paratha", "Dal", "Rajma curry", "Chole", "Chicken breast", "Chicken curry",
              "Fish curry", "Paneer", "Paneer bhurji", "Soya chunks", "Mixed veg sabzi", "Bhindi", "Sambar", "Curd",
              "Boiled egg", "Omelette", "Moong sprouts", "Boiled chickpeas", "Chaas"},
    "snack": {"Banana", "Apple", "Peanuts", "Almonds", "Peanut butter", "Curd", "Chaas", "Milk", "Whey protein",
              "Boiled chickpeas", "Moong sprouts", "Boiled egg", "Brown bread", "Soya chunks"},
}
SLOT_FOODS["dinner"] = SLOT_FOODS["lunch"] - {"Plain paratha"}
CARBS = {"Roti", "Steamed rice", "Plain paratha", "Aloo paratha", "Poha", "Upma", "Idli", "Plain dosa", "Brown bread",
         "Oats"}
PROTEINS = {"Paneer", "Paneer bhurji", "Boiled egg", "Omelette", "Chicken breast", "Chicken curry", "Fish curry",
            "Soya chunks", "Whey protein"}
PULSES = {"Dal", "Rajma curry", "Chole", "Sambar", "Boiled chickpeas", "Moong sprouts"}
COUNTED = ("piece", "large", "medium", "slice", "egg")  # servings that are whole items: step by 1, not 0.5
MAX_COMBO = 3
MIN_USEFUL_KCAL = 120
MAX_MEAL_KCAL = 900  # a planned meal never exceeds this; the rest is mentioned, not crammed in


def _eligible(f: Food, slot: str) -> bool:
    if f.name in SLOT_FOODS["lunch"] | SLOT_FOODS["snack"] | SLOT_FOODS["breakfast"] | CARBS | PROTEINS | PULSES:
        return f.name in SLOT_FOODS[slot]
    if f.source == "recipe":
        return slot in ("lunch", "dinner") or f.calories <= 300
    return f.calories <= 260 or slot in ("lunch", "dinner")


MAX_SERVINGS = {"Milk": 2, "Chaas": 2, "Apple": 2, "Banana": 2, "Curd": 2, "Whey protein": 1, "Peanut butter": 2,
                "Almonds": 2, "Peanuts": 2, "Oats": 2, "Brown bread": 3}  # sensible caps for things nobody eats three of


def _servings(f: Food, budget: float) -> list[float]:
    step = 1.0 if any(w in (f.serving or "").lower() for w in COUNTED) else 0.5
    top = min(MAX_SERVINGS.get(f.name, 3), 3 if f.calories <= 160 else 2)
    out, n = [], step
    while n <= top + 1e-9:
        if f.calories * n <= max(budget * 1.15, f.calories * step):
            out.append(round(n, 1))
        n += step
    return out or [step]


def _cost(cal, pro, fib, t, goal, role_ok, logged, used, excluded_hit, n_items) -> float:
    cal_t, pro_t, fib_t = max(t["calories"], 100.0), t["protein_g"], t["fibre_g"]
    over_w = 1.4 if goal == "fat_loss" else 1.0
    c = (cal - t["calories"]) / cal_t
    cost = over_w * c if c > 0 else -0.6 * c
    if pro_t > 0:
        d = pro - pro_t
        cost += 1.2 * (-d / max(pro_t, 10.0)) if d < 0 else 0.15 * (d / max(pro_t, 10.0))
    if fib_t > 0 and fib < fib_t:
        cost += 0.35 * (fib_t - fib) / max(fib_t, 3.0)
    cost += 0.03 * (n_items - 1)
    cost += 0 if role_ok else 0.5
    cost += 0.1 * logged + 0.4 * used + 1.5 * excluded_hit
    return cost


def _role_ok(slot: str, names: set[str], items: list[tuple[Food, float]]) -> bool:
    if slot not in ("lunch", "dinner"):
        return True
    base = bool(names & (CARBS | PULSES)) or any(f.source == "recipe" for f, _ in items)
    protein = bool(names & (PROTEINS | PULSES)) or any(f.protein_g * s >= 12 for f, s in items)
    return base and protein and len(items) >= 2 or any(f.source == "recipe" and f.protein_g * s >= 12 for f, s in items)


def _best(pool: list[Food], slot: str, t: dict, goal: str, logged: set[str], used: set[str], exclude: set[str],
          max3: int = 14) -> dict | None:
    pool = [f for f in pool if f.calories > 0]
    best, best_cost = None, 1e9
    for n in range(1, MAX_COMBO + 1):
        if n == 3 and len(pool) > max3:  # keep the search small: the most protein- and fibre-dense foods
            sub = sorted(pool, key=lambda f: -(f.protein_g + f.fibre_g) / max(f.calories, 1))[:max3]
        else:
            sub = pool
        for combo in combinations(sub, n):
            opts = [_servings(f, t["calories"]) for f in combo]
            for servs in product(*opts):
                items = list(zip(combo, servs))
                cal = sum(f.calories * s for f, s in items)
                if cal > t["calories"] * 1.35 + 40:
                    continue
                pro = sum(f.protein_g * s for f, s in items)
                fib = sum((f.fibre_g or 0) * s for f, s in items)
                names = {f.name for f in combo}
                cost = _cost(cal, pro, fib, t, goal, _role_ok(slot, names, items), len(names & logged), len(names & used),
                             len(names & exclude), n)
                if cost < best_cost:
                    best, best_cost = items, cost
    if not best:
        return None
    rows = [{"food": f.name, "servings": s, "serving": f.serving, "kcal": round(f.calories * s),
             "protein_g": round(f.protein_g * s, 1), "fibre_g": round((f.fibre_g or 0) * s, 1)} for f, s in best]
    return {"items": rows, "totals": {"calories": sum(r["kcal"] for r in rows),
                                      "protein_g": round(sum(r["protein_g"] for r in rows), 1),
                                      "fibre_g": round(sum(r["fibre_g"] for r in rows), 1)}}


def plan_rest_of_day(db: Session, hour: int | None = None, slots: list[str] | None = None,
                     exclude: list[str] | None = None, day: date | None = None) -> dict:
    day = day or date.today()
    hour = datetime.now().hour if hour is None else int(hour)
    rem = nut.remaining(db, day)
    gut = dig.status(db, day)
    cal_left, pro_left = rem["calories_remaining"], max(0.0, rem["protein_remaining_g"])
    fib_left = max(0.0, rem["fibre_remaining_g"])
    goal = rem["goal"]
    base = {"day": day.isoformat(), "goal": goal, "hour": hour,
            "remaining": {"calories": cal_left, "protein_g": round(pro_left, 1), "fibre_g": round(fib_left, 1),
                          "water_ml": gut["water_remaining_ml"]}, "slots": [], "notes": []}
    water_note = f"Water: {gut['water_remaining_ml']:g} ml to go today." if gut["water_remaining_ml"] > 0 else None

    if cal_left <= 0:
        base.update(status="over", summary=f"You are {abs(cal_left):g} kcal over today's target. No more food is needed; "
                                           "don't skip meals tomorrow to make up for it. Water and a walk are fine.")
        base["notes"] = [n for n in [water_note] if n]
        return base
    wanted = [s for s in (slots or SLOTS) if s in SLOTS]
    active = [s for s in wanted if slots or hour < SLOTS[s][2]]
    if not active:
        # late in the day: offer a single top-up only if protein is clearly short
        active = ["snack"] if pro_left >= 15 and cal_left >= MIN_USEFUL_KCAL else []
    if cal_left < MIN_USEFUL_KCAL and not slots:
        active = ["snack"] if pro_left >= 15 and cal_left >= 60 else []
    if not active:
        base.update(status="done", summary=f"You have {cal_left:g} kcal and {pro_left:g} g protein left: basically done for today.")
        base["notes"] = [n for n in [water_note] if n]
        return base

    foods = list(db.scalars(select(Food).order_by(Food.name)))
    if not foods:
        base.update(status="empty", summary="No foods to plan with yet. Add some foods first.")
        return base
    logged = {i["food"].split(" (")[0] for i in nut.daily_totals(db, day)["items"]}
    exclude_set, used = set(exclude or []), set()
    total_w = sum(SLOTS[s][1] for s in active)
    projected = {"calories": rem["calories_eaten"], "protein_g": rem["protein_eaten_g"], "fibre_g": rem["fibre_eaten_g"]}
    for s in active:
        share = SLOTS[s][1] / total_w
        target = {"calories": min(MAX_MEAL_KCAL, round(cal_left * share)), "protein_g": round(pro_left * share, 1), "fibre_g": round(fib_left * share, 1)}
        pool = [f for f in foods if _eligible(f, s)]
        best = _best(pool, s, target, goal, logged, used, exclude_set) if pool else None
        if not best:
            continue
        used |= {r["food"] for r in best["items"]}
        for k in projected:
            projected[k] += best["totals"][k]
        base["slots"].append({"slot": s, "label": SLOTS[s][0], "target": target, **best})
    if not base["slots"]:
        base.update(status="empty", summary="Couldn't build a plan from your current foods.")
        return base
    base["status"] = "plan"
    base["projected_day"] = {"calories": round(projected["calories"]), "protein_g": round(projected["protein_g"], 1),
                             "fibre_g": round(projected["fibre_g"], 1), "calorie_target": rem["calorie_target"],
                             "protein_target_g": rem["protein_target_g"], "fibre_target_g": rem["fibre_target_g"]}
    notes = []
    short = rem["protein_target_g"] - projected["protein_g"]
    if short > 10:
        notes.append(f"Even with this plan you would finish about {short:.0f} g short on protein. Add whey, eggs, curd or paneer to one meal.")
    if projected["fibre_g"] < 0.8 * rem["fibre_target_g"]:
        notes.append(f"Fibre would end around {projected['fibre_g']:.0f} of {rem['fibre_target_g']:g} g. Add dal, rajma, vegetables or fruit.")
    if rem["training_day_bonus"]:
        notes.append(f"Includes the +{rem['training_day_bonus']} kcal training-day allowance.")
    unplanned = cal_left - (projected["calories"] - rem["calories_eaten"])
    if unplanned > 250:
        notes.append(f"About {unplanned:.0f} kcal are still unplanned. Add a bigger portion or another snack if you are hungry.")
    if water_note:
        notes.append(water_note)
    base["notes"] = notes
    base["summary"] = ("Plan for the rest of today: " + "; ".join(
        f"{sl['label']}: " + ", ".join(f"{i['servings']:g} x {i['food']}" for i in sl["items"]) +
        f" ({sl['totals']['calories']:g} kcal, {sl['totals']['protein_g']:g} g protein)" for sl in base["slots"]) +
        f". Day would end at about {base['projected_day']['calories']:g} kcal and {base['projected_day']['protein_g']:g} g protein.")
    return base
