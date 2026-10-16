"""Saved workouts (routines): build, start today's session with last-time numbers, flag busy gear and injuries,
and suggest which routine is next. All logic is code; the coach only reads and creates routines through it."""
import math
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Exercise, Routine, RoutineExercise, WorkoutSession, WorkoutSet
from . import injuries as inj_svc
from . import progress
from . import workouts as wk

MAX_EXERCISES = 15
MAX_ROUTINES = 30
DEFAULT_REST_S = 90

# Starter splits. Exercise names are exact names from the exercise database (a test checks every one resolves).
# (name, sets, rep_min, rep_max, rest_s)
TEMPLATES = {
    "push": ("Push day", "Chest, shoulders and triceps.", [
        ("Barbell Bench Press - Medium Grip", 4, 6, 10, 150), ("Incline Dumbbell Press", 3, 8, 12, 120),
        ("Dumbbell Shoulder Press", 3, 8, 12, 120), ("Side Lateral Raise", 3, 12, 15, 60),
        ("Triceps Pushdown", 3, 10, 15, 75), ("Standing Dumbbell Triceps Extension", 3, 10, 12, 75)]),
    "pull": ("Pull day", "Back and biceps.", [
        ("Wide-Grip Lat Pulldown", 4, 8, 12, 120), ("Seated Cable Rows", 3, 8, 12, 120),
        ("Bent Over Barbell Row", 3, 8, 10, 120), ("Face Pull", 3, 12, 15, 60),
        ("Barbell Curl", 3, 8, 12, 75), ("Hammer Curls", 3, 10, 12, 75)]),
    "legs": ("Leg day", "Quads, hamstrings, calves and abs.", [
        ("Barbell Squat", 4, 6, 10, 150), ("Leg Press", 3, 10, 12, 120), ("Romanian Deadlift", 3, 8, 10, 120),
        ("Lying Leg Curls", 3, 10, 12, 90), ("Standing Calf Raises", 4, 12, 15, 60), ("Cable Crunch", 3, 12, 15, 60)]),
    "upper": ("Upper body", "Chest, back, shoulders and arms.", [
        ("Barbell Bench Press - Medium Grip", 3, 6, 10, 150), ("Wide-Grip Lat Pulldown", 3, 8, 12, 120),
        ("Dumbbell Shoulder Press", 3, 8, 12, 120), ("Seated Cable Rows", 3, 8, 12, 120),
        ("Barbell Curl", 2, 8, 12, 75), ("Triceps Pushdown", 2, 10, 15, 75)]),
    "lower": ("Lower body", "Legs, glutes and core.", [
        ("Barbell Squat", 4, 6, 10, 150), ("Romanian Deadlift", 3, 8, 10, 120), ("Leg Press", 3, 10, 12, 120),
        ("Lying Leg Curls", 3, 10, 12, 90), ("Standing Calf Raises", 3, 12, 15, 60), ("Plank", 3, 30, 60, 60)]),
    "full": ("Full body", "One lift per big muscle group.", [
        ("Barbell Squat", 3, 6, 10, 150), ("Barbell Bench Press - Medium Grip", 3, 6, 10, 150),
        ("Seated Cable Rows", 3, 8, 12, 120), ("Dumbbell Shoulder Press", 2, 8, 12, 120),
        ("Romanian Deadlift", 2, 8, 10, 120), ("Plank", 2, 30, 60, 60)]),
}


class RoutineError(ValueError):
    """A problem with what the user entered; the message is shown as is."""


class NameTaken(RoutineError):
    pass


def _item_json(i: RoutineExercise) -> dict:
    e = i.exercise
    return {"id": i.id, "exercise_id": e.id, "name": e.name, "equipment": e.equipment,
            "primary_muscles": e.primary_muscles, "sets": i.sets, "rep_min": i.rep_min, "rep_max": i.rep_max,
            "rest_s": i.rest_s}


