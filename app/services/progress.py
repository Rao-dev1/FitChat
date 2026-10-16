"""Sets, personal bests and progression hints per exercise. All arithmetic is done here, in code."""
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Exercise, WorkoutSession, WorkoutSet
from .nutrition import get_profile

MAX_REPS, MAX_WEIGHT_KG, MAX_SETS_PER_CALL = 100, 500.0, 20
WEIGHT_STEP_KG = 2.5  # smallest common plate jump


def e1rm(weight_kg: float, reps: int) -> float:
    """Estimated one-rep max (Epley). 0 for bodyweight sets, where reps are the measure instead."""
    if weight_kg <= 0 or reps <= 0:
        return 0.0
    return round(weight_kg if reps == 1 else weight_kg * (1 + reps / 30), 1)


def check_set(reps, weight_kg) -> tuple[int, float]:
    try:
        r = int(reps)
        w = float(weight_kg or 0)
    except (TypeError, ValueError) as e:
        raise ValueError("reps and weight must be numbers") from e
    if not 1 <= r <= MAX_REPS:
        raise ValueError(f"reps must be between 1 and {MAX_REPS}")
    if not 0 <= w <= MAX_WEIGHT_KG:
        raise ValueError(f"weight must be between 0 and {MAX_WEIGHT_KG:g} kg (use 0 for bodyweight)")
    return r, round(w, 2)


def _rows(db: Session, exercise_id: str) -> list[tuple[date, WorkoutSet]]:
    stmt = (select(WorkoutSession.day, WorkoutSet).join(WorkoutSession, WorkoutSet.session_id == WorkoutSession.id)
            .where(WorkoutSet.exercise_id == exercise_id).order_by(WorkoutSession.day, WorkoutSet.set_number, WorkoutSet.id))
    return [(d, s) for d, s in db.execute(stmt).all()]


def best_before(db: Session, exercise_id: str) -> dict:
    """Personal bests from sets already stored (call BEFORE adding new sets)."""
    best_e, best_bw = 0.0, 0
    n = 0
    for _, s in _rows(db, exercise_id):
        n += 1
        if s.weight_kg > 0:
            best_e = max(best_e, e1rm(s.weight_kg, s.reps))
        else:
            best_bw = max(best_bw, s.reps)
    return {"has_history": n > 0, "e1rm": best_e, "bodyweight_reps": best_bw}


def detect_prs(prior: dict, new_sets: list[tuple[int, float]], exercise_name: str) -> list[dict]:
    """New personal records among sets just logged. The very first time an exercise is logged is not a PR."""
    if not prior["has_history"]:
        return []
    prs = []
    weighted = [e1rm(w, r) for r, w in new_sets if w > 0]
    if weighted and max(weighted) > prior["e1rm"] > 0:
        prs.append({"exercise": exercise_name, "kind": "e1rm", "value": max(weighted), "previous": prior["e1rm"],
                    "text": f"New best estimated 1-rep max on {exercise_name}: {max(weighted):g} kg (was {prior['e1rm']:g})."})
    bw = [r for r, w in new_sets if w <= 0]
    if bw and max(bw) > prior["bodyweight_reps"] > 0:
        prs.append({"exercise": exercise_name, "kind": "reps", "value": max(bw), "previous": prior["bodyweight_reps"],
                    "text": f"New best reps on {exercise_name}: {max(bw)} (was {prior['bodyweight_reps']})."})
    return prs


def _set_json(s: WorkoutSet) -> dict:
    return {"id": s.id, "set_number": s.set_number, "reps": s.reps, "weight_kg": s.weight_kg}


def _volume(sets) -> float:
    return round(sum(s.reps * s.weight_kg for s in sets), 1)


def _rep_range(goal: str) -> tuple[int, int]:
    from .workouts import REP_RANGE
    m = re.match(r"(\d+)-(\d+)", REP_RANGE.get(goal, "8-12"))
    return (int(m.group(1)), int(m.group(2))) if m else (8, 12)


def progression_hint(sets: list[WorkoutSet], goal: str) -> dict | None:
    """A simple double-progression rule from the last session: when every set at the top weight reached the top of
    the rep range, add weight; otherwise stay and add reps. A rule of thumb, not individual coaching."""
    if not sets:
        return None
    lo, hi = _rep_range(goal)
    top_w = max(s.weight_kg for s in sets)
    at_top = [s for s in sets if s.weight_kg == top_w]
    if top_w <= 0:
        if all(s.reps >= hi for s in at_top):
            return {"next_weight_kg": None, "text": f"All sets reached {hi}+ reps. Add weight or try a harder variation."}
        return {"next_weight_kg": None, "text": "Same movement: aim for one more rep on each set."}
    if all(s.reps >= hi for s in at_top):
        nxt = round(top_w + WEIGHT_STEP_KG, 2)
        return {"next_weight_kg": nxt, "text": f"Every set hit {hi}+ reps at {top_w:g} kg. Try {nxt:g} kg (reps will drop a little)."}
    if min(s.reps for s in at_top) < lo:
        return {"next_weight_kg": top_w, "text": f"Stay at {top_w:g} kg until every set reaches {lo}+ reps."}
    return {"next_weight_kg": top_w, "text": f"Stay at {top_w:g} kg and aim for one more rep per set (target {hi})."}


def last_session(db: Session, exercise_id: str, before: date | None = None) -> tuple[date, list[WorkoutSet]] | None:
    """Most recent day this exercise was done before `before` (default: today, so today's sets are excluded)."""
    before = before or date.today()
    by_day: dict[date, list[WorkoutSet]] = {}
    for d, s in _rows(db, exercise_id):
        if d < before:
            by_day.setdefault(d, []).append(s)
    if not by_day:
        return None
    d = max(by_day)
    return d, by_day[d]


