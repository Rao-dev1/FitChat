"""Recipe builder endpoints for the phone UI. No language model involved."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Recipe
from ..services import myfoods as mf
from ..services import recipes as rc

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


class LineIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    grams: float | None = Field(default=None, gt=0, le=5000)
    amount: float | None = Field(default=None, gt=0, le=5000)
    unit: str | None = Field(default=None, max_length=20)
    quantity: float | None = Field(default=None, gt=0, le=500)


class PreviewIn(BaseModel):
    ingredients: list[LineIn] = Field(min_length=1, max_length=rc.MAX_LINES)
    servings: float = 1
    cooked_weight_g: float | None = None


class RecipeIn(PreviewIn):
    name: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    notes: str | None = Field(default=None, max_length=500)


def _lines(body: PreviewIn) -> list[dict]:
    return [ln.model_dump(exclude_none=True) for ln in body.ingredients]


def _fail(e: mf.FoodError):
    raise HTTPException(409 if isinstance(e, (mf.NameTaken, mf.Protected)) else 422, str(e)) from e


@router.get("")
def list_all(db: Session = Depends(get_db)):
    return rc.list_recipes(db)


@router.post("/preview")
def preview(body: PreviewIn, db: Session = Depends(get_db)):
    try:
        return rc.analyze(db, _lines(body), body.servings, body.cooked_weight_g)
    except mf.FoodError as e:
        _fail(e)


@router.post("", status_code=201)
def create(body: RecipeIn, db: Session = Depends(get_db)):
    try:
        return rc.save(db, name=body.name, ingredients=_lines(body), servings=body.servings,
                       cooked_weight_g=body.cooked_weight_g, aliases=body.aliases, notes=body.notes)
    except mf.FoodError as e:
        db.rollback()
        _fail(e)


@router.put("/{recipe_id}")
def update(recipe_id: int, body: RecipeIn, db: Session = Depends(get_db)):
    r = db.get(Recipe, recipe_id)
    if not r:
        raise HTTPException(404, "recipe not found")
    try:
        return rc.save(db, name=body.name, ingredients=_lines(body), servings=body.servings,
                       cooked_weight_g=body.cooked_weight_g, aliases=body.aliases, notes=body.notes, existing=r)
    except mf.FoodError as e:
        db.rollback()
        _fail(e)


@router.delete("/{recipe_id}", status_code=204)
def remove(recipe_id: int, db: Session = Depends(get_db)):
    if not rc.delete(db, recipe_id):
        raise HTTPException(404, "recipe not found")
