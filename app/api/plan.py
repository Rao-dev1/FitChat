"""Rest-of-day meal plan for the phone UI."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import plan as pl

router = APIRouter(prefix="/api/plan", tags=["plan"])


@router.get("")
def get_plan(exclude: list[str] = Query(default=[]), slots: list[str] = Query(default=[]),
             hour: int | None = Query(default=None, ge=0, le=23), db: Session = Depends(get_db)):
    return pl.plan_rest_of_day(db, hour=hour, slots=slots or None, exclude=exclude)
