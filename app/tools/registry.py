"""Functions the LLM may call. The model never does arithmetic or holds state: it calls these,
they read/write the database, and the model words the result."""
import logging
from datetime import date, timedelta
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..llm.base import ToolSpec
from ..services import arc as arc_svc
from ..services import body as body_svc
from ..services import daystats as ds_svc
from ..services import ingredients as ing_svc
from ..services import mealprep as mp_svc
from ..services import digestion as dig
from ..services import injuries as inj_svc
from ..services import nutrition as nut
from ..services import myfoods as mf_svc
from ..services import plan as plan_svc
from ..services import progress as prog
from ..services import recipes as rc_svc
from ..services import routines as rt_svc
from ..services import weekly as wkly
from ..services import workouts as wk

log = logging.getLogger(__name__)
Handler = Callable[[Session, dict], dict]


@dataclass
class Tool:
    spec: ToolSpec
    handler: Handler


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


_NUM, _STR, _INT = {"type": "number"}, {"type": "string"}, {"type": "integer"}


# ---------- handlers ----------
def _log_food(db, a):
    results = []
    days_ago = max(0, min(int(a.get("days_ago") or 0), 60))
    day = date.today() - timedelta(days=days_ago)
    for it in a.get("items", []):
        totals = {k[len("total_"):]: it[k] for k in ("total_calories", "total_protein_g", "total_carbs_g",
                                                     "total_fat_g", "total_fibre_g") if it.get(k) is not None}
        try:
            results.append(nut.log_item(db, it["name"], float(it.get("quantity") or 1), it.get("meal_type"),
                                        grams=it.get("grams"), totals=totals or None,
                                        ingredients=it.get("ingredients") or None, day=day))
        except ValueError as e:  # one bad item must not lose the others
            db.rollback()
            results.append({"logged": False, "reason": str(e)})
    if days_ago:
        rem = nut.remaining(db, day)
        return {"results": results, "remaining": rem, "summary": (
            f"For {day.isoformat()} ({days_ago} day{'s' if days_ago > 1 else ''} ago): {rem['calories_eaten']:g} kcal and "
            f"{rem['protein_eaten_g']:g} g protein eaten that day.")}
    rem = nut.remaining(db)
    today = (f"Today so far: {rem['calories_eaten']:g} kcal and {rem['protein_eaten_g']:g} g protein eaten. "
             f"Left: {rem['calories_remaining']:g} kcal and {rem['protein_remaining_g']:g} g protein.")
    return {"results": results, "remaining": rem, "summary": today}


def _lookup_nutrition(db, a):
    return ing_svc.lookup(db, a.get("items", []))


def _get_progress(db, a):
    ex = prog.find_logged(db, a["name"]) or wk.find_exercise(db, a["name"])
    if not ex:
        return {"found": False, "reason": f"No exercise named '{a['name']}'."}
    p = prog.exercise_progress(db, ex.id, sessions=5)
    if not p["sessions_logged"]:
        return {"found": True, "name": ex.name, "note": "Nothing logged for this exercise yet."}
    return {"found": True, "name": ex.name, **{k: p[k] for k in ("last", "history", "personal_bests", "sessions_logged")}}


def _log_weight(db, a):
    try:
        return wkly.log_weight(db, float(a["weight_kg"]))
    except (ValueError, KeyError, TypeError) as e:
        db.rollback()
        return {"logged": False, "reason": str(e)}


def _log_water(db, a):
    try:
        return dig.add_water(db, float(a["ml"]))
    except (ValueError, KeyError, TypeError) as e:
        db.rollback()
        return {"logged": False, "reason": str(e)}


def _log_stool(db, a):
    try:
        res = dig.add_bowel(db, int(a["bristol"]), bool(a.get("warning_signs")), a.get("note"))
    except (ValueError, KeyError, TypeError) as e:
        db.rollback()
        return {"logged": False, "reason": str(e)}
    return {**res, "digestion": dig.status(db)}


