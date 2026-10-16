"""Whole-word, plural-insensitive name matching shared by the food and ingredient tables."""
import re


def stem(t: str) -> str:
    return t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t


def tokens(s: str) -> list[str]:
    return [stem(t) for t in re.split(r"[^a-z0-9]+", s.lower()) if t]


def norm(s: str) -> str:
    return " ".join(tokens(s))


def match_named(rows, name: str):
    """rows: objects with .name and .aliases. Returns (row, quality): 'exact' (the name or an alias, ignoring case,
    punctuation and plurals), 'loose' (all words of one contain the other, exactly one best candidate) or 'none'.
    Whole-word only ('dalia' never matches 'Dal'); ambiguous ties return none rather than guessing."""
    rows = list(rows)
    q = norm(name)
    if not q:
        return None, "none"
    for r in rows:
        if q in {norm(n) for n in [r.name, *(r.aliases or [])]}:
            return r, "exact"
    qt = set(q.split())
    scored = []
    for r in rows:
        best = 0
        for n in [r.name, *(r.aliases or [])]:
            nt = set(tokens(n))
            if nt and (nt <= qt or qt <= nt):
                best = max(best, len(nt & qt))
        if best:
            scored.append((best, r))
    if not scored:
        return None, "none"
    top = max(sc for sc, _ in scored)
    winners = [r for sc, r in scored if sc == top]
    return (winners[0], "loose") if len(winners) == 1 else (None, "none")


def closest(rows, name: str, limit: int = 5) -> list[str]:
    """Names that share at least one word with the query, best first. Used for 'did you mean' hints."""
    qt = set(tokens(name))
    out = []
    for r in rows:
        words = set()
        for n in [r.name, *(r.aliases or [])]:
            words |= set(tokens(n))
        hit = len(qt & words)
        if hit:
            out.append((-hit, r.name))
    return [n for _, n in sorted(out)[:limit]]
