"""Reading and saving the profile, including the calculator-driven targets."""
from sqlalchemy.orm import Session

from . import nutrition as nut
from . import targets as tg


def _inputs(p) -> dict:
    return dict(weight_kg=p.weight_kg, height_cm=p.height_cm, age=p.age, sex=p.sex, activity=p.activity, goal=p.goal)


def view(db: Session) -> dict:
    p = nut.get_profile(db)
    return {"goal": p.goal, "experience": p.experience, "calorie_target": p.calorie_target,
            "protein_target_g": p.protein_target_g, "weight_kg": p.weight_kg, "water_target_ml": p.water_target_ml,
            "fibre_target_g": p.fibre_target_g, "gym_days_goal": p.gym_days_goal, "height_cm": p.height_cm,
            "age": p.age, "sex": p.sex, "activity": p.activity or "light", "auto_targets": bool(p.auto_targets),
            "suggestion": tg.suggest(**_inputs(p)),
            "activity_options": [{"value": k, "label": v[1]} for k, v in tg.ACTIVITY.items()]}


def refresh_if_auto(db: Session) -> bool:
    """When the person chose automatic targets, recalculate them from the current details."""
    p = nut.get_profile(db)
    if not p.auto_targets:
        return False
    s = tg.suggest(**_inputs(p))
    if not s["ready"]:
        return False
    p.calorie_target, p.protein_target_g = float(s["calories"]), float(s["protein_g"])
    return True


def apply_suggested(db: Session) -> dict:
    p = nut.get_profile(db)
    s = tg.suggest(**_inputs(p))
    if not s["ready"]:
        need = ", ".join(s["missing"]) or "your details"
        raise ValueError(f"Add {need} first.")
    p.calorie_target, p.protein_target_g = float(s["calories"]), float(s["protein_g"])
    db.commit()
    return view(db)


def save_body(db: Session, values: dict) -> dict:
    """Update any of the profile fields, validate body details, then refresh automatic targets."""
    p = nut.get_profile(db)
    for field in ("weight_kg", "height_cm", "age"):
        if values.get(field) is not None:
            tg.validate(field, values[field])
    if values.get("sex") is not None and values["sex"] not in tg.SEXES:
        raise ValueError("sex must be male, female or other")
    if values.get("activity") is not None and values["activity"] not in tg.ACTIVITY:
        raise ValueError("activity must be sedentary, light or moderate")
    weight = values.pop("weight_kg", None)
    for k, v in values.items():
        if v is not None:
            setattr(p, k, v)
    if weight is not None and weight != p.weight_kg:
        from . import weekly  # a new weight is also a reading in the weight history
        weekly.log_weight(db, float(weight))
    refresh_if_auto(db)
    db.commit()
    return view(db)
