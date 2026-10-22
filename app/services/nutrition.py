import re
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import DayStat, Food, Ingredient, MealLog, Profile, WorkoutSession, WorkoutSet
from . import targets as tg
from . import ingredients as ing_svc
from .textmatch import match_named
from .. import clock

# Extra calories on a day with a workout / steps: see targets.training_bonus and targets.steps_bonus.
TRAINING_DAY_CALORIE_BONUS = tg.TRAIN_FLOOR  # smallest bonus a counted workout earns
MIN_SETS_FOR_BONUS = 6


def get_profile(db: Session) -> Profile:
    p = db.scalar(select(Profile))
    if p is None:
        p = Profile()
        db.add(p)
        db.commit()
    return p


_GRAMS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*g\b")
MAX_ITEM_KCAL, MAX_ITEM_PROTEIN_G = 5000, 300  # sanity limits for a single logged item


def serving_grams(food: Food) -> float | None:
    """Weight of one table serving, read from text like '1 katori (150 g)'. None if the table gives no weight."""
    m = _GRAMS_RE.search(food.serving or "")
    return float(m.group(1)) if m else None


def match_food(db: Session, name: str) -> tuple[Food | None, str]:
    """Returns (food, quality): 'exact' (name or alias), 'loose' (one clear best whole-word match) or 'none'."""
    return match_named(db.scalars(select(Food)).all(), name)


def find_food(db: Session, name: str) -> Food | None:
    return match_food(db, name)[0]


def _check_plausible(vals: dict) -> None:
    if any(v < 0 for v in vals.values()):
        raise ValueError("nutrition values cannot be negative")
    if vals["calories"] > MAX_ITEM_KCAL or vals["protein_g"] > MAX_ITEM_PROTEIN_G:
        raise ValueError(f"implausible values for one item ({vals['calories']:g} kcal, {vals['protein_g']:g} g "
                         "protein). Check units: totals should be for the whole amount eaten.")


def _entry(db, day, meal_type, label, quantity, per, estimated, scale=1.0) -> MealLog:
    e = MealLog(
        day=day, meal_type=meal_type, food_name=label[:120], quantity=quantity, estimated=estimated,
        calories=round(per["calories"] * scale, 1), protein_g=round(per["protein_g"] * scale, 1),
        carbs_g=round(per.get("carbs_g", 0) * scale, 1), fat_g=round(per.get("fat_g", 0) * scale, 1),
        fibre_g=round(per.get("fibre_g", 0) * scale, 1),
    )
    db.add(e)
    db.commit()
    return e


def _vals(d: dict) -> dict:
    return {k: float(d.get(k, 0) or 0) for k in ("calories", "protein_g", "carbs_g", "fat_g", "fibre_g")}