def _recipe_args(a):
    return dict(ingredients=a.get("ingredients") or [], servings=a.get("servings") or 1,
                cooked_weight_g=a.get("cooked_weight_g"))


def _analyze_recipe(db, a):
    try:
        return rc_svc.analyze(db, **_recipe_args(a))
    except mf_svc.FoodError as e:
        return {"ok": False, "problems": [str(e)], "summary": str(e)}


def _save_recipe(db, a):
    try:
        return rc_svc.save(db, name=a.get("name", ""), aliases=a.get("aliases"), notes=a.get("notes"), **_recipe_args(a))
    except mf_svc.FoodError as e:
        db.rollback()
        return {"saved": False, "reason": str(e)}


def _routine_by_name(db, name):
    from sqlalchemy import select as _sel
    from ..models import Routine
    n = str(name or "").strip().lower()
    rows = db.scalars(_sel(Routine)).all()
    return next((r for r in rows if r.name.lower() == n), None) or next((r for r in rows if n and n in r.name.lower()), None)


def _plan_week(db, a):
    p = mp_svc.generate(db, days=int(a.get("days") or 7), reshuffle=bool(a.get("reshuffle")))
    return {"summary": p["summary"], "days": [{"day": d["day"], "meals": {s["label"]: ", ".join(f"{i['servings']:g} x {i['food']}" for i in s["items"])
                                                                         for s in d["slots"]}, "totals": d["totals"]} for d in p["days"]],
            "grocery_text": p["grocery_text"]}


def _grocery(db):
    p = mp_svc.latest(db)
    return {"grocery_text": p["grocery_text"], "summary": p["summary"]} if p else {"error": "No weekly plan yet. Use plan_week first."}


def _get_routine_plan(db, a):
    r = _routine_by_name(db, a.get("name"))
    if not r:
        return {"found": False, "reason": f"No routine called '{a.get('name')}'.",
                "routines": [x["name"] for x in rt_svc.list_routines(db)]}
    return rt_svc.plan(db, r.id)


def _create_routine(db, a):
    try:
        r = rt_svc.save_routine(db, name=a.get("name", ""), notes=a.get("notes"), exercises=a.get("exercises") or [])
    except rt_svc.RoutineError as e:
        db.rollback()
        return {"saved": False, "reason": str(e)}
    j = rt_svc.routine_json(db, r)
    return {"saved": True, **j, "summary": f"Saved routine '{r.name}' with {len(j['exercises'])} exercises "
                                           f"({j['total_sets']} sets). Start it from the Workout screen."}


def _get_overview(db, a):
    p = nut.get_profile(db)
    return {"nutrition": nut.remaining(db), "trained_today": nut.trained_today(db),
            "readiness": wk.readiness(db), "experience": p.experience,
            "injuries": [{"area": i.area, "severity": i.severity} for i in inj_svc.active_injuries(db)],
            "unavailable_equipment": wk.unavailable_equipment(db)}


def _log_workout(db, a):
    res = wk.log_workout(db, a["exercise"], a.get("sets", []), notes=a.get("notes"))
    return {**res, "overview": {"nutrition": nut.remaining(db)}} if res.get("logged") else res


def _show_exercise(db, a):
    ex = wk.find_exercise(db, a["name"])
    if not ex:
        return {"found": False, "reason": f"No exercise named '{a['name']}'."}
    card = wk.exercise_card(ex)
    return {"found": True, "name": ex.name, "equipment": ex.equipment, "steps": ex.instructions, "_card": card}


def _set_injury(db, a):
    i = inj_svc.set_injury(db, a["area"], a.get("severity", "mild"), a.get("note"))
    return {"area": i.area, "severity": i.severity,
            "reminder": "Heuristic filtering only. Sharp, persistent or worsening pain needs a doctor/physio."}


