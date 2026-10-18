import logging
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..llm.base import LLMClient, LLMError, LLMRateLimited, Message, ToolResult
from ..models import ChatMessage, Exercise
from ..tools import registry
from . import workouts as wk
from .nutrition import get_profile
from .. import clock

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the coach inside a personal food + gym tracking app used on a phone. Be concise, \
practical and friendly; short paragraphs, no long essays. Today is {today}. User goal: {goal}; targets: \
{cal} kcal, {prot} g protein.

Rules:
- NEVER do nutrition arithmetic or remember state yourself. Use the tools; quote the numbers they return.
- When the user says they ate something, call log_food. The app has a built-in per-100 g ingredient table and does \
the arithmetic, so give it WEIGHTS, not calorie guesses: a plain food with a weight or count (300 g cooked rajma, \
2 eggs) -> name + grams or quantity; a dish from the food table -> quantity in servings (2 rotis -> 2); a home-made \
or mixed dish -> 'ingredients' (a list of name + grams pairs) for the portion eaten, including cooking oil (1 tsp = 5 g, \
1 tbsp = 14 g). Read the user's words carefully: "300 g rajma" is the cooked beans, "300 g rajma sabji" is a curry \
with gravy, so only part of that weight is beans. If you must assume a split, say the assumption in one short line \
so they can correct it. Use total_calories/total_protein_g only when something is missing from the ingredient table \
(lookup_nutrition shows what exists). After logging, state the numbers exactly as written in the tool result \
'summary' fields; never state figures of your own for what was logged or what is left, and mention when something \
is an estimate. For "how much protein/calories in X" questions use lookup_nutrition.
- For "what should I eat", call get_remaining_macros / suggest_next_food, then suggest concrete options that fit.
- For workouts, call get_today_overview first, then get_exercise_options once per muscle group asked about \
(it also accepts: back, arms, legs, abs). If the user wants N exercises, request limit = N + 2 and recommend \
exactly N of the returned options. Use the exact exercise names returned. Recommend ONLY exercises from the \
latest tool results; the tool already rotates exercises between requests, so never reuse earlier suggestions \
on purpose and never invent names. Honour injuries, unavailable equipment and readiness, and say briefly why \
alternatives were skipped. Form pictures are attached automatically for every listed exercise you name, so do \
not call show_exercise for those; use it only when the user asks to see the form of a specific exercise. \
Add 1-2 short form cues per exercise in text. When an option has last_time, say what they did last time and \
the next_hint (it is computed for them; quote the weights exactly). After log_workout, congratulate any entry \
in prs using its text exactly. For progress questions use get_exercise_progress. For 'how was my week' or 'am I on track' call \
get_weekly_summary and quote its summary; when the user states their bodyweight call log_weight. Never judge \
weight change from a single day; say the trend over weeks matters. Water: call log_water. Stool: call log_stool \
with the Bristol type (ask if unclear). For digestion, constipation or fibre questions call get_digestion_status and \
quote its hints; remind that fibre should rise gradually with more water. Fibre is in the remaining numbers too. \
Meal plan: for 'what should I eat now / rest of the day' call plan_rest_of_day and relay its summary and notes; for 'something else' call it again with exclude set to the foods it suggested. Do not invent numbers.\n\
Body and extras: waist/chest/arm/thigh/hips in cm → log_measurements; 'how is my body changing' → get_body_progress; sleep hours or steps → log_sleep_steps; 'how is my winter arc' → get_winter_arc and quote its summary (the end-weight figure is an estimate, say so). Week plan: 'plan my week / grocery list' → plan_week (short overview, then the list only if asked); 'what do I need to buy' → get_grocery_list. Photos can only be added in the app (Progress tab).\n\
Routines: for 'what should I train today' call list_routines, recommend the suggested one, then get_routine_plan \
and tell them about any blocked exercise (say why) and offer one of its alternatives; they start it from the Workout \
screen. To make a workout for them call create_routine. Recipes: when the user describes how they cook a dish (ingredients and amounts), call analyze_recipe, show the \
per-serving numbers and any assumptions (raw vs cooked) in two or three lines, confirm how many servings it makes \
(and the finished weight if they know it), then save_recipe and log the portion with log_food. Saved recipes are \
logged by name. Never estimate recipe nutrition yourself. Never diagnose; for blood, black stool, severe pain or symptoms lasting over two weeks, advise seeing a doctor.
- Food and gym are linked: use today's macros and training status when advising (e.g. protein left after a training \
session, lighter volume on a low-readiness day). Do not tell the user to eat very little to compensate for a big meal.
- Offer stretching (category 'stretching') after workouts or when asked.
- You are not a doctor. For sharp, persistent or worsening pain, or any medical question, advise seeing a doctor or \
physiotherapist. Do not diagnose.
- If a tool returns an error, tell the user plainly and ask for what is missing."""


def attach_mentioned_cards(db: Session, reply: str, candidates: list[dict], cards: list[dict], max_cards: int = 6) -> None:
    """Add a form card for every offered exercise the reply names, so pictures never depend on the model
    remembering to ask for them. Matches the full name first, then the part before ' - ' (the grip/variant)."""
    text = f" {wk.norm_text(reply)} "
    have = {c.get("id") for c in cards}
    full_hits, base_hits = [], []
    for c in candidates:
        if c["id"] in have:
            continue
        full = wk.norm_text(c["name"])
        if full and f" {full} " in text:
            full_hits.append((text.index(f" {full} "), c))
            continue
        base = wk.norm_text(c["name"].split(" - ")[0])
        if base and f" {base} " in text:
            base_hits.append((text.index(f" {base} "), base, c))
    added = 0
    used_bases = {wk.norm_text(c["name"].split(" - ")[0]) for _, c in full_hits}
    ordered = [(pos, c) for pos, c in full_hits]
    for pos, base, c in sorted(base_hits, key=lambda x: x[0]):
        if base in used_bases:
            continue
        used_bases.add(base)
        ordered.append((pos, c))
    for _, c in sorted(ordered, key=lambda x: x[0]):
        if added >= max_cards:
            break
        ex = db.get(Exercise, c["id"])
        if ex and ex.id not in have:
            cards.append(wk.exercise_card(ex))
            have.add(ex.id)
            added += 1


@dataclass
class ChatResult:
    reply: str
    cards: list[dict] = field(default_factory=list)
    degraded: bool = False


def _history(db: Session, n: int) -> list[Message]:
    rows = db.scalars(select(ChatMessage).order_by(ChatMessage.id.desc()).limit(n)).all()
    return [Message(role=r.role, text=r.content) for r in reversed(rows)]


def run_chat(db: Session, llm: LLMClient, user_text: str) -> ChatResult:
    s = get_settings()
    p = get_profile(db)
    system = SYSTEM_PROMPT.format(today=clock.today().isoformat(), goal=p.goal.replace("_", " "),
                                  cal=int(p.calorie_target), prot=int(p.protein_target_g))
    messages = _history(db, s.history_messages) + [Message(role="user", text=user_text)]
    db.add(ChatMessage(role="user", content=user_text))
    db.commit()  # keep the user's message even if the model fails

    cards: list[dict] = []
    candidates: list[dict] = []
    reply = ""
    try:
        for _ in range(s.max_tool_rounds):
            resp = llm.generate(system, messages, registry.specs())
            if not resp.tool_calls:
                reply = resp.text
                break
            messages.append(Message(role="assistant", text=resp.text, tool_calls=resp.tool_calls, raw=resp.raw))
            results = []
            for tc in resp.tool_calls:
                result, card = registry.execute(db, tc.name, tc.args)
                if tc.name == "get_exercise_options":
                    candidates.extend(result.get("options", []))
                results.append(ToolResult(name=tc.name, result=result))
                if card and card not in cards:
                    cards.append(card)
            messages.append(Message(role="tool", tool_results=results))
        else:
            reply = "I got stuck working that out. Your entries are saved, so try asking again in a simpler way."
    except LLMRateLimited:
        log.warning("LLM rate limited")
        return ChatResult("The AI is rate-limited right now (free-tier limit). Anything already logged is saved; "
                          "try again in a minute.", cards, degraded=True)
    except LLMError as e:
        log.error("LLM error: %s", e)
        return ChatResult("I couldn't reach the AI model. Anything already logged is saved.", cards, degraded=True)

    reply = reply or "I couldn't produce a reply. Try rephrasing."
    if candidates:
        attach_mentioned_cards(db, reply, candidates, cards)
    shown = [c["id"] for c in cards if c.get("type") == "exercise"]
    if shown:
        wk.record_suggestions(db, shown)
    db.add(ChatMessage(role="assistant", content=reply))
    db.commit()
    return ChatResult(reply, cards)