def log_item(db: Session, name: str, quantity: float = 1, meal_type: str | None = None,
             day: date | None = None, estimate: dict | None = None, grams: float | None = None,
             totals: dict | None = None, ingredients: list[dict] | None = None) -> dict:
    """Log one food. Ways, in priority order:
      0. `ingredients`: a dish given as ingredient lines [{name, grams|quantity}] for the portion eaten. The app sums
         them from the built-in per-100 g table (flagged as an estimate, since recipes vary).
      1. `totals`: calories/protein_g[/carbs_g/fat_g] for the WHOLE amount eaten (home-made dishes, anything
         weighed). Always wins over the table and is flagged as an estimate.
      2. A table food: `quantity` servings, or `grams` converted using the serving weight when the table has one.
         `estimate` (per serving) is ignored for an exact table match but wins over a merely loose one.
      3. `estimate` per serving x quantity for a food not in the table (flagged as an estimate).
    The result always has a plain-language `summary` stating exactly what was stored."""
    if quantity is None or float(quantity) <= 0:
        raise ValueError("quantity must be positive")
    if grams is not None and float(grams) <= 0:
        raise ValueError("grams must be positive")
    quantity = float(quantity)
    day = day or clock.today()
    label = name.strip()
    has_totals = bool(totals) and totals.get("calories") is not None and totals.get("protein_g") is not None
    has_estimate = bool(estimate) and estimate.get("calories") is not None and estimate.get("protein_g") is not None

    if ingredients:
        sums, lines, problems = ing_svc.compose(db, ingredients)
        if problems:
            return {"logged": False, "reason": " ".join(problems) + " Fix the ingredient names/weights and call "
                                                                     "log_food again, or give total_calories and total_protein_g."}
        _check_plausible(sums)
        shown = f"{label} ({float(grams):g} g)" if grams else label
        e = _entry(db, day, meal_type, shown, 1.0, sums, True)
        parts = ", ".join(f"{ln['grams']:g} g {ln['ingredient'].lower()}" for ln in lines)
        return {"logged": True, "id": e.id, "food": shown, "quantity": 1, "estimated": True, "source": "ingredients",
                "calories": e.calories, "protein_g": e.protein_g, "matched_as": None, "breakdown": lines,
                "summary": f"Logged {shown} as an ESTIMATE built from the ingredient table ({parts}): "
                           f"{e.calories:g} kcal, {e.protein_g:g} g protein."}

    if has_totals:
        vals = _vals(totals)
        _check_plausible(vals)
        shown = f"{label} ({float(grams):g} g)" if grams else label
        e = _entry(db, day, meal_type, shown, 1.0, vals, True)
        return {"logged": True, "id": e.id, "food": shown, "quantity": 1, "estimated": True, "source": "estimate",
                "calories": e.calories, "protein_g": e.protein_g, "matched_as": None,
                "summary": f"Logged {shown} as an ESTIMATE: {e.calories:g} kcal, {e.protein_g:g} g protein."}

    food, quality = match_food(db, name)
    # A table food that cannot convert grams (e.g. "1 glass") may still be computed from the per-100 g table.
    food_usable = quality == "exact" and not (grams and not serving_grams(food))
    ing, iquality = (None, "none") if food_usable else ing_svc.match_ingredient(db, name)
    if ing and iquality == "loose" and has_estimate:
        ing = None  # the caller gave its own numbers for a custom dish: do not substitute a different food
    g = err = None
    if ing:
        g, err = ing_svc._grams_for(ing, grams, quantity)
        if err and iquality == "loose":
            ing = None  # a vague name match without a usable amount: do not guess, fall through
    if ing:
        if err:
            return {"logged": False, "reason": err + " Then call log_food again."}
        if g > ing_svc.MAX_GRAMS:
            raise ValueError(f"{g:g} g looks wrong; check the units.")
        vals = ing_svc.scale(ing, g)
        _check_plausible(vals)
        shown = f"{ing.name} ({g:g} g)"
        e = _entry(db, day, meal_type, shown, 1.0, vals, False)
        note = "" if iquality == "exact" else f"; closest match to what you called '{label}'"
        return {"logged": True, "id": e.id, "food": shown, "quantity": 1, "estimated": False, "source": "ingredient",
                "calories": e.calories, "protein_g": e.protein_g, "matched_as": ing.name, "match": iquality,
                "summary": f"Logged {g:g} g {ing.name} = {e.calories:g} kcal, {e.protein_g:g} g protein, from the "
                           f"built-in table ({ing.calories_100g:g} kcal and {ing.protein_100g:g} g protein per 100 g){note}."}
    if food and quality == "loose" and has_estimate:
        food = None
    if food:
        qty = quantity
        if grams:
            sg = serving_grams(food)
            if not sg:
                return {"logged": False, "reason": (
                    f"'{food.name}' is stored per '{food.serving}' with no weight, so {float(grams):g} g cannot be "
                    "converted. Call log_food again with total_calories and total_protein_g for the whole amount.")}
            qty = round(float(grams) / sg, 2)
        per = {"calories": food.calories, "protein_g": food.protein_g, "carbs_g": food.carbs_g, "fat_g": food.fat_g,
               "fibre_g": food.fibre_g or 0}
        _check_plausible({"calories": food.calories * qty, "protein_g": food.protein_g * qty})
        e = _entry(db, day, meal_type, food.name, qty, per, False, scale=qty)
        note = "" if quality == "exact" else f"; closest match to what you called '{label}'"
        return {"logged": True, "id": e.id, "food": food.name, "quantity": qty, "estimated": False, "source": "table",
                "calories": e.calories, "protein_g": e.protein_g, "matched_as": food.name, "match": quality,
                "summary": f"Logged {qty:g} x {food.name} (1 serving = {food.serving}) = {e.calories:g} kcal, "
                           f"{e.protein_g:g} g protein, from the food table{note}."}

    if has_estimate:
        vals = _vals(estimate)
        _check_plausible({k: v * quantity if k in ("calories", "protein_g") else v for k, v in vals.items()})
        e = _entry(db, day, meal_type, label, quantity, vals, True, scale=quantity)
        return {"logged": True, "id": e.id, "food": label, "quantity": quantity, "estimated": True,
                "source": "estimate", "calories": e.calories, "protein_g": e.protein_g, "matched_as": None,
                "summary": f"Logged {quantity:g} x {label} as an ESTIMATE = {e.calories:g} kcal, "
                           f"{e.protein_g:g} g protein."}
    return {"logged": False, "reason": f"'{label}' is not in the food table. Call log_food again with 'ingredients' (name and "
                                       "grams of each ingredient eaten), or total_calories and total_protein_g for the "
                                       "whole amount eaten."}


