"""Direct (non-LLM) endpoints: quick-tap logging and dashboards cost zero model quota."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Food
from ..services import injuries as inj_svc
from ..services import nutrition as nut
from ..services import workouts as wk

router = APIRouter(prefix="/api", tags=["data"])


class MealIn(BaseModel):
    name: str
    quantity: float = Field(default=1, gt=0, le=50)
    meal_type: str | None = None
    calories: float | None = None  # per serving, only for foods not in the table
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


class ProfileIn(BaseModel):
    goal: str | None = Field(default=None, pattern="^(fat_loss|muscle_gain|maintain)$")
    experience: str | None = Field(default=None, pattern="^(beginner|intermediate|expert)$")
    calorie_target: float | None = Field(default=None, gt=0)
    protein_target_g: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)


class InjuryIn(BaseModel):
    area: str
    severity: str = "mild"
    note: str | None = None


class StateIn(BaseModel):
    energy: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=1, le=5)
    note: str | None = None


class EquipmentIn(BaseModel):
    items: list[str]


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    p = nut.get_profile(db)
    return {"goal": p.goal, "experience": p.experience, "calorie_target": p.calorie_target,
            "protein_target_g": p.protein_target_g, "weight_kg": p.weight_kg}


@router.put("/profile")
def put_profile(body: ProfileIn, db: Session = Depends(get_db)):
    p = nut.get_profile(db)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(p, k, v)
    db.commit()
    return get_profile(db)


@router.get("/foods")
def foods(q: str = "", db: Session = Depends(get_db)):
    q = q.lower()
    rows = [f for f in db.scalars(select(Food).order_by(Food.name))
            if not q or q in f.name.lower() or any(q in a.lower() for a in f.aliases)]
    return [{"id": f.id, "name": f.name, "serving": f.serving, "calories": f.calories, "protein_g": f.protein_g,
             "carbs_g": f.carbs_g, "fat_g": f.fat_g} for f in rows]


@router.post("/meals", status_code=201)
def log_meal(body: MealIn, db: Session = Depends(get_db)):
    est = {k: getattr(body, k) for k in ("calories", "protein_g", "carbs_g", "fat_g") if getattr(body, k) is not None}
    res = nut.log_item(db, body.name, body.quantity, body.meal_type, estimate=est or None)
    if not res["logged"]:
        raise HTTPException(422, res["reason"])
    return {**res, "remaining": nut.remaining(db)}


@router.delete("/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    if not nut.delete_meal(db, meal_id):
        raise HTTPException(404, "meal not found")


@router.get("/summary/today")
def summary_today(db: Session = Depends(get_db)):
    return {"totals": nut.daily_totals(db), "remaining": nut.remaining(db),
            "readiness": wk.readiness(db), "recent_training": wk.recent_training(db)}


@router.get("/summary/{day}")
def summary_day(day: date, db: Session = Depends(get_db)):
    return {"totals": nut.daily_totals(db, day), "remaining": nut.remaining(db, day)}


@router.get("/exercises")
def exercises(q: str = "", muscle: str | None = None, category: str | None = None, limit: int = 30,
              db: Session = Depends(get_db)):
    return [wk.exercise_card(e) for e in wk.search_exercises(db, q, muscle, category, min(limit, 100))]


@router.get("/exercises/{exercise_id}")
def exercise_detail(exercise_id: str, db: Session = Depends(get_db)):
    from ..models import Exercise
    e = db.get(Exercise, exercise_id)
    if not e:
        raise HTTPException(404, "exercise not found")
    return wk.exercise_card(e)


@router.get("/injuries")
def injuries(db: Session = Depends(get_db)):
    return [{"area": i.area, "severity": i.severity, "note": i.note} for i in inj_svc.active_injuries(db)]


@router.post("/injuries", status_code=201)
def add_injury(body: InjuryIn, db: Session = Depends(get_db)):
    try:
        i = inj_svc.set_injury(db, body.area, body.severity, body.note)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"area": i.area, "severity": i.severity}


@router.delete("/injuries/{area}")
def remove_injury(area: str, db: Session = Depends(get_db)):
    try:
        return {"cleared": inj_svc.clear_injury(db, area)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.put("/state")
def put_state(body: StateIn, db: Session = Depends(get_db)):
    st = wk.set_daily_state(db, body.energy, body.soreness, body.note)
    return {"energy": st.energy, "soreness": st.soreness}


@router.get("/equipment/unavailable")
def equipment(db: Session = Depends(get_db)):
    return wk.unavailable_equipment(db)


@router.put("/equipment/unavailable")
def mark_unavailable(body: EquipmentIn, db: Session = Depends(get_db)):
    return {"unavailable": wk.set_equipment_unavailable(db, body.items)}


@router.post("/equipment/available")
def free_some_equipment(body: EquipmentIn, db: Session = Depends(get_db)):
    """Mark only the listed items as available again."""
    return {"cleared": wk.set_equipment_available(db, body.items)}


@router.delete("/equipment/unavailable")
def mark_available(db: Session = Depends(get_db)):
    return {"cleared": wk.set_equipment_available(db)}