def _update_profile(db, a):
    p = nut.get_profile(db)
    if a.get("goal"):
        if a["goal"] not in ("fat_loss", "muscle_gain", "maintain"):
            raise ValueError("goal must be fat_loss, muscle_gain or maintain")
        p.goal = a["goal"]
    if a.get("experience"):
        if a["experience"] not in wk.LEVELS_ALLOWED:
            raise ValueError("experience must be beginner, intermediate or expert")
        p.experience = a["experience"]
    for f in ("calorie_target", "protein_target_g", "weight_kg"):
        if a.get(f) is not None:
            if float(a[f]) <= 0:
                raise ValueError(f"{f} must be positive")
            setattr(p, f, float(a[f]))
    db.commit()
    return {"goal": p.goal, "calorie_target": p.calorie_target, "protein_target_g": p.protein_target_g,
            "weight_kg": p.weight_kg, "experience": p.experience}


TOOLS: list[Tool] = [
    Tool(ToolSpec("log_food",
                  "Log foods the user ate. Per item pick the FIRST that applies: (1) a plain food with a weight or "
                  "count (300 g cooked rajma, 2 eggs, 150 g paneer, 1 banana): just name + grams (or quantity for "
                  "countable things). The app finds it in the built-in per-100 g ingredient table and computes the "
                  "numbers itself. (2) a dish from the user's food table: name + quantity in servings. (3) a "
                  "home-made or mixed dish: name + 'ingredients', a list of {name, grams} for the portion the user "
                  "ATE (include cooking oil/ghee, 1 tsp = 5 g, 1 tbsp = 14 g); the app sums them from the table. "
                  "(4) only if something is missing from the ingredient table: total_calories and "
                  "total_protein_g for the WHOLE amount. Never put your own numbers on foods the table can compute. "
                  "Set days_ago (1 = yesterday, 2 = the day before, max 60) when the user is logging food from an earlier "
                  "day; leave it out for today. "
                  "The result has a 'summary' for each item and for the day: quote those numbers exactly.",
                  _obj({"days_ago": _INT, "items": {"type": "array", "items": _obj({
                      "name": _STR, "quantity": _NUM, "grams": _NUM, "meal_type": _STR,
                      "ingredients": {"type": "array", "items": _obj({"name": _STR, "grams": _NUM, "amount": _NUM,
                                                                      "unit": _STR, "quantity": _NUM}, ["name"])},
                      "total_calories": _NUM, "total_protein_g": _NUM, "total_carbs_g": _NUM,
                      "total_fat_g": _NUM, "total_fibre_g": _NUM}, ["name"])}}, ["items"])), _log_food),
    Tool(ToolSpec("lookup_nutrition",
                  "Look up calories, protein, carbs and fat per 100 g (and for a given weight) from the built-in "
                  "ingredient table, without logging anything. Use it to answer 'how much protein in X', to compare "
                  "foods, or to check names before building a dish. Items: [{name, grams?}].",
                  _obj({"items": {"type": "array", "items": _obj({"name": _STR, "grams": _NUM, "quantity": _NUM},
                                                                 ["name"])}}, ["items"])), _lookup_nutrition),
    Tool(ToolSpec("get_remaining_macros", "Calories/protein eaten and remaining today (includes training-day bonus).",
                  _obj({})), lambda db, a: nut.remaining(db)),
    Tool(ToolSpec("get_daily_food_log", "Everything logged today with totals.", _obj({})),
         lambda db, a: nut.daily_totals(db)),
    Tool(ToolSpec("suggest_next_food", "Foods from the user's table that best fit the remaining calories/protein.",
                  _obj({"limit": _INT})), lambda db, a: nut.suggest_foods(db, limit=int(a.get("limit", 6)))),
    Tool(ToolSpec("get_today_overview",
                  "One-shot context: macros remaining, whether trained today, readiness, injuries, unavailable "
                  "equipment. Call before giving combined food+gym advice.", _obj({})), _get_overview),
    Tool(ToolSpec("log_workout", "Log sets for one exercise today (weight_kg 0 for bodyweight). The result lists any new personal records in prs.",
                  _obj({"exercise": _STR, "sets": {"type": "array", "items": _obj(
                      {"reps": _INT, "weight_kg": _NUM}, ["reps"])}, "notes": _STR}, ["exercise", "sets"])),
         _log_workout),
    Tool(ToolSpec("get_exercise_progress",
                  "Progress on one exercise: last session, recent sessions, personal bests (estimated 1-rep max) and "
                  "what to try next. Use for 'how is my bench going' or before suggesting a weight.",
                  _obj({"name": _STR}, ["name"])), _get_progress),
    Tool(ToolSpec("get_weekly_summary",
                  "Summary of the last N days (default 7): average calories and protein against target, days the "
                  "protein target was reached, training days and sets, and the bodyweight trend. Use for 'how was my "
                  "week' or 'am I on track'. Quote its summary and lines exactly.",
                  _obj({"days": _INT})), lambda db, a: wkly.weekly_summary(db, days=int(a.get("days", 7)))),
    Tool(ToolSpec("log_weight", "Record today's bodyweight in kg (a second reading today replaces the first).",
                  _obj({"weight_kg": _NUM}, ["weight_kg"])), _log_weight),
    Tool(ToolSpec("log_water", "Record water drunk, in ml (a glass is about 250, a bottle 500 to 1000). Say the "
                  "returned summary.", _obj({"ml": _NUM}, ["ml"])), _log_water),
    Tool(ToolSpec("log_stool", "Record a bowel movement on the Bristol scale: 1-2 hard/constipated, 3-5 normal, "
                  "6-7 loose/watery. Ask the user which type if unclear. Set warning_signs true if they mention "
                  "blood, black stool or severe pain.", _obj({"bristol": _INT, "warning_signs": {"type": "boolean"},
                                                              "note": _STR}, ["bristol"])), _log_stool),
    Tool(ToolSpec("get_digestion_status", "Today's water and fibre against targets, days since the last bowel "
                  "movement, recent stool pattern, high-fibre food options and rule-based hints. Use for digestion, "
                  "constipation or 'what should I eat for fibre' questions and before suggesting meals. Quote its hints.",
                  _obj({})), lambda db, a: dig.status(db)),
    Tool(ToolSpec("analyze_recipe",
                  "Total a home recipe from its ingredient list WITHOUT saving: per-serving calories, protein, carbs, "
                  "fat and fibre, a line-by-line breakdown, assumptions and warnings. Each ingredient: name plus "
                  "grams, or amount + unit (g, kg, ml, tsp, tbsp, cup, glass, katori, piece). Bare names mean the raw/dry "
                  "weight; write 'cooked rice' for cooked. servings = how many portions the recipe makes; "
                  "cooked_weight_g = weight of the finished dish if known (ask; it makes gram portions exact). "
                  "If ok is false, ask the user about the problems; never invent numbers.",
                  _obj({"ingredients": {"type": "array", "items": _obj({"name": _STR, "grams": _NUM, "amount": _NUM, "unit": _STR, "quantity": _NUM}, ["name"])},
                        "servings": _NUM, "cooked_weight_g": _NUM}, ["ingredients"])), _analyze_recipe),
    Tool(ToolSpec("save_recipe",
                  "Save a home recipe so it can be logged by name later (same arguments as analyze_recipe plus name, "
                  "optional aliases and notes). Call analyze_recipe first, confirm servings with the user, then save. "
                  "Afterwards log a portion with log_food using the recipe name (quantity = servings eaten, or grams eaten).",
                  _obj({"name": _STR, "aliases": {"type": "array", "items": _STR}, "notes": _STR,
                        "ingredients": {"type": "array", "items": _obj({"name": _STR, "grams": _NUM, "amount": _NUM, "unit": _STR, "quantity": _NUM}, ["name"])},
                        "servings": _NUM, "cooked_weight_g": _NUM}, ["name", "ingredients"])), _save_recipe),
    Tool(ToolSpec("list_recipes", "The user's saved recipes with per-serving nutrition.", _obj({})),
         lambda db, a: {"recipes": rc_svc.list_recipes(db)}),
    Tool(ToolSpec("plan_rest_of_day", "Build a meal plan for the rest of today from what is left of calories, protein "
                  "and fibre, using the user's own foods and recipes. Use for 'what should I eat now/for dinner/rest of "
                  "the day'. exclude: food names to avoid (for 'something else'). Read out the summary as is.",
                  _obj({"exclude": {"type": "array", "items": _STR}})),
         lambda db, a: plan_svc.plan_rest_of_day(db, exclude=a.get("exclude"))),
    Tool(ToolSpec("log_measurements", "Save tape measurements in cm for today (or days_ago). Any of waist_cm, chest_cm, hips_cm, "
                  "arm_cm, thigh_cm. Quote the summary.", _obj({"waist_cm": _NUM, "chest_cm": _NUM, "hips_cm": _NUM, "arm_cm": _NUM,
                                                               "thigh_cm": _NUM, "days_ago": _INT})),
         lambda db, a: body_svc.log_measures(db, date.today() - timedelta(days=int(a.get("days_ago") or 0)),
                                            **{k: a.get(k) for k in body_svc.FIELDS})),
    Tool(ToolSpec("get_body_progress", "Measurements over time and what changed since the first entry. Photos are viewed in the "
                  "app, not here.", _obj({})),
         lambda db, a: {k: v for k, v in body_svc.overview(db).items() if k != "photos"}),
    Tool(ToolSpec("log_sleep_steps", "Record last night's sleep (sleep_h hours) and/or today's steps (steps). days_ago for earlier "
                  "days. Quote the summary.", _obj({"sleep_h": _NUM, "steps": _INT, "days_ago": _INT})),
         lambda db, a: ds_svc.log_stats(db, date.today() - timedelta(days=int(a.get("days_ago") or 0)), a.get("sleep_h"), a.get("steps"))),
    Tool(ToolSpec("get_winter_arc", "Winter Arc (Oct 1 to Dec 31) progress: day count, streaks, this week's gym days, weight "
                  "change and an estimated end weight. Quote the summary.", _obj({})),
         lambda db, a: {k: v for k, v in arc_svc.status(db).items() if k != "dots"}),
    Tool(ToolSpec("plan_week", "Make a 7-day meal plan with a grocery list from the user's foods and recipes. reshuffle=true "
                  "for a different version. Give a short overview, then the grocery_text if they want to shop.",
                  _obj({"days": _INT, "reshuffle": {"type": "boolean"}})),
         lambda db, a: _plan_week(db, a)),
    Tool(ToolSpec("get_grocery_list", "The grocery list of the saved weekly plan, grouped by aisle.", _obj({})),
         lambda db, a: _grocery(db)),
    Tool(ToolSpec("list_routines", "The user's saved workouts (routines) and which one is due next (the one not "
                  "trained the longest). Use for 'what should I train today'. Then call get_routine_plan to see last "
                  "time's numbers and any exercise that is blocked by busy gear or an injury.", _obj({})),
         lambda db, a: {"routines": rt_svc.list_routines(db), "suggestion": rt_svc.suggest(db)}),
    Tool(ToolSpec("get_routine_plan", "Today's plan for one saved routine: per exercise the target, last time, sets "
                  "done today, and whether it is blocked (busy equipment or injury) with alternatives.",
                  _obj({"name": _STR}, ["name"])), _get_routine_plan),
    Tool(ToolSpec("create_routine", "Save a workout. exercises: [{name, sets, rep_min, rep_max, rest_s}] using real "
                  "exercise names (check with get_exercise_options if unsure). Typical: compound lifts 3-4 sets of "
                  "6-10 with 120-150 s rest, isolation 3 sets of 10-15 with 60-90 s.",
                  _obj({"name": _STR, "notes": _STR, "exercises": {"type": "array", "items": _obj(
                      {"name": _STR, "sets": _INT, "rep_min": _INT, "rep_max": _INT, "rest_s": _INT}, ["name"])}},
                       ["name", "exercises"])), _create_routine),
    Tool(ToolSpec("get_recent_training", "Recent sessions, sets per muscle and days since each muscle was trained.",
                  _obj({"days": _INT})), lambda db, a: wk.recent_training(db, int(a.get("days", 7)))),
    Tool(ToolSpec("get_exercise_options",
                  "Candidate exercises for a muscle, ALREADY filtered for unavailable equipment, injuries and "
                  "readiness. category: 'strength' or 'stretching'. muscle: one of abdominals, abductors, adductors, "
                  "biceps, calves, chest, forearms, glutes, hamstrings, lats, lower back, middle back, neck, "
                  "quadriceps, shoulders, traps, triceps; or a group: back, arms, legs, abs. 'limit' is how many "
                  "candidates to return (use N+2 when the user wants N). Results rotate between calls so "
                  "repeat requests give fresh exercises. Only recommend exercises from this list, using "
                  "the exact names.",
                  _obj({"muscle": _STR, "category": {"type": "string", "enum": ["strength", "stretching"]},
                        "limit": _INT}, ["muscle"])),
         lambda db, a: wk.exercise_options(db, a["muscle"], a.get("category", "strength"), int(a.get("limit", 6)))),
    Tool(ToolSpec("show_exercise", "Show the form pictures + step-by-step cues card for an exercise or stretch in "
                  "the chat. Call for each exercise you recommend (max ~4 per reply).", _obj({"name": _STR}, ["name"])),
         _show_exercise),
    Tool(ToolSpec("set_injury", "Record an injury. area: shoulder, knee, lower_back, elbow, wrist, neck, hip, ankle. "
                  "severity: mild, moderate, severe.", _obj({"area": _STR, "severity": _STR, "note": _STR}, ["area"])),
         _set_injury),
    Tool(ToolSpec("clear_injury", "Mark an injury area as recovered.", _obj({"area": _STR}, ["area"])),
         lambda db, a: {"cleared": inj_svc.clear_injury(db, a["area"])}),
    Tool(ToolSpec("set_daily_state", "Record today's energy (1 drained..5 great) and soreness (1 none..5 very sore).",
                  _obj({"energy": _INT, "soreness": _INT, "note": _STR})),
         lambda db, a: (lambda s: {"energy": s.energy, "soreness": s.soreness})(
             wk.set_daily_state(db, a.get("energy"), a.get("soreness"), a.get("note")))),
    Tool(ToolSpec("set_equipment_unavailable", "Mark equipment as busy/unavailable today: a type (barbell, dumbbell, "
                  "machine, cable, body only, kettlebells, bands...) or a specific machine name (e.g. 'leg press').",
                  _obj({"items": {"type": "array", "items": _STR}}, ["items"])),
         lambda db, a: {"unavailable": wk.set_equipment_unavailable(db, a["items"])}),
    Tool(ToolSpec("set_equipment_available", "Clear unavailable equipment (all if items omitted).",
                  _obj({"items": {"type": "array", "items": _STR}})),
         lambda db, a: {"cleared": wk.set_equipment_available(db, a.get("items"))}),
    Tool(ToolSpec("update_profile", "Change goal (fat_loss|muscle_gain|maintain), experience, calorie_target, "
                  "protein_target_g, weight_kg.", _obj({"goal": _STR, "experience": _STR, "calorie_target": _NUM,
                                                        "protein_target_g": _NUM, "weight_kg": _NUM})),
         _update_profile),
]
_BY_NAME = {t.spec.name: t for t in TOOLS}


def specs() -> list[ToolSpec]:
    return [t.spec for t in TOOLS]


def execute(db: Session, name: str, args: dict) -> tuple[dict, dict | None]:
    """Run a tool. Returns (result_for_model, ui_card_or_None). Never raises."""
    tool = _BY_NAME.get(name)
    if not tool:
        return {"error": f"Unknown tool '{name}'"}, None
    try:
        result = tool.handler(db, args or {})
    except (ValueError, KeyError, TypeError) as e:
        db.rollback()
        return {"error": f"Invalid input: {e}"}, None
    except Exception:  # noqa: BLE001 - keep the chat alive on any tool bug
        db.rollback()
        log.exception("tool %s failed", name)
        return {"error": "Internal error while running this tool."}, None
    card = result.pop("_card", None)
    return result, card