def log_ingredient(db: Session, ingredient_id: int, grams: float, meal_type: str | None = None,
                   day: date | None = None) -> dict:
    """Log exactly this ingredient row for a weight (used by the Add food screen, no name matching involved)."""
    ing = db.get(Ingredient, ingredient_id)
    if ing is None:
        return {"logged": False, "reason": "That ingredient no longer exists."}
    grams = float(grams)
    if grams <= 0 or grams > ing_svc.MAX_GRAMS:
        raise ValueError(f"grams must be between 0 and {ing_svc.MAX_GRAMS:g}")
    vals = ing_svc.scale(ing, grams)
    _check_plausible(vals)
    shown = f"{ing.name} ({grams:g} g)"
    e = _entry(db, day or clock.today(), meal_type, shown, 1.0, vals, False)
    return {"logged": True, "id": e.id, "food": shown, "quantity": 1, "estimated": False, "source": "ingredient",
            "calories": e.calories, "protein_g": e.protein_g, "matched_as": ing.name,
            "summary": f"Logged {grams:g} g {ing.name} = {e.calories:g} kcal, {e.protein_g:g} g protein."}


def daily_totals(db: Session, day: date | None = None) -> dict:
    day = day or clock.today()
    row = db.execute(
        select(func.coalesce(func.sum(MealLog.calories), 0), func.coalesce(func.sum(MealLog.protein_g), 0),
               func.coalesce(func.sum(MealLog.carbs_g), 0), func.coalesce(func.sum(MealLog.fat_g), 0),
               func.count(MealLog.id), func.coalesce(func.sum(MealLog.fibre_g), 0)).where(MealLog.day == day)
    ).one()
    items = db.scalars(select(MealLog).where(MealLog.day == day).order_by(MealLog.logged_at)).all()
    return {
        "day": day.isoformat(), "calories": round(row[0], 1), "protein_g": round(row[1], 1),
        "carbs_g": round(row[2], 1), "fat_g": round(row[3], 1), "entries": row[4], "fibre_g": round(row[5], 1),
        "any_estimated": any(i.estimated for i in items),
        "items": [{"id": i.id, "food": i.food_name, "qty": i.quantity, "kcal": i.calories,
                   "protein_g": i.protein_g, "fibre_g": i.fibre_g or 0, "meal_type": i.meal_type,
                   "estimated": i.estimated} for i in items],
    }


def sets_on(db: Session, day: date) -> int:
    return db.scalar(select(func.count(WorkoutSet.id)).join(WorkoutSession).where(WorkoutSession.day == day)) or 0


def trained_today(db: Session, day: date | None = None) -> bool:
    return sets_on(db, day or clock.today()) >= MIN_SETS_FOR_BONUS


def steps_on(db: Session, day: date) -> int | None:
    return db.scalar(select(DayStat.steps).where(DayStat.day == day))


def remaining(db: Session, day: date | None = None) -> dict:
    day = day or clock.today()
    p, t = get_profile(db), daily_totals(db, day)
    bonus = tg.training_bonus(sets_on(db, day), p.weight_kg, MIN_SETS_FOR_BONUS)
    steps = steps_on(db, day)
    steps_extra = tg.steps_bonus(steps, p.weight_kg)
    cal_target = p.calorie_target + bonus + steps_extra
    return {
        "day": day.isoformat(), "goal": p.goal,
        "calorie_target": cal_target, "training_day_bonus": bonus, "steps_bonus": steps_extra, "steps": steps,
        "base_calorie_target": p.calorie_target,
        "calories_eaten": t["calories"], "calories_remaining": round(cal_target - t["calories"], 1),
        "protein_target_g": p.protein_target_g, "protein_eaten_g": t["protein_g"],
        "protein_remaining_g": round(p.protein_target_g - t["protein_g"], 1),
        "carbs_eaten_g": t["carbs_g"], "fat_eaten_g": t["fat_g"],
        "fibre_eaten_g": t["fibre_g"], "fibre_target_g": p.fibre_target_g or 30,
        "fibre_remaining_g": round((p.fibre_target_g or 30) - t["fibre_g"], 1),
        "any_estimated_entries": t["any_estimated"],
    }


def suggest_foods(db: Session, day: date | None = None, limit: int = 6) -> dict:
    """Rank foods from the table by how well one serving fits the remaining budget."""
    rem = remaining(db, day)
    cal_left, prot_left = rem["calories_remaining"], rem["protein_remaining_g"]
    if cal_left <= 0:
        return {"remaining": rem, "suggestions": [],
                "note": "Calorie target already reached; only light, high-protein options if needed."}
    scored = []
    for f in db.scalars(select(Food)).all():
        if f.calories > cal_left or f.calories <= 0:
            continue
        useful_protein = min(f.protein_g, max(prot_left, 0))
        scored.append((useful_protein / f.calories, f))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    return {"remaining": rem, "suggestions": [
        {"food": f.name, "serving": f.serving, "kcal": f.calories, "protein_g": f.protein_g}
        for _, f in scored[:limit]]}


def delete_meal(db: Session, meal_id: int) -> bool:
    m = db.get(MealLog, meal_id)
    if not m:
        return False
    db.delete(m)
    db.commit()
    return True
