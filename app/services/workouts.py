import random
import re
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (DailyState, EquipmentStatus, Exercise, ExerciseSuggestion, WorkoutSession,
                      WorkoutSet)
from . import injuries as inj_svc
from . import progress
from .nutrition import get_profile

EQUIPMENT_TYPES = {"barbell", "dumbbell", "machine", "cable", "body only", "kettlebells", "bands",
                   "medicine ball", "exercise ball", "foam roll", "e-z curl bar", "other"}
EQUIPMENT_ALIASES = {"bodyweight": "body only", "kettlebell": "kettlebells", "band": "bands",
                     "ez bar": "e-z curl bar", "ez curl bar": "e-z curl bar", "cables": "cable",
                     "machines": "machine", "dumbbells": "dumbbell", "barbells": "barbell"}
EQUIPMENT_PREFERENCE = ["barbell", "dumbbell", "machine", "cable", "body only", "kettlebells", "e-z curl bar"]
LEVELS_ALLOWED = {"beginner": {"beginner", "intermediate"}, "intermediate": {"beginner", "intermediate", "expert"},
                  "expert": {"beginner", "intermediate", "expert"}}
# Typical rep ranges by goal (general convention, not individualised advice)
REP_RANGE = {"muscle_gain": "6-12", "fat_loss": "8-15", "maintain": "8-12"}


