"""Nutrition from the built-in per-100 g table. All arithmetic happens here, never in the language model."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Ingredient
from .textmatch import closest, match_named, tokens

MAX_GRAMS = 5000


DRY_WORDS = {"dry", "dried", "raw", "uncooked"}
COOKED_WORDS = {"cooked", "boiled", "steamed", "fried", "roasted", "grilled", "soaked", "sauteed"}
# Words that describe preparation or size but do not change which ingredient is meant.
FILLER = {"cooked", "boiled", "fresh", "plain", "grilled", "roasted", "steamed", "whole", "piece", "pieces", "small",
          "medium", "large", "big", "of", "some", "the", "a", "an", "with", "home", "made", "homemade", "g", "gm",
          "gram", "grams"} | DRY_WORDS


def _is_dry(row: Ingredient) -> bool:
    return ", dry" in row.name or ", raw" in row.name


def _row_words(row: Ingredient) -> set[str]:
    words: set[str] = set()
    for n in [row.name, *(row.aliases or [])]:
        words |= set(tokens(n))
    return words


def match_ingredient(db: Session, name: str) -> tuple[Ingredient | None, str]:
    """Exact name/alias first. Otherwise a whole-word match that (a) prefers cooked rows unless the user said
    dry/raw/uncooked, (b) never picks a dry row unless asked, and (c) refuses names with extra food words
    ('chicken biryani' is not 'chicken'), because guessing a different food is worse than asking."""
    rows = db.scalars(select(Ingredient)).all()
    best, quality = match_named(rows, name)
    if quality == "exact":
        return best, quality
    qt = set(tokens(name))
    wants_dry = bool(DRY_WORDS & qt)
    row, q = match_named([r for r in rows if _is_dry(r) == wants_dry], name)
    if row is None and best is not None and (wants_dry or not _is_dry(best)):
        row, q = best, quality
    if row is None:
        return None, "none"
    extra = {t for t in qt - _row_words(row) - FILLER if not t.isdigit()}
    if extra:
        return None, "none"
    return row, q


def _grams_for(ing: Ingredient, grams, quantity) -> tuple[float | None, str | None]:
    """Weight in grams for an ingredient line, from an explicit weight or a count of countable pieces."""
    if grams is not None and float(grams) > 0:
        return float(grams), None
    if quantity is not None and float(quantity) > 0 and ing.serving_g:
        return round(float(quantity) * ing.serving_g, 1), None
    if quantity is not None and float(quantity) > 0:
        return None, (f"'{ing.name}' has no standard piece size, so give its weight in grams.")
    return None, f"Give a weight in grams for '{ing.name}'."


def scale(ing: Ingredient, grams: float) -> dict:
    f = grams / 100.0
    return {"calories": round(ing.calories_100g * f, 1), "protein_g": round(ing.protein_100g * f, 1),
            "carbs_g": round(ing.carbs_100g * f, 1), "fat_g": round(ing.fat_100g * f, 1),
            "fibre_g": round((ing.fibre_100g or 0) * f, 1)}


def per_100g(ing: Ingredient) -> dict:
    return {"calories": ing.calories_100g, "protein_g": ing.protein_100g,
            "carbs_g": ing.carbs_100g, "fat_g": ing.fat_100g, "fibre_g": ing.fibre_100g or 0}


def lookup(db: Session, items: list[dict]) -> dict:
    """items: [{name, grams?, quantity?}]. Returns per-100 g values and, when an amount is given, the amount's values."""
    all_rows = db.scalars(select(Ingredient)).all()
    out, total = [], {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fibre_g": 0.0}
    for it in items:
        name = str(it.get("name", "")).strip()
        ing, quality = match_named(all_rows, name)
        if not ing:
            out.append({"name": name, "found": False, "did_you_mean": closest(all_rows, name),
                        "note": "Not in the ingredient table. Use a listed name, or log with your own totals."})
            continue
        row = {"name": name, "found": True, "matched_as": ing.name, "match": quality, "per_100g": per_100g(ing)}
        if it.get("grams") is not None or it.get("quantity") is not None:
            g, err = _grams_for(ing, it.get("grams"), it.get("quantity"))
            if err:
                row["note"] = err
            else:
                row["grams"] = g
                row["amount"] = scale(ing, g)
                for k in total:
                    total[k] += row["amount"][k]
        out.append(row)
    return {"items": out, "total": {k: round(v, 1) for k, v in total.items()}}


# Spices and flavourings that add almost nothing: ignored (and listed as ignored) when small and not in the table.
NEGLIGIBLE = {"salt", "namak", "turmeric", "haldi", "chilli", "chili", "mirch", "masala", "garam", "jeera", "cumin",
              "coriander", "dhania", "hing", "asafoetida", "pepper", "cardamom", "elaichi", "clove", "cinnamon",
              "bay", "curry", "mustard", "ginger", "garlic", "lemon", "lime", "water", "kasuri", "methi", "ajwain",
              "paprika", "oregano", "spice", "spices", "powder", "leaves", "leaf", "pinch"}
NEGLIGIBLE_MAX_G = 15.0

ML_PER_UNIT = {"ml": 1.0, "l": 1000.0, "litre": 1000.0, "liter": 1000.0, "tsp": 4.93, "teaspoon": 4.93,
               "tbsp": 14.79, "tablespoon": 14.79, "cup": 240.0, "glass": 250.0, "katori": 150.0, "bowl": 250.0}
GRAM_UNITS = {"g": 1.0, "gm": 1.0, "gram": 1.0, "grams": 1.0, "kg": 1000.0}
PIECE_UNITS = {"piece", "pieces", "pc", "pcs", "nos", "no", "count", "whole", "scoop", "slice", "slices", "egg", "eggs"}
# grams per millilitre, matched against the ingredient's table name (first hit wins). Volume units are only converted
# for ingredients listed here; otherwise the caller must give grams, because guessing a cup of something is how
# recipe calories go wrong.
DENSITY = [("peanut butter", 1.07), ("oil", 0.91), ("ghee", 0.91), ("butter", 0.96), ("milk", 1.03), ("curd", 1.03),
           ("yogurt", 1.03), ("honey", 1.4), ("sugar", 0.85), ("besan", 0.42), ("flour", 0.5), ("atta", 0.5),
           ("sooji", 0.7), ("semolina", 0.7), ("oats", 0.36), ("rice, dry", 0.8), ("rice, cooked", 0.65),
           ("dal, boiled", 0.95), ("dal", 0.83), ("rajma, dry", 0.8), ("chickpeas, dry", 0.8), ("moong, dry", 0.85),
           ("peanuts", 0.6), ("almonds", 0.6), ("cashews", 0.55), ("walnuts", 0.45), ("chia", 0.65), ("flax", 0.6),
           ("whey", 0.45), ("poha", 0.3), ("sattu", 0.55), ("coconut", 0.4)]


def _density(ing: Ingredient) -> float | None:
    n = ing.name.lower()
    for needle, d in DENSITY:
        if needle in n:
            return d
    return None


def to_grams(ing: Ingredient | None, line: dict, name: str = "") -> tuple[float | None, str | None]:
    """Weight in grams for an ingredient line: {grams} | {amount, unit} | {quantity} (countable pieces).
    Volume units (tsp, tbsp, cup, ml...) are converted only for ingredients with a known density."""
    label = ing.name if ing else name
    if line.get("grams") is not None and float(line["grams"]) > 0:
        return float(line["grams"]), None
    amount, unit = line.get("amount"), str(line.get("unit") or "").strip().lower().rstrip(".")
    if amount is None and line.get("quantity") is not None:
        amount, unit = line["quantity"], unit or "piece"
    if amount is None or float(amount) <= 0:
        return None, f"Give an amount for '{label}'."
    amount = float(amount)
    if unit in GRAM_UNITS:
        return round(amount * GRAM_UNITS[unit], 1), None
    if unit in PIECE_UNITS or not unit:
        if ing is not None and ing.serving_g:
            return round(amount * ing.serving_g, 1), None
        return None, f"'{label}' has no standard piece size, so give its weight in grams."
    if unit in ML_PER_UNIT:
        d = _density(ing) if ing is not None else 1.0
        if d is None:
            return None, (f"I don't know how much a {unit} of '{label}' weighs. Give its weight in grams "
                          "(a kitchen scale, or the pack's serving size).")
        return round(amount * ML_PER_UNIT[unit] * d, 1), None
    return None, f"Unknown unit '{unit}' for '{label}'. Use g, kg, ml, tsp, tbsp, cup, glass, katori or pieces."


def _loose_grams(line: dict) -> float | None:
    """Rough grams for a spice line (1 g per ml, a pinch is half a gram). None when no amount was given."""
    if line.get("grams") is not None:
        return float(line["grams"])
    amount, unit = line.get("amount"), str(line.get("unit") or "").strip().lower()
    if amount is None:
        return None
    amount = float(amount)
    if unit in GRAM_UNITS:
        return amount * GRAM_UNITS[unit]
    if unit in ML_PER_UNIT:
        return amount * ML_PER_UNIT[unit]
    return amount * 0.5 if unit == "pinch" else amount * 3.0


def resolve(rows: list[Ingredient], name: str, raw_default: bool = False) -> dict:
    """Pick the table row for a typed ingredient name. In recipe mode (raw_default) a bare name means the raw/dry
    weight, because recipes list what goes into the pot; saying 'cooked'/'boiled' picks the cooked row.
    Returns {row, quality, note, candidates}. Ambiguous names return candidates instead of guessing."""
    qt = set(tokens(name))
    if raw_default and not (COOKED_WORDS & qt):
        pool = [r for r in rows if _is_dry(r)]
        base = qt - DRY_WORDS
        primary = [r for r in pool if set(tokens(r.name)) - DRY_WORDS == base]  # 'rice' is 'Rice, dry', not 'Poha, dry'
        row, q = (primary[0], "exact") if len(primary) == 1 else match_named(pool, name)
        if row is not None and not {t for t in qt - _row_words(row) - FILLER if not t.isdigit()}:
            assumed = not (DRY_WORDS & qt)
            return {"row": row, "quality": q, "candidates": [],
                    "note": f"assumed the raw/dry weight of '{name}'. Say 'cooked {name}' if it was already cooked." if assumed else ""}
        cands = [r.name for r in pool if any(set(tokens(n)) and (set(tokens(n)) <= qt or qt <= set(tokens(n)))
                                             for n in [r.name, *(r.aliases or [])]) and qt]
        if len(cands) > 1:
            return {"row": None, "quality": "none", "candidates": cands, "note": ""}
    best, quality = match_named(rows, name)
    if quality != "exact":
        wants_dry = bool(DRY_WORDS & qt)
        row, q = match_named([r for r in rows if _is_dry(r) == wants_dry], name)
        if row is None and best is not None and (wants_dry or not _is_dry(best)):
            row, q = best, quality
        best, quality = row, q
        if best is not None and {t for t in qt - _row_words(best) - FILLER if not t.isdigit()}:
            best, quality = None, "none"
    if best is None:
        return {"row": None, "quality": "none", "candidates": [], "note": ""}
    note = ""
    if raw_default and not (COOKED_WORDS & qt) and not _is_dry(best) and any(w in best.name.lower() for w in ("cooked", "boiled")):
        note = f"the table only has the cooked value for '{best.name}'; if you weighed it raw the numbers run a little high."
    return {"row": best, "quality": quality, "candidates": [], "note": note}


def compose_ex(db: Session, parts: list[dict], raw_default: bool = False) -> dict:
    """Sum a dish from ingredient lines [{name, grams | amount+unit | quantity}]. Returns
    {totals, lines, ignored, problems, assumptions}. Any problem means nothing should be logged or saved."""
    rows = db.scalars(select(Ingredient)).all()
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fibre_g": 0.0}
    lines, ignored, problems, notes = [], [], [], []
    for it in parts:
        name = str(it.get("name", "")).strip()
        if not name:
            problems.append("An ingredient line has no name.")
            continue
        nt = set(tokens(name))
        if nt and all(t in NEGLIGIBLE or t in FILLER or t.isdigit() for t in nt) and nt & NEGLIGIBLE:
            g = _loose_grams(it)
            if "water" in nt or g is None or g <= NEGLIGIBLE_MAX_G:
                ignored.append({"name": name, "reason": "no calories" if "water" in nt else "tiny amount of spice/flavouring, counted as zero"})
                continue
        res = resolve(rows, name, raw_default)
        ing = res["row"]
        if ing is None:
            if res["candidates"]:
                problems.append(f"'{name}' could be {', '.join(res['candidates'])}. Say which one, or say 'cooked {name}' "
                                "if it was already cooked.")
                continue
            if set(tokens(name)) & NEGLIGIBLE:
                g = _loose_grams(it)
                if g is None or g <= NEGLIGIBLE_MAX_G:
                    ignored.append({"name": name, "reason": "tiny amount of spice/flavouring, counted as zero"})
                    continue
            hint = closest(rows, name)
            problems.append(f"'{name}' is not in the ingredient table" + (f" (did you mean: {', '.join(hint)}?)" if hint else "") + ".")
            continue
        g, err = to_grams(ing, it, name)
        if err:
            problems.append(err)
            continue
        if g > MAX_GRAMS:
            problems.append(f"{g:g} g of '{ing.name}' looks wrong; check the units.")
            continue
        vals = scale(ing, g)
        for k in totals:
            totals[k] += vals[k]
        line = {"input": name, "ingredient": ing.name, "grams": g, "match": res["quality"], "note": res["note"], **vals}
        lines.append(line)
        if res["note"]:
            notes.append(f"{name}: {res['note']}")
    out = {"lines": lines, "ignored": ignored, "problems": problems, "assumptions": notes}
    out["totals"] = None if problems else {k: round(v, 1) for k, v in totals.items()}
    return out


def compose(db: Session, parts: list[dict], raw_default: bool = False) -> tuple[dict | None, list[dict], list[str]]:
    r = compose_ex(db, parts, raw_default)
    return r["totals"], r["lines"], r["problems"]
