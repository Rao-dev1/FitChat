from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import daystats as ds

router = APIRouter(prefix="/api/daystats", tags=["daystats"])


class StatIn(BaseModel):
    day: date | None = None
    sleep_h: float | None = Field(default=None, gt=0, le=24)
    steps: int | None = Field(default=None, ge=0, le=ds.MAX_STEPS)


@router.get("")
def get_series(days: int = 14, db: Session = Depends(get_db)):
    return {**ds.series(db, days), "today": ds.get(db, date.today())}


@router.post("")
def post_stat(b: StatIn, db: Session = Depends(get_db)):
    try:
        return ds.log_stats(db, b.day, b.sleep_h, b.steps)
    except ds.StatError as e:
        raise HTTPException(422, str(e)) from None


@router.delete("/{day}")
def delete_stat(day: date, db: Session = Depends(get_db)):
    if not ds.delete_stats(db, day):
        raise HTTPException(404, "Nothing logged on that day.")
    return {"ok": True}