def _last_done(db: Session, r: Routine) -> date | None:
    """Latest day on which at least half of the routine's exercises were trained."""
    ids = [i.exercise_id for i in r.items]
    if not ids:
        return None
    need = max(1, math.ceil(len(ids) / 2))
    rows = db.execute(
        select(WorkoutSession.day, func.count(func.distinct(WorkoutSet.exercise_id)))
        .join(WorkoutSet, WorkoutSet.session_id == WorkoutSession.id)
        .where(WorkoutSet.exercise_id.in_(ids)).group_by(WorkoutSession.day)).all()
    days = [d for d, n in rows if n >= need]
    return max(days) if days else None


def routine_json(db: Session, r: Routine) -> dict:
    last = _last_done(db, r)
    return {"id": r.id, "name": r.name, "notes": r.notes, "exercises": [_item_json(i) for i in r.items],
            "total_sets": sum(i.sets for i in r.items), "last_done": last.isoformat() if last else None,
            "days_since": (date.today() - last).days if last else None}


def list_routines(db: Session) -> list[dict]:
    return [routine_json(db, r) for r in db.scalars(select(Routine).order_by(Routine.created_at, Routine.id))]


def suggest(db: Session) -> dict | None:
    """The routine not trained for longest (never-trained first, in the order you made them)."""
    rs = list(db.scalars(select(Routine).order_by(Routine.created_at, Routine.id)))
    if not rs:
        return None
    info = [(r, _last_done(db, r)) for r in rs]
    today = date.today()
    pending = [(r, d) for r, d in info if d != today]
    if not pending:
        return {"routine_id": None, "reason": "You already trained a full routine today."}
    r, d = min(pending, key=lambda x: (x[1] is not None, x[1] or date.min))
    reason = "Not trained yet." if d is None else f"Last trained {(today - d).days} day{'s' if (today - d).days != 1 else ''} ago."
    return {"routine_id": r.id, "name": r.name, "reason": reason}


def _clean_item(db: Session, raw: dict, taken: set[str]) -> dict:
    ex = db.get(Exercise, raw["exercise_id"]) if raw.get("exercise_id") else wk.find_exercise(db, str(raw.get("name", "")), "strength")
    if ex is None:
        raise RoutineError(f"No exercise matching '{raw.get('name') or raw.get('exercise_id')}'. Search for it and pick from the list.")
    if ex.id in taken:
        raise RoutineError(f"'{ex.name}' is in the routine twice. Use one entry and raise its sets.")
    taken.add(ex.id)
    try:
        sets, lo, hi, rest = (int(raw.get("sets", 3)), int(raw.get("rep_min", 8)), int(raw.get("rep_max", 12)),
                              int(raw.get("rest_s", DEFAULT_REST_S)))
    except (TypeError, ValueError):
        raise RoutineError(f"Sets, reps and rest for '{ex.name}' must be whole numbers.") from None
    if not 1 <= sets <= 10:
        raise RoutineError(f"Sets for '{ex.name}' must be 1 to 10.")
    if not (1 <= lo <= hi <= progress.MAX_REPS):
        raise RoutineError(f"Reps for '{ex.name}' must go from a smaller number to a larger one, 1 to {progress.MAX_REPS}.")
    if not 15 <= rest <= 600:
        raise RoutineError(f"Rest for '{ex.name}' must be 15 to 600 seconds.")
    return {"exercise_id": ex.id, "sets": sets, "rep_min": lo, "rep_max": hi, "rest_s": rest}


