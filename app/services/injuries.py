"""Injury-aware exercise filtering.

IMPORTANT: this is a conservative HEURISTIC filter (keywords + muscle groups), not medical advice.
It only removes exercises that are likely to load the affected area. Sharp, persistent or worsening
pain should be assessed by a doctor or physiotherapist.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Exercise, Injury

SEVERITIES = ("mild", "moderate", "severe")

# area -> (muscle groups loaded by that area, name keywords of risky movements)
AREAS: dict[str, dict] = {
    "shoulder": {"muscles": {"shoulders"}, "keywords": ["overhead", "military", "behind neck", "upright row",
                                                         "dip", "snatch", "handstand", "arnold", "jerk"]},
    "knee": {"muscles": {"quadriceps"}, "keywords": ["squat", "lunge", "jump", "leg extension", "step-up",
                                                     "pistol", "box", "hop", "split"]},
    "lower_back": {"muscles": {"lower back"}, "keywords": ["deadlift", "good morning", "bent over", "snatch",
                                                          "clean", "back extension", "hyperextension", "superman"]},
    "elbow": {"muscles": {"biceps", "triceps"}, "keywords": ["skull", "french", "dip", "close-grip", "preacher"]},
    "wrist": {"muscles": {"forearms"}, "keywords": ["push-up", "pushup", "handstand", "wrist", "front squat",
                                                    "plank"]},
    "neck": {"muscles": {"neck"}, "keywords": ["behind neck", "shrug", "bridge", "neck"]},
    "hip": {"muscles": {"abductors", "adductors"}, "keywords": ["sumo", "hip", "split", "lunge", "adduct", "abduct"]},
    "ankle": {"muscles": {"calves"}, "keywords": ["jump", "hop", "calf raise", "box", "skip", "sprint"]},
}

ALIASES = {"back": "lower_back", "lower back": "lower_back", "lowerback": "lower_back", "knees": "knee",
           "shoulders": "shoulder", "wrists": "wrist", "elbows": "elbow", "hips": "hip", "ankles": "ankle"}


def normalize_area(area: str) -> str:
    a = area.strip().lower().replace("-", " ")
    a = ALIASES.get(a, a.replace(" ", "_"))
    if a not in AREAS:
        raise ValueError(f"Unknown injury area '{area}'. Use one of: {', '.join(AREAS)}")
    return a


def active_injuries(db: Session) -> list[Injury]:
    return list(db.scalars(select(Injury).where(Injury.active.is_(True))))


def blocked_by_injury(ex: Exercise, injuries: list[Injury]) -> str | None:
    name = ex.name.lower()
    primary, secondary = set(ex.primary_muscles or []), set(ex.secondary_muscles or [])
    for inj in injuries:
        rule = AREAS.get(inj.area)
        if not rule:
            continue
        if any(k in name for k in rule["keywords"]):
            return inj.area
        if inj.severity in ("moderate", "severe") and primary & rule["muscles"]:
            return inj.area
        if inj.severity == "severe" and secondary & rule["muscles"]:
            return inj.area
    return None


def set_injury(db: Session, area: str, severity: str = "mild", note: str | None = None) -> Injury:
    area = normalize_area(area)
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    inj = db.scalar(select(Injury).where(Injury.area == area, Injury.active.is_(True)))
    if inj:
        inj.severity, inj.note = severity, note or inj.note
    else:
        inj = Injury(area=area, severity=severity, note=note)
        db.add(inj)
    db.commit()
    return inj


def clear_injury(db: Session, area: str) -> int:
    area = normalize_area(area)
    rows = db.scalars(select(Injury).where(Injury.area == area, Injury.active.is_(True))).all()
    for r in rows:
        r.active = False
    db.commit()
    return len(rows)
