"""Add, edit and delete your own foods; search Open Food Facts for packaged products."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Food, Ingredient
from ..services import myfoods as mf
from ..services import openfoodfacts as off

router = APIRouter(prefix="/api", tags=["my foods"])


class IngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    basis: Literal["100g", "serving"] = "100g"
    serving_g: float | None = Field(default=None, gt=0, le=5000)  # grams in one serving or piece
    serving_label: str | None = Field(default=None, max_length=40)
    calories: float = Field(ge=0, le=20000)
    protein_g: float = Field(ge=0, le=2000)
    carbs_g: float = Field(default=0, ge=0, le=2000)
    fat_g: float = Field(default=0, ge=0, le=2000)
    fibre_g: float = Field(default=0, ge=0, le=2000)
    source: Literal["user", "openfoodfacts"] = "user"


class DishIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=10)
    serving: str = Field(min_length=1, max_length=60)  # e.g. "1 katori" or "1 plate"
    calories: float = Field(ge=0, le=20000)
    protein_g: float = Field(ge=0, le=2000)
    carbs_g: float = Field(default=0, ge=0, le=2000)
    fat_g: float = Field(default=0, ge=0, le=2000)
    fibre_g: float = Field(default=0, ge=0, le=2000)


def ingredient_json(i: Ingredient, warnings: list[str] | None = None) -> dict:
    return {"id": i.id, "name": i.name, "aliases": i.aliases, "calories_100g": i.calories_100g,
            "protein_100g": i.protein_100g, "carbs_100g": i.carbs_100g, "fat_100g": i.fat_100g,
            "fibre_100g": i.fibre_100g or 0, "serving_g": i.serving_g, "serving_label": i.serving_label, "source": i.source,
            "warnings": warnings or []}


def dish_json(f: Food) -> dict:
    return {"id": f.id, "name": f.name, "aliases": f.aliases, "serving": f.serving, "calories": f.calories,
            "protein_g": f.protein_g, "carbs_g": f.carbs_g, "fat_g": f.fat_g, "fibre_g": f.fibre_g or 0,
            "source": f.source}


def _fail(e: mf.FoodError):
    raise HTTPException(409 if isinstance(e, (mf.NameTaken, mf.Protected)) else 422, str(e)) from e


def _save_ingredient(db: Session, body: IngredientIn, existing: Ingredient | None):
    try:
        row, warnings = mf.save_ingredient(
            db, name=body.name, aliases=body.aliases, serving_g=body.serving_g, serving_label=body.serving_label,
            values={"calories": body.calories, "protein_g": body.protein_g, "carbs_g": body.carbs_g, "fat_g": body.fat_g,
                    "fibre_g": body.fibre_g},
            per_serving=body.basis == "serving", source=body.source, existing=existing)
    except mf.FoodError as e:
        db.rollback()
        _fail(e)
    return ingredient_json(row, warnings)


@router.post("/ingredients", status_code=201)
def create_ingredient(body: IngredientIn, db: Session = Depends(get_db)):
    return _save_ingredient(db, body, None)


@router.put("/ingredients/{ingredient_id}")
def update_ingredient(ingredient_id: int, body: IngredientIn, db: Session = Depends(get_db)):
    row = db.get(Ingredient, ingredient_id)
    if not row:
        raise HTTPException(404, "food not found")
    return _save_ingredient(db, body, row)


@router.delete("/ingredients/{ingredient_id}", status_code=204)
def delete_ingredient(ingredient_id: int, db: Session = Depends(get_db)):
    row = db.get(Ingredient, ingredient_id)
    if not row:
        raise HTTPException(404, "food not found")
    try:
        mf.delete_row(db, row)
    except mf.FoodError as e:
        _fail(e)


@router.post("/foods", status_code=201)
def create_dish(body: DishIn, db: Session = Depends(get_db)):
    try:
        row = mf.save_dish(db, name=body.name, aliases=body.aliases, serving=body.serving, values=body.model_dump())
    except mf.FoodError as e:
        db.rollback()
        _fail(e)
    return dish_json(row)


@router.put("/foods/{food_id}")
def update_dish(food_id: int, body: DishIn, db: Session = Depends(get_db)):
    row = db.get(Food, food_id)
    if not row:
        raise HTTPException(404, "food not found")
    if row.source == "recipe":
        raise HTTPException(409, "This is a saved recipe. Edit it under Recipes so its ingredients and numbers stay in step.")
    try:
        row = mf.save_dish(db, name=body.name, aliases=body.aliases, serving=body.serving, values=body.model_dump(),
                           existing=row)
    except mf.FoodError as e:
        db.rollback()
        _fail(e)
    return dish_json(row)


@router.delete("/foods/{food_id}", status_code=204)
def delete_dish(food_id: int, db: Session = Depends(get_db)):
    row = db.get(Food, food_id)
    if not row:
        raise HTTPException(404, "food not found")
    if row.source == "recipe":
        from ..models import Recipe
        rec = db.query(Recipe).filter(Recipe.food_id == row.id).first()
        if rec:
            from ..services import recipes as rc
            rc.delete(db, rec.id)
            return
    try:
        mf.delete_row(db, row)
    except mf.FoodError as e:
        _fail(e)


@router.get("/online-foods")
def online_foods(q: str):
    try:
        results = off.search(q)
    except off.OnlineLookupError as e:
        raise HTTPException(502, str(e)) from e
    return {"results": results, "source": "Open Food Facts (community data; check against your pack)"}
