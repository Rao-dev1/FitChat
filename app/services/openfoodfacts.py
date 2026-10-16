"""Search the free Open Food Facts database (community-maintained packaged-food data).
Needs internet on the laptop that runs the server. Values are per 100 g as printed on packs, so check them
against your pack. Nothing is saved until the user chooses a result."""
import httpx

SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
USER_AGENT = "FitChat/0.1 (personal food tracker, self-hosted)"
MAX_RESULTS = 10


class OnlineLookupError(Exception):
    """User-presentable failure (offline, rate limited, bad response)."""


def _fetch(params: dict) -> dict:
    r = httpx.get(SEARCH_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=10.0)
    r.raise_for_status()
    return r.json()


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN guard


def parse_products(payload: dict) -> list[dict]:
    out, seen = [], set()
    for p in (payload or {}).get("products") or []:
        n = p.get("nutriments") or {}
        kcal = _num(n.get("energy-kcal_100g"))
        if kcal is None:
            kj = _num(n.get("energy_100g"))
            kcal = round(kj / 4.184, 1) if kj is not None else None
        protein = _num(n.get("proteins_100g"))
        carbs, fat = _num(n.get("carbohydrates_100g")), _num(n.get("fat_100g"))
        name = (p.get("product_name") or "").strip()
        if not name or kcal is None or protein is None:
            continue
        carbs, fat = carbs or 0.0, fat or 0.0
        if not (0 <= kcal <= 900 and 0 <= protein <= 100 and 0 <= carbs <= 100 and 0 <= fat <= 100):
            continue
        if protein + carbs + fat > 100.5:
            continue
        brand = (p.get("brands") or "").split(",")[0].strip()
        key = (name.lower(), brand.lower())
        if key in seen:
            continue
        seen.add(key)
        sq = _num(p.get("serving_quantity"))
        out.append({
            "code": p.get("code"), "name": name[:80], "brand": brand,
            "calories_100g": round(kcal, 1), "protein_100g": round(protein, 1),
            "carbs_100g": round(carbs, 1), "fat_100g": round(fat, 1), "fibre_100g": round(_num(n.get("fiber_100g")) or 0.0, 1),
            "serving_g": sq if sq and 0 < sq <= 5000 else None,
            "serving_label": (p.get("serving_size") or "").strip()[:40] or None,
        })
        if len(out) >= MAX_RESULTS:
            break
    return out


def search(query: str, fetch=None) -> list[dict]:
    q = (query or "").strip()
    if len(q) < 2:
        raise OnlineLookupError("Type at least 2 letters to search.")
    params = {"search_terms": q, "search_simple": 1, "action": "process", "json": 1, "page_size": 25,
              "fields": "code,product_name,brands,nutriments,serving_size,serving_quantity"}
    try:
        payload = (fetch or _fetch)(params)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            raise OnlineLookupError("Open Food Facts is rate-limiting searches. Wait a minute and try again.") from e
        raise OnlineLookupError(f"Open Food Facts returned an error ({e.response.status_code}). Try again later.") from e
    except (httpx.HTTPError, ValueError) as e:
        raise OnlineLookupError("Could not reach Open Food Facts. Check that the laptop is online.") from e
    return parse_products(payload)
