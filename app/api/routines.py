"""Saved workouts for the phone UI. No language model involved."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Routine
from ..services import routines as rt

router = APIRouter(prefix="/api/routines", tags=["routines"])


class ItemIn(BaseModel):
    exercise_id: str | None = None
    name: str | None = None
    sets: int = Field(default=3, ge=1, le=10)
    rep_min: int = Field(default=8, ge=1, le=100)
    rep_max: int = Field(default=12, ge=1, le=100)
    rest_s: int = Field(default=rt.DEFAULT_REST_S, ge=15, le=600)


class RoutineIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    notes: str | None = Field(default=None, max_length=300)
    exercises: list[ItemIn] = Field(min_length=1, max_length=rt.MAX_EXERCISES)


class TemplateIn(BaseModel):
    key: str


def _fail(e: rt.RoutineError):
    raise HTTPException(409 if isinstance(e, rt.NameTaken) else 422, str(e)) from e


@router.get("")
def list_all(db: Session = Depends(get_db)):
    return {"routines": rt.list_routines(db), "suggestion": rt.suggest(db), "templates": rt.templates()}


@router.post("", status_code=201)
def create(body: RoutineIn, db: Session = Depends(get_db)):
    try:
        r = rt.save_routine(db, name=body.name, notes=body.notes, exercises=[x.model_dump(exclude_none=True) for x in body.exercises])
    except rt.RoutineError as e:
        db.rollback()
        _fail(e)
    return rt.routine_json(db, r)


@router.post("/from-template", status_code=201)
def from_template(body: TemplateIn, db: Session = Depends(get_db)):
    try:
        r = rt.from_template(db, body.key)
    except rt.RoutineError as e:
        db.rollback()
        _fail(e)
    return rt.routine_json(db, r)


@router.put("/{routine_id}")
def update(routine_id: int, body: RoutineIn, db: Session = Depends(get_db)):
    r = db.get(Routine, routine_id)
    if not r:
        raise HTTPException(404, "routine not found")
    try:
        r = rt.save_routine(db, name=body.name, notes=body.notes, existing=r,
                            exercises=[x.model_dump(exclude_none=True) for x in body.exercises])
    except rt.RoutineError as e:
        db.rollback()
        _fail(e)
    return rt.routine_json(db, r)


@router.delete("/{routine_id}", status_code=204)
def remove(routine_id: int, db: Session = Depends(get_db)):
    if not rt.delete_routine(db, routine_id):
        raise HTTPException(404, "routine not found")


@router.get("/{routine_id}/plan")
def plan(routine_id: int, db: Session = Depends(get_db)):
    p = rt.plan(db, routine_id)
    if p is None:
        raise HTTPException(404, "routine not found")
    return p
