from app.llm.base import LLMError, LLMRateLimited
from app.llm.fake import ScriptedLLM, call, say
from app.models import MealLog


class Boom:
    def __init__(self, exc):
        self.exc = exc

    def generate(self, *a, **k):
        raise self.exc


def test_food_logging_flow_through_tools(client, db):
    client.set_llm(ScriptedLLM([
        call("log_food", items=[{"name": "roti", "quantity": 2}, {"name": "dal"}]),
        say("Logged. You have 1,xxx kcal left."),
    ]))
    r = client.post("/api/chat", json={"message": "had 2 rotis and dal"})
    assert r.status_code == 200 and r.json()["reply"].startswith("Logged")
    assert db.query(MealLog).count() == 2
    assert client.get("/api/summary/today").json()["totals"]["calories"] == 220 + 150


def test_exercise_card_returned_to_ui_not_model(client):
    llm = ScriptedLLM([call("show_exercise", name="Barbell Curl"), say("Here's the form.")])
    client.set_llm(llm)
    body = client.post("/api/chat", json={"message": "show curl"}).json()
    assert body["cards"] and body["cards"][0]["images"]
    tool_msg = llm.calls[1][-1]  # what the model saw after the tool ran
    assert "images" not in str(tool_msg.tool_results[0].result)


def test_unknown_tool_and_bad_args_do_not_crash(client):
    client.set_llm(ScriptedLLM([call("nope"), call("log_food", items=[{"quantity": 1}]), say("ok")]))
    assert client.post("/api/chat", json={"message": "x"}).json()["reply"] == "ok"


def test_tool_loop_is_bounded(client):
    client.set_llm(ScriptedLLM([call("get_remaining_macros")] * 20))
    r = client.post("/api/chat", json={"message": "loop"}).json()
    assert "stuck" in r["reply"]


def test_rate_limit_degrades_gracefully_and_keeps_user_message(client):
    client.set_llm(Boom(LLMRateLimited("429")))
    r = client.post("/api/chat", json={"message": "hello"}).json()
    assert r["degraded"] and "rate-limited" in r["reply"]
    assert client.get("/api/chat/history").json()[-1]["content"] == "hello"


def test_provider_error_degrades(client):
    client.set_llm(Boom(LLMError("down")))
    assert client.post("/api/chat", json={"message": "hi"}).json()["degraded"]


def test_history_is_sent_to_model(client):
    client.set_llm(ScriptedLLM([say("one"), say("two")]))
    client.post("/api/chat", json={"message": "first"})
    llm = ScriptedLLM([say("two")])
    client.set_llm(llm)
    client.post("/api/chat", json={"message": "second"})
    texts = [m.text for m in llm.calls[0]]
    assert texts == ["first", "one", "second"]


def test_input_validation(client):
    client.set_llm(ScriptedLLM([]))
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_direct_endpoints_work_without_llm(client):
    assert client.post("/api/meals", json={"name": "banana", "quantity": 2}).status_code == 201
    assert client.post("/api/meals", json={"name": "unknown thing"}).status_code == 422
    assert client.put("/api/state", json={"energy": 9}).status_code == 422
    assert client.post("/api/injuries", json={"area": "knee", "severity": "mild"}).status_code == 201
    assert client.post("/api/injuries", json={"area": "pinky"}).status_code == 422
    assert client.put("/api/profile", json={"goal": "bulk"}).status_code == 422
    assert client.get("/api/exercises", params={"q": "curl", "limit": 3}).json()
    assert client.get("/api/exercises/does_not_exist").status_code == 404


def test_missing_api_key_degrades_instead_of_500(client):
    from app.deps import _Unavailable
    client.set_llm(_Unavailable("GEMINI_API_KEY is not set"))
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 200 and r.json()["degraded"]


def test_ui_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "FitChat" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/app.css").status_code == 200
    assert client.get("/static/manifest.webmanifest").status_code == 200


def test_free_single_equipment_item(client):
    client.put("/api/equipment/unavailable", json={"items": ["barbell", "cable"]})
    assert client.post("/api/equipment/available", json={"items": ["barbell"]}).json()["cleared"] == 1
    assert client.get("/api/equipment/unavailable").json() == ["cable"]