def last_performance(db: Session, exercise_id: str) -> dict | None:
    """Compact 'last time + what to try next' used by the coach and by the logger."""
    got = last_session(db, exercise_id)
    if not got:
        return None
    d, sets = got
    hint = progression_hint(sets, get_profile(db).goal)
    return {"day": d.isoformat(), "sets": [{"reps": s.reps, "weight_kg": s.weight_kg} for s in sets],
            "next_hint": hint["text"] if hint else None, "next_weight_kg": hint["next_weight_kg"] if hint else None}


def exercise_progress(db: Session, exercise_id: str, sessions: int = 10) -> dict | None:
    ex = db.get(Exercise, exercise_id)
    if ex is None:
        return None
    rows = _rows(db, exercise_id)
    by_day: dict[date, list[WorkoutSet]] = {}
    for d, s in rows:
        by_day.setdefault(d, []).append(s)
    history = []
    for d in sorted(by_day, reverse=True)[:sessions]:
        ss = by_day[d]
        weighted = [s for s in ss if s.weight_kg > 0]
        top = max(weighted, key=lambda s: (e1rm(s.weight_kg, s.reps), s.weight_kg)) if weighted else max(ss, key=lambda s: s.reps)
        history.append({"day": d.isoformat(), "sets": [_set_json(s) for s in ss], "volume_kg": _volume(ss),
                        "top_set": {"reps": top.reps, "weight_kg": top.weight_kg}, "e1rm": e1rm(top.weight_kg, top.reps)})
    best = {"e1rm": None, "heaviest": None, "bodyweight_reps": None}
    for d, s in rows:
        if s.weight_kg > 0:
            v = e1rm(s.weight_kg, s.reps)
            if best["e1rm"] is None or v > best["e1rm"]["value"]:
                best["e1rm"] = {"value": v, "weight_kg": s.weight_kg, "reps": s.reps, "day": d.isoformat()}
            if best["heaviest"] is None or s.weight_kg > best["heaviest"]["weight_kg"]:
                best["heaviest"] = {"weight_kg": s.weight_kg, "reps": s.reps, "day": d.isoformat()}
        elif best["bodyweight_reps"] is None or s.reps > best["bodyweight_reps"]["reps"]:
            best["bodyweight_reps"] = {"reps": s.reps, "day": d.isoformat()}
    today_sets = by_day.get(date.today(), [])
    return {"exercise": {"id": ex.id, "name": ex.name, "equipment": ex.equipment,
                         "primary_muscles": ex.primary_muscles},
            "today": [_set_json(s) for s in today_sets], "last": last_performance(db, exercise_id),
            "history": history, "personal_bests": best, "sessions_logged": len(by_day)}


def today_log(db: Session, day: date | None = None) -> dict:
    day = day or date.today()
    session = db.scalar(select(WorkoutSession).where(WorkoutSession.day == day))
    groups: dict[str, dict] = {}
    for s in (sorted(session.sets, key=lambda x: x.id) if session else []):
        g = groups.setdefault(s.exercise_id, {"exercise_id": s.exercise_id, "name": s.exercise.name, "sets": []})
        g["sets"].append(_set_json(s))
    total_sets = sum(len(g["sets"]) for g in groups.values())
    for g in groups.values():
        g["volume_kg"] = round(sum(x["reps"] * x["weight_kg"] for x in g["sets"]), 1)
    return {"day": day.isoformat(), "exercises": list(groups.values()), "total_sets": total_sets}


def delete_set(db: Session, set_id: int) -> bool:
    s = db.get(WorkoutSet, set_id)
    if s is None:
        return False
    session, ex_id = s.session, s.exercise_id
    db.delete(s)
    db.flush()
    remaining = sorted((x for x in session.sets if x.exercise_id == ex_id and x.id != set_id), key=lambda x: x.set_number)
    for i, x in enumerate(remaining, 1):
        x.set_number = i
    if not [x for x in session.sets if x.id != set_id]:
        db.delete(session)
    db.commit()
    return True


def exercises_with_history(db: Session) -> list[dict]:
    stmt = (select(WorkoutSession.day, WorkoutSet).join(WorkoutSession, WorkoutSet.session_id == WorkoutSession.id))
    agg: dict[str, dict] = {}
    for d, s in db.execute(stmt).all():
        a = agg.setdefault(s.exercise_id, {"exercise_id": s.exercise_id, "name": s.exercise.name, "days": set(),
                                           "last_day": d, "best_e1rm": 0.0, "best_reps": 0})
        a["days"].add(d)
        a["last_day"] = max(a["last_day"], d)
        if s.weight_kg > 0:
            a["best_e1rm"] = max(a["best_e1rm"], e1rm(s.weight_kg, s.reps))
        else:
            a["best_reps"] = max(a["best_reps"], s.reps)
    out = [{"exercise_id": a["exercise_id"], "name": a["name"], "sessions": len(a["days"]),
            "last_day": a["last_day"].isoformat(), "best_e1rm": a["best_e1rm"] or None,
            "best_reps": a["best_reps"] or None} for a in agg.values()]
    return sorted(out, key=lambda x: x["last_day"], reverse=True)


def find_logged(db: Session, name: str) -> Exercise | None:
    """Match a spoken name ('bench press') against exercises the user has actually logged, most recent first, so a
    progress question lands on their lift rather than the shortest-named exercise in the whole library."""
    from .workouts import _tokens
    toks = _tokens(name)
    if not toks:
        return None
    for h in exercises_with_history(db):
        ex = db.get(Exercise, h["exercise_id"])
        if ex and (ex.name.lower() == name.strip().lower() or all(t in _tokens(ex.name) for t in toks)):
            return ex
    return None
