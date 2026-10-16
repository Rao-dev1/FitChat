import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Exercise, Food, Ingredient, Profile
from .fibre import FOOD_FIBRE_PER_SERVING, INGREDIENT_FIBRE_100G
from .foods import FOODS, RENAMED, VALUE_FIXES
from .ingredients import INGREDIENTS

EXERCISE_FILE = Path(__file__).resolve().parents[2] / "data" / "exercises.json"


def seed_all(db: Session) -> None:
    if not db.scalar(select(func.count()).select_from(Profile)):
        db.add(Profile())
    if not db.scalar(select(func.count()).select_from(Food)):
        for name, aliases, serving, kcal, p, c, f in FOODS:
            db.add(Food(name=name, aliases=aliases, serving=serving, calories=kcal,
                        protein_g=p, carbs_g=c, fat_g=f, source="seed_approx",
                        fibre_g=FOOD_FIBRE_PER_SERVING.get(name, 0)))
    if not db.scalar(select(func.count()).select_from(Exercise)) and EXERCISE_FILE.exists():
        for e in json.loads(EXERCISE_FILE.read_text(encoding="utf-8")):
            db.add(Exercise(
                id=e["id"], name=e["name"], category=e.get("category") or "strength",
                equipment=e.get("equipment"), level=e.get("level"), force=e.get("force"),
                mechanic=e.get("mechanic"), primary_muscles=e.get("primaryMuscles", []),
                secondary_muscles=e.get("secondaryMuscles", []),
                instructions=e.get("instructions", []), images=e.get("images", []),
            ))
    db.commit()
    # Keep the serving text (which carries the weight used for gram conversion) in sync for starter foods.
    # Only touches foods still marked as the untouched starter data; nutrition values are never changed.
    starter = {name: serving for name, _a, serving, *_ in FOODS}
    for f in db.scalars(select(Food).where(Food.source == "seed_approx")):
        if f.name in starter and f.serving != starter[f.name]:
            f.serving = starter[f.name]
    db.commit()
    for f in db.scalars(select(Food).where(Food.source == "seed_approx")):  # untouched starter rows follow the table
        f.fibre_g = FOOD_FIBRE_PER_SERVING.get(f.name, 0)
    db.commit()
    _sync_starter_names(db)
    _seed_ingredients(db)


def _sync_starter_names(db: Session) -> None:
    """Rename starter foods whose names changed (e.g. 'Rajma' is now 'Rajma curry') and refresh their aliases."""
    by_name = {f[0]: f for f in FOODS}
    for old, new in RENAMED.items():
        row = db.scalar(select(Food).where(Food.name == old, Food.source == "seed_approx"))
        if row and not db.scalar(select(Food).where(Food.name == new)):
            row.name = new
            row.aliases = list(by_name[new][1])
    for name, (kcal, protein, carbs, fat) in VALUE_FIXES.items():
        row = db.scalar(select(Food).where(Food.name == name, Food.source == "seed_approx"))
        if row:
            row.calories, row.protein_g, row.carbs_g, row.fat_g = kcal, protein, carbs, fat
    db.commit()


def _seed_ingredients(db: Session) -> None:
    """Add missing ingredients and refresh untouched ones (source 'seed_approx') from the bundled table.
    Rows you edited or added yourself (any other source) are never overwritten."""
    existing = {i.name: i for i in db.scalars(select(Ingredient))}
    for name, aliases, kcal, protein, carbs, fat, serving_g, serving_label in INGREDIENTS:
        row = existing.get(name)
        if row is None:
            db.add(Ingredient(name=name, aliases=aliases, calories_100g=kcal, protein_100g=protein, carbs_100g=carbs,
                              fat_100g=fat, serving_g=serving_g, serving_label=serving_label, source="seed_approx",
                              fibre_100g=INGREDIENT_FIBRE_100G.get(name, 0)))
        elif row.source == "seed_approx":
            row.aliases, row.calories_100g, row.protein_100g = aliases, kcal, protein
            row.carbs_100g, row.fat_100g, row.serving_g, row.serving_label = carbs, fat, serving_g, serving_label
            row.fibre_100g = INGREDIENT_FIBRE_100G.get(name, 0)
    db.commit()