def save_routine(db: Session, *, name: str, exercises: list[dict], notes: str | None = None,
                 existing: Routine | None = None) -> Routine:
    name = (name or "").strip()
    if not name or len(name) > 60:
        raise RoutineError("Give the routine a name (up to 60 characters).")
    notes = (notes or "").strip()[:300] or None
    if not exercises:
        raise RoutineError("Add at least one exercise.")
    if len(exercises) > MAX_EXERCISES:
        raise RoutineError(f"At most {MAX_EXERCISES} exercises in a routine.")
    for r in db.scalars(select(Routine)):
        if r is not existing and r.name.lower() == name.lower():
            raise NameTaken(f"You already have a routine called '{r.name}'.")
    if existing is None and (db.scalar(select(func.count()).select_from(Routine)) or 0) >= MAX_ROUTINES:
        raise RoutineError(f"At most {MAX_ROUTINES} routines.")
    taken: set[str] = set()
    items = [_clean_item(db, x, taken) for x in exercises]  # validate everything before touching the database
    r = existing or Routine()
    r.name, r.notes = name, notes
    r.items = [RoutineExercise(position=i, **it) for i, it in enumerate(items)]
    if existing is None:
        db.add(r)
    db.commit()
    return r


def delete_routine(db: Session, routine_id: int) -> bool:
    r = db.get(Routine, routine_id)
    if not r:
        return False
    db.delete(r)
    db.commit()
    return True


def templates() -> list[dict]:
    return [{"key": k, "name": v[0], "description": v[1], "exercises": len(v[2])} for k, v in TEMPLATES.items()]


def from_template(db: Session, key: str) -> Routine:
    if key not in TEMPLATES:
        raise RoutineError(f"Unknown template '{key}'.")
    name, notes, rows = TEMPLATES[key]
    existing = {r.name.lower() for r in db.scalars(select(Routine))}
    final, n = name, 2
    while final.lower() in existing:
        final, n = f"{name} {n}", n + 1
    items = [{"name": ex, "sets": s, "rep_min": lo, "rep_max": hi, "rest_s": rest} for ex, s, lo, hi, rest in rows]
    return save_routine(db, name=final, exercises=items, notes=notes)


def _blocked(e: Exercise, unavailable: list[str], injuries) -> str | None:
    for u in unavailable:
        if (u in wk.EQUIPMENT_TYPES and (e.equipment or "other") == u) or (u not in wk.EQUIPMENT_TYPES and u in e.name.lower()):
            return f"{u} is marked busy"
    area = inj_svc.blocked_by_injury(e, injuries)
    return f"your {area.replace('_', ' ')} injury" if area else None


def plan(db: Session, routine_id: int) -> dict | None:
    """Start-of-session view: each exercise with target, last time, sets done today, and (when the gear is busy
    or an injury makes it a poor choice) why and a few alternatives for the same muscle."""
    r = db.get(Routine, routine_id)
    if not r:
        return None
    unavailable, injuries = wk.unavailable_equipment(db), inj_svc.active_injuries(db)
    today = progress.today_log(db)
    done = {g["exercise_id"]: len(g["sets"]) for g in today["exercises"]}
    in_routine = {i.exercise_id for i in r.items}
    out = []
    for i in r.items:
        e = i.exercise
        row = {**_item_json(i), "sets_done": done.get(e.id, 0), "last_time": progress.last_performance(db, e.id),
               "blocked": _blocked(e, unavailable, injuries), "alternatives": []}
        if row["blocked"] and e.primary_muscles:
            opts = wk.exercise_options(db, e.primary_muscles[0], "strength", limit=8).get("options", [])
            row["alternatives"] = [{"exercise_id": o["id"], "name": o["name"], "equipment": o.get("equipment"),
                                    "last_time": o.get("last_time")} for o in opts if o["id"] not in in_routine][:3]
        out.append(row)
    target = sum(x["sets"] for x in out)
    done_sets = sum(min(x["sets_done"], x["sets"]) for x in out)
    return {**routine_json(db, r), "exercises": out, "target_sets": target, "done_sets": done_sets,
            "complete": target > 0 and done_sets >= target,
            "readiness": wk.readiness(db), "goal_rep_range": wk.REP_RANGE.get(wk.get_profile(db).goal, "8-12")}
