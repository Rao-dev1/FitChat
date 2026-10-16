"""Weekly meal plan and grocery list for the phone UI."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import mealprep as mp

router = APIRouter(prefix="/api/mealprep", tags=["mealprep"])


class GenIn(BaseModel):
    days: int = Field(default=mp.MAX_DAYS, ge=1, le=mp.MAX_DAYS)
    reshuffle: bool = False


@router.get("")
def get_plan(db: Session = Depends(get_db)):
    return {"plan": mp.latest(db)}


@router.post("")
def make_plan(b: GenIn, db: Session = Depends(get_db)):
    try:
        return {"plan": mp.generate(db, days=b.days, reshuffle=b.reshuffle)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
