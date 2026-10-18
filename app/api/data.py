"""Direct (non-LLM) endpoints: quick-tap logging and dashboards cost zero model quota."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Food, Ingredient
from ..services import injuries as inj_svc
from ..services import nutrition as nut
from ..services import workouts as wk
from .. import clock

router = APIRouter(prefix="/api", tags=["data"])
MAX_BACKFILL_DAYS = 60


def _past_ok(day: date | None) -> date | None:
    if day is None:
        return None
    if day > clock.today():
        raise HTTPException(422, "Can't log food for a future day.")
    if day < clock.today() - timedelta(days=MAX_BACKFILL_DAYS):
        raise HTTPException(422, f"Can only log food up to {MAX_BACKFILL_DAYS} days back.")
    return day


class MealIn(BaseModel):
    day: date | None = None  # log for an earlier day (forgot to log yesterday's dinner)
    name: str
    quantity: float = Field(default=1, gt=0, le=50)
    meal_type: str | None = None
    calories: float | None = None  # per serving, only for foods not in the table
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


class WeighedIn(BaseModel):
    day: date | None = None
    ingredient_id: int
    grams: float = Field(gt=0, le=5000)
    meal_type: str | None = None


class ProfileIn(BaseModel):
    goal: str | None = Field(default=None, pattern="^(fat_loss|muscle_gain|maintain)$")
    experience: str | None = Field(default=None, pattern="^(beginner|intermediate|expert)$")
    calorie_target: float | None = Field(default=None, gt=0)
    protein_target_g: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    water_target_ml: float | None = Field(default=None, ge=500, le=10000)
    fibre_target_g: float | None = Field(default=None, ge=5, le=100)
    gym_days_goal: int | None = Field(default=None, ge=1, le=7)


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
            "protein_target_g": p.protein_target_g, "weight_kg": p.weight_kg,
            "water_target_ml": p.water_target_ml, "fibre_target_g": p.fibre_target_g,
            "gym_days_goal": p.gym_days_goal}


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
    return [{"id": f.id, "name": f.name, "aliases": f.aliases, "serving": f.serving, "calories": f.calories,
             "protein_g": f.protein_g, "carbs_g": f.carbs_g, "fat_g": f.fat_g, "fibre_g": f.fibre_g or 0,
             "source": f.source} for f in rows]


@router.get("/ingredients")
def ingredients(q: str = "", db: Session = Depends(get_db)):
    """The built-in per-100 g table, for logging by weight."""
    q = q.strip().lower()
    rows = [i for i in db.scalars(select(Ingredient).order_by(Ingredient.name))
            if not q or q in i.name.lower() or any(q in a.lower() for a in i.aliases)]
    return [{"id": i.id, "name": i.name, "aliases": i.aliases, "calories_100g": i.calories_100g, "protein_100g": i.protein_100g,
             "carbs_100g": i.carbs_100g, "fat_100g": i.fat_100g, "fibre_100g": i.fibre_100g or 0, "serving_g": i.serving_g,
             "serving_label": i.serving_label, "source": i.source} for i in rows]


@router.post("/meals/weighed", status_code=201)
def log_weighed(body: WeighedIn, db: Session = Depends(get_db)):
    try:
        res = nut.log_ingredient(db, body.ingredient_id, body.grams, body.meal_type, _past_ok(body.day))
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    if not res["logged"]:
        raise HTTPException(404, res["reason"])
    return {**res, "remaining": nut.remaining(db)}


@router.post("/meals", status_code=201)
def log_meal(body: MealIn, db: Session = Depends(get_db)):
    est = {k: getattr(body, k) for k in ("calories", "protein_g", "carbs_g", "fat_g") if getattr(body, k) is not None}
    day = _past_ok(body.day)
    try:
        res = nut.log_item(db, body.name, body.quantity, body.meal_type, day=day, estimate=est or None)
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    if not res["logged"]:
        raise HTTPException(422, res["reason"])
    return {**res, "remaining": nut.remaining(db, day)}


@router.delete("/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    if not nut.delete_meal(db, meal_id):
        raise HTTPException(404, "meal not found")


@router.get("/summary/today")
def summary_today(db: Session = Depends(get_db)):
    return {"totals": nut.daily_totals(db), "remaining": nut.remaining(db),
            "readiness": wk.readiness(db), "recent_training": wk.recent_training(db),
            "gut": _gut_line(db)}


def _gut_line(db: Session) -> dict:
    from ..services import digestion as dig
    g = dig.status(db)
    return {k: g[k] for k in ("water_ml", "water_target_ml", "fibre_g", "fibre_target_g", "days_since_bowel", "alert")}


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
