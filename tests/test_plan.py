from app.llm.fake import ScriptedLLM, call, say
from app.services import nutrition as nut


def test_plan_fills_day(client):
    r = client.get("/api/plan?hour=8").json()
    assert r["status"] == "plan" and len(r["slots"]) == 4
    for s in r["slots"]:
        assert s["totals"]["calories"] <= 900 and s["items"]
        assert all(i["servings"] <= 3 for i in s["items"])
    pd = r["projected_day"]
    assert abs(pd["calories"] - pd["calorie_target"]) < 0.15 * pd["calorie_target"]


def test_plan_only_remaining_slots(client):
    r = client.get("/api/plan?hour=17").json()
    assert [s["slot"] for s in r["slots"]] == ["snack", "dinner"]


def test_plan_over_target(client, db):
    nut.log_item(db, "Chicken curry", 12)
    r = client.get("/api/plan?hour=12").json()
    assert r["status"] == "over" and not r["slots"]


def test_plan_exclude_changes_foods(client):
    a = client.get("/api/plan?hour=17").json()
    names = [i["food"] for s in a["slots"] for i in s["items"]]
    b = client.get("/api/plan?hour=17", params={"exclude": names}).json()
    assert not set(names) & {i["food"] for s in b["slots"] for i in s["items"]}


def test_plan_late_night_nothing(client, db):
    nut.log_item(db, "Chicken curry", 6)
    r = client.get("/api/plan?hour=23").json()
    assert r["status"] in ("done", "over") or len(r["slots"]) <= 1


def test_coach_plan_tool(client):
    client.set_llm(ScriptedLLM([call("plan_rest_of_day"), say("ok")]))
    r = client.post("/api/chat", json={"message": "what should I eat for the rest of the day"})
    assert r.status_code == 200
