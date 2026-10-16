"""Home recipes: describe the ingredients, get an honest per-serving breakdown, save it, log it by name later.
All arithmetic is code over the ingredient table; the language model only passes the description in."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Food, Recipe
from . import ingredients as ing_svc
from . import myfoods as mf

MAX_LINES = 40
MIN_SERVINGS, MAX_SERVINGS = 0.5, 50.0
MIN_COOKED_G, MAX_COOKED_G = 50.0, 20000.0
MAX_KCAL_PER_SERVING = 3000


def _check_inputs(ingredients, servings, cooked_weight_g) -> tuple[float, float | None]:
    if not ingredients:
        raise mf.FoodError("Add at least one ingredient.")
    if len(ingredients) > MAX_LINES:
        raise mf.FoodError(f"At most {MAX_LINES} ingredient lines.")
    try:
        servings = float(servings)
    except (TypeError, ValueError):
        raise mf.FoodError("Servings must be a number.") from None
    if not MIN_SERVINGS <= servings <= MAX_SERVINGS:
        raise mf.FoodError(f"Servings must be between {MIN_SERVINGS:g} and {MAX_SERVINGS:g}.")
    if cooked_weight_g in (None, "", 0):
        return servings, None
    cooked = float(cooked_weight_g)
    if not MIN_COOKED_G <= cooked <= MAX_COOKED_G:
        raise mf.FoodError(f"Weight of the finished dish must be between {MIN_COOKED_G:g} and {MAX_COOKED_G:g} g.")
    return servings, cooked


def analyze(db: Session, ingredients: list[dict], servings: float = 1, cooked_weight_g: float | None = None) -> dict:
    """Breakdown without saving. ok=False means problems must be fixed first (nothing is guessed)."""
    servings, cooked = _check_inputs(ingredients, servings, cooked_weight_g)
    r = ing_svc.compose_ex(db, ingredients, raw_default=True)
    out = {"ok": not r["problems"], "problems": r["problems"], "lines": r["lines"], "ignored": r["ignored"],
           "assumptions": r["assumptions"], "servings": servings, "cooked_weight_g": cooked, "warnings": []}
    if r["problems"]:
        out["summary"] = "Can't total this recipe yet: " + " ".join(r["problems"])
        return out
    total = r["totals"]
    per = {k: round(v / servings, 1) for k, v in total.items()}
    out.update(total=total, per_serving=per)
    if cooked:
        out["serving_g"] = round(cooked / servings)
        out["per_100g_cooked"] = {k: round(v * 100 / cooked, 1) for k, v in total.items()}
    loose = [ln["input"] for ln in r["lines"] if ln["match"] == "loose"]
    out["confidence"] = "medium" if (r["assumptions"] or loose) else "high"
    if per["calories"] > MAX_KCAL_PER_SERVING:
        raise mf.FoodError(f"{per['calories']:g} kcal per serving looks wrong. Check the amounts and the number of servings.")
    if per["calories"] > 1200:
        out["warnings"].append(f"{per['calories']:g} kcal per serving is a lot. Check the number of servings.")
    if cooked and out["per_100g_cooked"]["calories"] > 600:
        out["warnings"].append("Very calorie-dense for a cooked dish. Check the finished weight (it includes water and sauce).")
    oil = sum(ln["calories"] for ln in r["lines"] if "oil" in ln["ingredient"].lower() or "ghee" in ln["ingredient"].lower()
              or "butter" in ln["ingredient"].lower())
    if oil and total["calories"] and oil / total["calories"] > 0.4:
        out["warnings"].append("Over 40% of the calories come from cooking fat. All of it is counted, "
                               "though some stays in the pan; reduce it if you pour leftover oil away.")
    out["warnings"] += [f"Matched '{x}' loosely; check it picked the right ingredient." for x in loose]
    out["summary"] = (f"Per serving ({servings:g} servings): {per['calories']:g} kcal, {per['protein_g']:g} g protein, "
                      f"{per['carbs_g']:g} g carbs, {per['fat_g']:g} g fat, {per['fibre_g']:g} g fibre. "
                      f"Total {total['calories']:g} kcal. Confidence: {out['confidence']}"
                      + (f"; assumptions: {' '.join(r['assumptions'])}" if r["assumptions"] else "") + ".")
    return out


def _clean_lines(ingredients: list[dict]) -> list[dict]:
    keep = ("name", "grams", "amount", "unit", "quantity")
    return [{k: it[k] for k in keep if it.get(k) not in (None, "")} for it in ingredients]


def save(db: Session, *, name: str, ingredients: list[dict], servings: float = 1, cooked_weight_g: float | None = None,
         aliases: list[str] | None = None, notes: str | None = None, existing: Recipe | None = None) -> dict:
    name = mf.clean_text(name, "Name", 80, required=True)
    notes = mf.clean_text(notes, "Notes", 500)
    aliases = mf.clean_aliases(aliases)
    a = analyze(db, ingredients, servings, cooked_weight_g)
    if not a["ok"]:
        raise mf.FoodError(a["summary"])
    mf.check_names_free(db, [name, *aliases], existing.food if existing else None)
    per = a["per_serving"]
    serving = f"1 serving (about {a['serving_g']} g)" if a.get("serving_g") else "1 serving"
    food = existing.food if existing else Food(source="recipe")
    food.name, food.aliases, food.serving = name, aliases, serving
    food.calories, food.protein_g, food.carbs_g, food.fat_g, food.fibre_g = (
        per["calories"], per["protein_g"], per["carbs_g"], per["fat_g"], per["fibre_g"])
    food.source = "recipe"
    rec = existing or Recipe(food=food)
    rec.servings, rec.cooked_weight_g, rec.notes = a["servings"], a["cooked_weight_g"], notes
    rec.ingredients = _clean_lines(ingredients)
    if existing is None:
        db.add(food)
        db.add(rec)
    db.commit()
    return {**recipe_json(rec), "analysis": a,
            "summary": f"Saved recipe '{name}': {per['calories']:g} kcal and {per['protein_g']:g} g protein per serving "
                       f"(1 serving = {serving[10:-1] if a.get('serving_g') else 'one of ' + format(a['servings'], 'g')}). "
                       "Log it any time by name."}


def recipe_json(r: Recipe) -> dict:
    f = r.food
    return {"id": r.id, "food_id": f.id, "name": f.name, "aliases": f.aliases, "serving": f.serving,
            "servings": r.servings, "cooked_weight_g": r.cooked_weight_g, "ingredients": r.ingredients, "notes": r.notes,
            "per_serving": {"calories": f.calories, "protein_g": f.protein_g, "carbs_g": f.carbs_g, "fat_g": f.fat_g,
                            "fibre_g": f.fibre_g or 0}}


def list_recipes(db: Session) -> list[dict]:
    return [recipe_json(r) for r in db.scalars(select(Recipe).join(Food).order_by(Food.name))]


def delete(db: Session, recipe_id: int) -> bool:
    r = db.get(Recipe, recipe_id)
    if not r:
        return False
    food = r.food
    db.delete(r)
    db.delete(food)
    db.commit()
    return True
