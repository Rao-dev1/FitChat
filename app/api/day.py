"""Past days, water and stool endpoints for the phone UI. No language model involved."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import daylog
from ..services import digestion as dig
from .. import clock

router = APIRouter(prefix="/api", tags=["day"])


class WaterIn(BaseModel):
    ml: float = Field(ge=dig.MIN_ML, le=dig.MAX_ML)
    day: date | None = None


class BowelIn(BaseModel):
    bristol: int = Field(ge=1, le=7)
    warning_signs: bool = False
    note: str | None = Field(default=None, max_length=200)
    day: date | None = None


@router.get("/day/{day}")
def get_day(day: date, db: Session = Depends(get_db)):
    if day > clock.today():
        raise HTTPException(422, "That day hasn't happened yet.")
    if day < clock.today() - timedelta(days=daylog.MAX_BACK_DAYS):
        raise HTTPException(422, "That date is too far back.")
    return daylog.day_log(db, day)


@router.get("/days")
def days(limit: int = Query(default=14, ge=1, le=90), db: Session = Depends(get_db)):
    return daylog.recent_days(db, limit)


@router.get("/gut")
def gut(day: date | None = None, db: Session = Depends(get_db)):
    return dig.status(db, day)


@router.post("/water", status_code=201)
def add_water(body: WaterIn, db: Session = Depends(get_db)):
    try:
        res = dig.add_water(db, body.ml, body.day)
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    return {**res, "gut": dig.status(db, body.day)}


@router.delete("/water/{water_id}")
def remove_water(water_id: int, db: Session = Depends(get_db)):
    if not dig.delete_water(db, water_id):
        raise HTTPException(404, "entry not found")
    return {"gut": dig.status(db)}


@router.post("/bowel", status_code=201)
def add_bowel(body: BowelIn, db: Session = Depends(get_db)):
    try:
        res = dig.add_bowel(db, body.bristol, body.warning_signs, body.note, body.day)
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from e
    return {**res, "gut": dig.status(db, body.day)}


@router.delete("/bowel/{bowel_id}")
def remove_bowel(bowel_id: int, db: Session = Depends(get_db)):
    if not dig.delete_bowel(db, bowel_id):
        raise HTTPException(404, "entry not found")
    return {"gut": dig.status(db)}
