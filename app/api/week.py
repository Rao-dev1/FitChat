"""Weekly summary and bodyweight log for the phone UI. No language model involved."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import weekly

router = APIRouter(prefix="/api", tags=["week"])


class WeightIn(BaseModel):
    weight_kg: float = Field(ge=weekly.MIN_WEIGHT_KG, le=weekly.MAX_WEIGHT_KG)
    day: date | None = None


@router.get("/week")
def week(end: date | None = None, days: int = Query(default=7, ge=1, le=weekly.MAX_WINDOW_DAYS),
         db: Session = Depends(get_db)):
    return {**weekly.weekly_summary(db, end, days), "weights": weekly.weight_series(db, 60, end)}


@router.get("/weight")
def weights(days: int = Query(default=60, ge=1, le=365), db: Session = Depends(get_db)):
    return weekly.weight_series(db, days)


@router.post("/weight", status_code=201)
def add_weight(body: WeightIn, db: Session = Depends(get_db)):
    try:
        return weekly.log_weight(db, body.weight_kg, body.day)
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e


@router.delete("/weight/{day}", status_code=204)
def remove_weight(day: date, db: Session = Depends(get_db)):
    if not weekly.delete_weight(db, day):
        raise HTTPException(404, "no reading for that day")