# ---------- lookups ----------
def _stem(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def _tokens(s: str) -> list[str]:
    return [_stem(t) for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def norm_text(s: str) -> str:
    """Lower-cased, punctuation-free, plural-insensitive form used to spot exercise names in text."""
    return " ".join(_tokens(s))


def find_exercise(db: Session, name: str, category: str | None = None) -> Exercise | None:
    q = name.strip().lower()
    stmt = select(Exercise)
    if category:
        stmt = stmt.where(Exercise.category == category)
    exercises = db.scalars(stmt).all()
    for e in exercises:
        if e.name.lower() == q:
            return e
    toks = _tokens(q)
    hits = [e for e in exercises if toks and all(t in _tokens(e.name) for t in toks)]
    return min(hits, key=lambda e: len(e.name)) if hits else None


def search_exercises(db: Session, q: str = "", muscle: str | None = None,
                     category: str | None = None, limit: int = 30) -> list[Exercise]:
    out = []
    toks = _tokens(q)
    for e in db.scalars(select(Exercise).order_by(Exercise.name)):
        if category and e.category != category:
            continue
        if muscle and muscle.lower() not in (e.primary_muscles or []):
            continue
        if toks and not all(t in _tokens(e.name) for t in toks):
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


# ---------- state ----------
def set_daily_state(db: Session, energy: int | None = None, soreness: int | None = None,
                    note: str | None = None, day: date | None = None) -> DailyState:
    day = day or date.today()
    st = db.get(DailyState, day) or DailyState(day=day)
    for field, v in (("energy", energy), ("soreness", soreness)):
        if v is not None:
            if not 1 <= int(v) <= 5:
                raise ValueError(f"{field} must be 1-5")
            setattr(st, field, int(v))
    if note is not None:
        st.note = note
    db.merge(st)
    db.commit()
    return st


def readiness(db: Session, day: date | None = None) -> dict:
    st = db.get(DailyState, day or date.today())
    energy, soreness = (st.energy, st.soreness) if st else (3, 1)
    if energy <= 2 or soreness >= 4:
        level, advice = "low", "Keep it lighter: fewer sets, stop well short of failure, easier variations, or mobility work."
    elif energy >= 4 and soreness <= 2:
        level, advice = "high", "Good day to push: heavier compound work is reasonable."
    else:
        level, advice = "normal", "Standard session."
    return {"level": level, "energy": energy, "soreness": soreness, "advice": advice,
            "reported_today": st is not None}


def set_equipment_unavailable(db: Session, items: list[str]) -> list[str]:
    stored = []
    for raw in items:
        key = raw.strip().lower()
        key = EQUIPMENT_ALIASES.get(key, key)
        if key:
            db.merge(EquipmentStatus(equipment=key))
            stored.append(key)
    db.commit()
    return stored


def set_equipment_available(db: Session, items: list[str] | None = None) -> int:
    rows = db.scalars(select(EquipmentStatus)).all()
    n = 0
    for r in rows:
        if items is None or r.equipment in [EQUIPMENT_ALIASES.get(i.strip().lower(), i.strip().lower()) for i in items]:
            db.delete(r)
            n += 1
    db.commit()
    return n


def unavailable_equipment(db: Session) -> list[str]:
    return [r.equipment for r in db.scalars(select(EquipmentStatus))]


# ---------- logging ----------
def _log_sets(db: Session, ex: Exercise, sets: list[dict], day: date | None, notes: str | None) -> dict:
    if not sets:
        raise ValueError("at least one set is required")
    if len(sets) > progress.MAX_SETS_PER_CALL:
        raise ValueError(f"at most {progress.MAX_SETS_PER_CALL} sets at a time")
    checked = [progress.check_set(s.get("reps"), s.get("weight_kg", 0)) for s in sets]  # validate everything first
    day = day or date.today()
    prior = progress.best_before(db, ex.id)
    session = db.scalar(select(WorkoutSession).where(WorkoutSession.day == day))
    if not session:
        session = WorkoutSession(day=day, notes=notes)
        db.add(session)
        db.flush()
    n = len([s for s in session.sets if s.exercise_id == ex.id])
    for reps, weight in checked:
        n += 1
        db.add(WorkoutSet(session_id=session.id, exercise_id=ex.id, set_number=n, reps=reps, weight_kg=weight))
    db.commit()
    return {"logged": True, "exercise": ex.name, "exercise_id": ex.id, "sets_logged": len(checked),
            "day": day.isoformat(), "prs": progress.detect_prs(prior, checked, ex.name)}


def log_workout(db: Session, exercise_name: str, sets: list[dict], day: date | None = None,
                notes: str | None = None) -> dict:
    ex = find_exercise(db, exercise_name)
    if not ex:
        return {"logged": False, "reason": f"No exercise matching '{exercise_name}'. Try a more standard name."}
    return _log_sets(db, ex, sets, day, notes)


def log_sets(db: Session, exercise_id: str, sets: list[dict], day: date | None = None) -> dict:
    ex = db.get(Exercise, exercise_id)
    if not ex:
        return {"logged": False, "reason": "Unknown exercise."}
    return _log_sets(db, ex, sets, day, None)


def recent_training(db: Session, days: int = 7) -> dict:
    since = date.today() - timedelta(days=days)
    sessions = db.scalars(select(WorkoutSession).where(WorkoutSession.day >= since)
                          .order_by(WorkoutSession.day.desc())).all()
    sets_per_muscle: dict[str, int] = {}
    last_muscle_day: dict[str, date] = {}
    history = []
    for s in sessions:
        per_ex: dict[str, list] = {}
        for st in s.sets:
            per_ex.setdefault(st.exercise.name, []).append({"reps": st.reps, "weight_kg": st.weight_kg})
            for m in st.exercise.primary_muscles or []:
                sets_per_muscle[m] = sets_per_muscle.get(m, 0) + 1
                last_muscle_day[m] = max(last_muscle_day.get(m, s.day), s.day)
        history.append({"day": s.day.isoformat(), "exercises": per_ex})
    return {"window_days": days, "sessions": history, "sets_per_muscle": sets_per_muscle,
            "days_since_muscle_trained": {m: (date.today() - d).days for m, d in last_muscle_day.items()}}


# ---------- recommendations ----------
def _compact(e: Exercise) -> dict:
    return {"id": e.id, "name": e.name, "equipment": e.equipment, "level": e.level, "mechanic": e.mechanic,
            "primary": e.primary_muscles}


KNOWN_MUSCLES = {
    "abdominals", "abductors", "adductors", "biceps", "calves", "chest", "forearms", "glutes", "hamstrings",
    "lats", "lower back", "middle back", "neck", "quadriceps", "shoulders", "traps", "triceps",
}
MUSCLE_ALIASES = {
    "back": ["lats", "middle back"], "upper back": ["middle back", "traps", "lats"],
    "arms": ["biceps", "triceps"], "legs": ["quadriceps", "hamstrings", "glutes", "calves"],
    "abs": ["abdominals"], "ab": ["abdominals"], "core": ["abdominals"], "abdominal": ["abdominals"],
    "bicep": ["biceps"], "tricep": ["triceps"], "quads": ["quadriceps"], "quad": ["quadriceps"],
    "quadricep": ["quadriceps"], "hamstring": ["hamstrings"], "hams": ["hamstrings"], "glute": ["glutes"],
    "calf": ["calves"], "lat": ["lats"], "trap": ["traps"], "forearm": ["forearms"], "shoulder": ["shoulders"],
    "delts": ["shoulders"], "pecs": ["chest"], "pec": ["chest"], "lowerback": ["lower back"],
}
RECENT_DAYS = 4  # exercises shown or done in this window are offered last
GYM_EQUIPMENT = {"barbell", "dumbbell", "machine", "cable", "body only", "e-z curl bar"}
# Never suggested automatically (Olympic lifts, gymnastics skills, plyometrics, strongman). The user can still
# ask to see any of them by name.
ADVANCED_KEYWORDS = ("kipping", "muscle up", "muscle-up", "snatch", "clean", "jerk", "atlas", "stone", "tire",
                     "plyo", "jump", "handstand", "planche", "iron cross", "sandbag", "yoke", "lever", "human flag",
                     "dragon flag", "gironda", "one arm chin", "one-arm chin")


def _is_advanced(e: Exercise) -> bool:
    n = e.name.lower()
    return any(k in n for k in ADVANCED_KEYWORDS)


def resolve_muscles(spec: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r",|/|&|\band\b", spec.lower()):
        key = part.strip()
        if not key:
            continue
        for m in MUSCLE_ALIASES.get(key, [key]):
            if m not in out:
                out.append(m)
    return out


def recently_used_ids(db: Session, days: int = RECENT_DAYS) -> set[str]:
    ids = set(db.scalars(select(ExerciseSuggestion.exercise_id)
                         .where(ExerciseSuggestion.suggested_at >= datetime.now() - timedelta(days=days))))
    since = date.today() - timedelta(days=days)
    ids |= set(db.scalars(select(WorkoutSet.exercise_id).join(WorkoutSession).where(WorkoutSession.day >= since)))
    return ids


def record_suggestions(db: Session, exercise_ids: list[str]) -> None:
    for xid in dict.fromkeys(exercise_ids):
        db.add(ExerciseSuggestion(exercise_id=xid))
    db.commit()


def _select(pool: list[Exercise], limit: int, recent: set[str], rng: random.Random,
            tier_of=lambda e: 0) -> list[Exercise]:
    """Order of preference: fresh + well-suited, fresh + less suited, recently used + well-suited, recently used +
    less suited, then unusual equipment. Within that, a mix of compound and isolation work and no single
    equipment type dominating."""
    items = list(pool)
    rng.shuffle(items)

    def grp(fresh: bool, tiers: set[int]) -> list[Exercise]:
        return [e for e in items if (e.id not in recent) == fresh and tier_of(e) in tiers]

    groups = [grp(True, {0}), grp(True, {1}), grp(False, {0}), grp(False, {1}), grp(True, {2}), grp(False, {2})]
    chosen: list[Exercise] = []
    per_equip: dict[str, int] = {}
    cap = max(2, -(-limit // 3))
    want_compound = 1 if limit == 1 else round(limit * 0.6)

    def is_compound(e: Exercise) -> bool:
        return e.mechanic == "compound"

    def add(group: list[Exercise], pred, n: int, respect_cap: bool) -> None:
        for e in group:
            if n <= 0 or len(chosen) >= limit:
                return
            if e in chosen or not pred(e):
                continue
            key = e.equipment or "other"
            if respect_cap and per_equip.get(key, 0) >= cap:
                continue
            chosen.append(e)
            per_equip[key] = per_equip.get(key, 0) + 1
            n -= 1

    for group in groups:
        add(group, is_compound, want_compound - sum(1 for e in chosen if is_compound(e)), True)
        add(group, lambda e: not is_compound(e), limit - len(chosen), True)
        add(group, lambda e: True, limit - len(chosen), False)
    return chosen


def _with_last(db: Session, e: Exercise) -> dict:
    c = _compact(e)
    last = progress.last_performance(db, e.id)
    if last:
        c["last_time"] = last
    return c


def exercise_options(db: Session, muscle: str, category: str = "strength", limit: int = 6,
                     rng: random.Random | None = None) -> dict:
    """Filter in code (equipment, injuries, level, readiness) first; the LLM only ranks/explains the rest.
    Results rotate: exercises shown or done in the last few days are offered last."""
    muscles = resolve_muscles(muscle)
    bad = [m for m in muscles if m not in KNOWN_MUSCLES]
    if not muscles or bad:
        return {"error": f"Unknown muscle {bad or [muscle]}. Use one of: {', '.join(sorted(KNOWN_MUSCLES))}, "
                         "or a group: back, arms, legs, abs."}
    limit = max(1, min(int(limit), 100))
    profile = get_profile(db)
    ready = readiness(db)
    unavailable = unavailable_equipment(db)
    injuries = inj_svc.active_injuries(db)
    allowed_levels = set(LEVELS_ALLOWED.get(profile.experience, LEVELS_ALLOWED["beginner"]))
    if ready["level"] == "low":
        allowed_levels = {"beginner"}

    excluded = {"unavailable_equipment": 0, "injury": 0, "level": 0, "advanced": 0}
    pool: list[Exercise] = []
    for e in db.scalars(select(Exercise).where(Exercise.category == category)):
        if not set(muscles) & set(e.primary_muscles or []):
            continue
        if category == "strength" and _is_advanced(e):
            excluded["advanced"] += 1
            continue
        if any((u in EQUIPMENT_TYPES and (e.equipment or "other") == u) or
               (u not in EQUIPMENT_TYPES and u in e.name.lower()) for u in unavailable):
            excluded["unavailable_equipment"] += 1
            continue
        if inj_svc.blocked_by_injury(e, injuries):
            excluded["injury"] += 1
            continue
        if category == "strength" and e.level and e.level not in allowed_levels:
            excluded["level"] += 1
            continue
        pool.append(e)

    recent = recently_used_ids(db)
    preferred_levels = {"beginner": {"beginner"}, "intermediate": {"beginner", "intermediate"}}.get(profile.experience)

    def tier_of(e: Exercise) -> int:
        if category != "strength":
            return 0
        if (e.equipment or "other") not in GYM_EQUIPMENT:
            return 2
        return 1 if preferred_levels is not None and e.level not in preferred_levels else 0

    chosen = _select(pool, limit, recent, rng or random.Random(), tier_of)
    since_trained = recent_training(db, days=7)["days_since_muscle_trained"]
    return {
        "muscle": ", ".join(muscles), "category": category, "goal": profile.goal,
        "typical_rep_range": REP_RANGE.get(profile.goal, "8-12") if category == "strength" else None,
        "readiness": ready, "unavailable_equipment": unavailable,
        "active_injuries": [{"area": i.area, "severity": i.severity} for i in injuries],
        "days_since_muscle_trained": {m: since_trained.get(m) for m in muscles},
        "excluded_counts": excluded,
        "options": [_with_last(db, e) for e in chosen], "total_matching": len(pool),
        "fresh_matching": sum(1 for e in pool if e.id not in recent),
        "note": "Use the exact names. Options already rotate away from recent exercises.",
    }


def exercise_card(e: Exercise) -> dict:
    base = get_settings().exercise_image_base_url
    return {"type": "exercise", "id": e.id, "name": e.name, "category": e.category, "equipment": e.equipment,
            "level": e.level, "primary_muscles": e.primary_muscles, "secondary_muscles": e.secondary_muscles,
            "images": [base + i for i in (e.images or [])], "steps": e.instructions}
