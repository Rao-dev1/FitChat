"""Your own foods: add, edit and delete rows in the ingredient table (per 100 g) and the dish table (per serving).
Rows you add or edit are marked so the built-in data refresh never overwrites them."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Food, Ingredient
from .textmatch import norm

BUILTIN = "seed_approx"
USER_SOURCES = {"user", "openfoodfacts"}


class FoodError(ValueError):
    """A problem with what the user typed. The message is shown to them as is."""


class NameTaken(FoodError):
    pass


class Protected(FoodError):
    pass


def clean_text(s: str | None, label: str, max_len: int, required: bool = False) -> str | None:
    s = (s or "").strip()
    if not s:
        if required:
            raise FoodError(f"{label} is required.")
        return None
    if len(s) > max_len:
        raise FoodError(f"{label} is too long (max {max_len} characters).")
    return s


def clean_aliases(aliases: list[str] | None) -> list[str]:
    out: list[str] = []
    for a in aliases or []:
        a = (a or "").strip()
        if a and len(a) <= 40 and norm(a) not in {norm(x) for x in out}:
            out.append(a)
    if len(out) > 10:
        raise FoodError("Use at most 10 alternative names.")
    return out


def _current_norms(row) -> set[str]:
    return {norm(n) for n in [row.name, *(row.aliases or [])]} if row is not None else set()


def check_names_free(db: Session, names: list[str], existing=None) -> None:
    """New or changed names must not collide with any name or alias already used in either food table, because
    an ambiguous name would make logging pick the wrong row. Unchanged names of an existing row are fine."""
    wanted = {norm(n) for n in names if norm(n)} - _current_norms(existing)
    if not wanted:
        return
    for rows in (db.scalars(select(Ingredient)), db.scalars(select(Food))):
        for r in rows:
            if r is existing:
                continue
            clash = wanted & {norm(n) for n in [r.name, *(r.aliases or [])]}
            if clash:
                raise NameTaken(f"'{sorted(clash)[0]}' is already used by '{r.name}'. Pick a different name, or edit that one.")


def check_per_100g(calories: float, protein: float, carbs: float, fat: float) -> list[str]:
    """Hard limits that catch typing mistakes (per-serving numbers entered as per-100 g); returns soft warnings."""
    for label, v, hi in (("Calories", calories, 900), ("Protein", protein, 100), ("Carbs", carbs, 100), ("Fat", fat, 100)):
        if v < 0 or v > hi:
            raise FoodError(f"{label} per 100 g must be between 0 and {hi}. Entered values for a whole serving? "
                            "Switch to 'Per serving' and give its weight.")
    if protein + carbs + fat > 100.5:
        raise FoodError("Protein, carbs and fat together can't exceed 100 g per 100 g of food. "
                        "Check the numbers, or switch to 'Per serving'.")
    warnings = []
    expected = 4 * protein + 4 * carbs + 9 * fat
    if (carbs or fat) and abs(expected - calories) > max(60, 0.35 * calories):
        warnings.append(f"Calories ({calories:g}) don't match the macros (about {expected:g} expected). Saved anyway; "
                        "double-check the label.")
    return warnings


def to_per_100g(values: dict, serving_g: float) -> dict:
    if not serving_g or serving_g <= 0 or serving_g > 5000:
        raise FoodError("Give the weight of one serving in grams (1 to 5000).")
    k = 100.0 / serving_g
    return {key: round(v * k, 2) for key, v in values.items()}


def _fill_ingredient(row: Ingredient, name, aliases, vals, serving_g, serving_label) -> None:
    row.name, row.aliases = name, aliases
    row.calories_100g, row.protein_100g = vals["calories"], vals["protein_g"]
    row.carbs_100g, row.fat_100g = vals["carbs_g"], vals["fat_g"]
    row.fibre_100g = vals.get("fibre_g", 0)
    row.serving_g, row.serving_label = serving_g, serving_label


def save_ingredient(db: Session, *, name: str, aliases: list[str] | None, values: dict, serving_g: float | None,
                    serving_label: str | None, per_serving: bool, source: str = "user",
                    existing: Ingredient | None = None) -> tuple[Ingredient, list[str]]:
    name = clean_text(name, "Name", 80, required=True)
    aliases = clean_aliases(aliases)
    label = clean_text(serving_label, "Serving label", 40)
    vals = {k: float(values.get(k) or 0) for k in ("calories", "protein_g", "carbs_g", "fat_g", "fibre_g")}
    if per_serving:
        vals = to_per_100g(vals, serving_g)
    elif serving_g is not None and not 0 < serving_g <= 5000:
        raise FoodError("Piece weight must be between 0 and 5000 g.")
    if not 0 <= vals["fibre_g"] <= 100:
        raise FoodError("Fibre per 100 g must be between 0 and 100.")
    warnings = check_per_100g(vals["calories"], vals["protein_g"], vals["carbs_g"], vals["fat_g"])
    check_names_free(db, [name, *aliases], existing)
    if serving_g and not label:
        label = "1 serving"
    row = existing or Ingredient()
    _fill_ingredient(row, name, aliases, vals, serving_g, label if serving_g else None)
    if existing is None:
        row.source = source if source in USER_SOURCES else "user"
        db.add(row)
    elif row.source == BUILTIN:
        row.source = "user"  # edited by the user: the built-in refresh must leave it alone from now on
    db.commit()
    return row, warnings


def save_dish(db: Session, *, name: str, aliases: list[str] | None, serving: str, values: dict,
              existing: Food | None = None) -> Food:
    name = clean_text(name, "Name", 80, required=True)
    serving = clean_text(serving, "Serving", 60, required=True)
    aliases = clean_aliases(aliases)
    vals = {k: float(values.get(k) or 0) for k in ("calories", "protein_g", "carbs_g", "fat_g", "fibre_g")}
    for label, v, hi in (("Fibre", vals["fibre_g"], 200), ("Calories", vals["calories"], 5000), ("Protein", vals["protein_g"], 300),
                         ("Carbs", vals["carbs_g"], 500), ("Fat", vals["fat_g"], 500)):
        if v < 0 or v > hi:
            raise FoodError(f"{label} per serving must be between 0 and {hi}.")
    check_names_free(db, [name, *aliases], existing)
    row = existing or Food()
    row.name, row.aliases, row.serving = name, aliases, serving
    row.calories, row.protein_g, row.carbs_g, row.fat_g = (vals["calories"], vals["protein_g"], vals["carbs_g"],
                                                           vals["fat_g"])
    row.fibre_g = vals["fibre_g"]
    if existing is None:
        row.source = "user"
        db.add(row)
    elif row.source == BUILTIN:
        row.source = "user"
    db.commit()
    return row


def delete_row(db: Session, row) -> None:
    if row.source == BUILTIN:
        raise Protected("Built-in foods can't be deleted (they would come back on restart). "
                        "You can edit one to make it yours.")
    db.delete(row)
    db.commit()