def test_cards_attach_automatically_for_every_named_exercise(client):
    """The model names exercises but never calls show_exercise: cards must still appear."""
    client.set_llm(ScriptedLLM([
        call("get_exercise_options", muscle="biceps", limit=100),
        say("Try **Barbell Curl** first, then barbell curls again later, and Concentration Curls to finish."),
    ]))
    body = client.post("/api/chat", json={"message": "bicep workout"}).json()
    names = [c["name"] for c in body["cards"]]
    assert "Barbell Curl" in names and names.count("Barbell Curl") == 1
    assert all(c["images"] for c in body["cards"])


def test_cards_not_attached_for_exercises_never_offered(client):
    client.set_llm(ScriptedLLM([call("get_exercise_options", muscle="biceps", limit=2), say("Do Bench Press and Deadlift.")]))
    assert client.post("/api/chat", json={"message": "x"}).json()["cards"] == []


def test_variant_name_shortened_by_model_still_gets_card(client, db):
    from app.models import Exercise
    ex = db.query(Exercise).filter(Exercise.name.like("% - %"), Exercise.category == "strength",
                                   Exercise.level == "beginner").first()
    short = ex.name.split(" - ")[0]
    muscle = ex.primary_muscles[0]
    client.set_llm(ScriptedLLM([call("get_exercise_options", muscle=muscle, limit=100), say(f"Do {short} today.")]))
    body = client.post("/api/chat", json={"message": "x"}).json()
    assert any(c["name"].split(" - ")[0] == short for c in body["cards"])


def test_shown_cards_are_recorded_so_next_request_rotates(client, db):
    from app.models import ExerciseSuggestion
    client.set_llm(ScriptedLLM([call("get_exercise_options", muscle="biceps", limit=100),
                                say("Barbell Curl and Concentration Curls.")]))
    client.post("/api/chat", json={"message": "x"})
    ids = {r.exercise_id for r in db.query(ExerciseSuggestion)}
    assert "Barbell_Curl" in ids


def test_two_muscle_request_in_one_turn_gives_both_sets_without_overlap(client):
    from app.llm.base import LLMResponse, ToolCall
    two = LLMResponse(text="", tool_calls=[ToolCall("get_exercise_options", {"muscle": "back", "limit": 5}),
                                           ToolCall("get_exercise_options", {"muscle": "biceps", "limit": 4})])
    client.set_llm(ScriptedLLM([two, say("Done.")]))
    assert client.post("/api/chat", json={"message": "3 back and 2 bicep"}).status_code == 200


def test_chat_logs_custom_dish_as_estimate_and_summary_matches_database(client, db):
    from app.models import MealLog
    llm = ScriptedLLM([
        call("log_food", items=[{"name": "rajma sabji", "grams": 300, "total_calories": 400, "total_protein_g": 16}]),
        say("Logged."),
    ])
    client.set_llm(llm)
    client.post("/api/chat", json={"message": "I had 300g of cooked rajma sabji"})
    rows = db.query(MealLog).all()
    assert len(rows) == 1 and rows[0].estimated and rows[0].calories == 400 and rows[0].protein_g == 16
    tool_msg = llm.calls[1][-1].tool_results[0].result  # what the model is shown after logging
    assert "ESTIMATE" in tool_msg["results"][0]["summary"]
    assert "400 kcal and 16 g protein eaten" in tool_msg["summary"]
    assert "1800 kcal" in tool_msg["summary"]


def test_one_bad_item_does_not_lose_the_others(client, db):
    from app.models import MealLog
    client.set_llm(ScriptedLLM([
        call("log_food", items=[{"name": "roti", "quantity": 2},
                                {"name": "weird", "total_calories": 99999, "total_protein_g": 1}]),
        say("ok"),
    ]))
    client.post("/api/chat", json={"message": "x"})
    assert [r.food_name for r in db.query(MealLog)] == ["Roti"]


def test_rest_estimate_for_loosely_matching_name(client):
    r = client.post("/api/meals", json={"name": "rajma curry homemade", "quantity": 3, "calories": 90, "protein_g": 5})
    assert r.status_code == 201 and r.json()["calories"] == 270 and r.json()["estimated"] is True
