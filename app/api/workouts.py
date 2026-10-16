"""Logging sets from the phone UI and reading progress. No language model involved."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import nutrition as nut
from ..services import progress
from ..services import workouts as wk

router = APIRouter(prefix="/api/workout", tags=["workout"])


class SetIn(BaseModel):
    reps: int = Field(ge=1, le=progress.MAX_REPS)
    weight_kg: float = Field(default=0, ge=0, le=progress.MAX_WEIGHT_KG)  # 0 = bodyweight


class SetsIn(BaseModel):
    exercise_id: str
    sets: list[SetIn] = Field(min_length=1, max_length=progress.MAX_SETS_PER_CALL)


def _today(db: Session) -> dict:
    rem = nut.remaining(db)
    return {**progress.today_log(db), "training_day_bonus": rem["training_day_bonus"],
            "trained_today": nut.trained_today(db)}


@router.get("/today")
def today(db: Session = Depends(get_db)):
    return _today(db)


@router.post("/sets", status_code=201)
def add_sets(body: SetsIn, db: Session = Depends(get_db)):
    try:
        res = wk.log_sets(db, body.exercise_id, [s.model_dump() for s in body.sets])
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    if not res["logged"]:
        raise HTTPException(404, res["reason"])
    return {**res, "today": _today(db), "remaining": nut.remaining(db)}


@router.delete("/sets/{set_id}")
def remove_set(set_id: int, db: Session = Depends(get_db)):
    if not progress.delete_set(db, set_id):
        raise HTTPException(404, "set not found")
    return {"today": _today(db), "remaining": nut.remaining(db)}


@router.get("/progress/{exercise_id}")
def exercise_progress(exercise_id: str, db: Session = Depends(get_db)):
    p = progress.exercise_progress(db, exercise_id)
    if p is None:
        raise HTTPException(404, "exercise not found")
    return p


@router.get("/history")
def history(db: Session = Depends(get_db)):
    return progress.exercises_with_history(db)
