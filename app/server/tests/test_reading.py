from __future__ import annotations


def _import_history(client, finished_at=1795000000):
    return client.post("/api/reading/history", json={
        "packId": "mini",
        "answers": {"1": "A", "2": "A", "3": "YES", "4": "NG"},
        "durationMs": 600_000,
        "finishedAt": finished_at,
    })


def test_history_import_scores_and_dates(client):
    body = _import_history(client).json()
    assert body["score"] == 3
    assert body["total"] == 4
    assert body["accuracy"] == 0.75

    overview = client.get("/api/stats/overview").json()
    assert overview["lastStudyAt"] == 1795000000
    assert overview["totals"]["readingQuestions"] == 4


def test_session_only_returns_requested_questions(client):
    body = client.post("/api/reading/sessions", json={"packId": "mini", "nos": [1, 2]}).json()
    groups = body["pack"]["questionGroups"]
    assert [g["id"] for g in groups] == ["mcq"]
    assert [q["no"] for q in groups[0]["items"]] == [1, 2]
    assert "answer" not in groups[0]["items"][0]


def test_submit_is_forgiving_about_case_and_blank_is_wrong(client):
    created = client.post("/api/reading/sessions", json={"packId": "mini"}).json()
    sid = created["sessionId"]
    body = client.post(f"/api/reading/sessions/{sid}/submit", json={
        "answers": {"1": "a", "2": "", "3": "yes", "4": "ng"},
        "durationMs": 120_000,
    }).json()
    assert body["score"] == 3
    assert [i["correct"] for i in body["items"]] == [True, False, True, True]
    assert body["pack"]["questionGroups"][0]["items"][0]["answer"] == "A"

    assert client.post(f"/api/reading/sessions/{sid}/submit", json={"answers": {}}).status_code == 409


def test_unknown_question_number(client):
    r = client.post("/api/reading/sessions", json={"packId": "mini", "nos": [99]})
    assert r.status_code == 400


def test_deck_pack_has_no_reading_questions(client):
    text = "deposit,The landlord kept the deposit.,房东留下了押金。"
    pid = client.post("/api/packs/import", json={"name": "deck only", "text": text}).json()["id"]
    r = client.post("/api/reading/sessions", json={"packId": pid})
    assert r.status_code == 400
    client.delete(f"/api/packs/{pid}")


def test_reading_sessions_listed(client):
    created = client.post("/api/reading/sessions", json={"packId": "mini"}).json()
    client.post(f"/api/reading/sessions/{created['sessionId']}/submit",
                json={"answers": {"1": "A"}})
    items = client.get("/api/reading/sessions").json()["items"]
    assert items[0]["packId"] == "mini"
    assert items[0]["total"] == 4
