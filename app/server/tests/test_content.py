from __future__ import annotations


def test_real_pack_is_loaded(client):
    data = client.get("/api/packs").json()
    ids = {p["id"]: p for p in data["items"]}
    assert "cam18-t3-p3" in ids
    assert data["errors"] == {}
    p = ids["cam18-t3-p3"]
    assert p["counts"] == {"sentences": 54, "questions": 14, "words": 462, "items": 0}
    assert p["meta"]["title"] == "The case for mixed-ability classes"


def test_detail_hides_answers_by_default(client):
    body = client.get("/api/packs/mini").json()
    item = body["questionGroups"][0]["items"][0]
    assert "answer" not in item
    assert body["counts"]["questions"] == 4

    with_answers = client.get("/api/packs/mini?answers=1").json()
    assert with_answers["questionGroups"][0]["items"][0]["answer"] == "A"


def test_group_keeps_shared_options_and_placeholders(client):
    body = client.get("/api/packs/cam18-t3-p3").json()
    summary = next(g for g in body["questionGroups"] if g["type"] == "summary")
    assert "{{31}}" in summary["text"]
    assert len(summary["options"]) == 9
    assert summary["from"] == 31 and summary["to"] == 35


def test_missing_pack(client):
    assert client.get("/api/packs/nope").status_code == 404


def test_reload(client):
    body = client.post("/api/packs/reload").json()
    assert body["loaded"] >= 2
    assert body["errors"] == {}


def test_delete_builtin_refused(client):
    assert client.delete("/api/packs/cam18-t3-p3").status_code == 400


def test_health_reports_packs(client):
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["dbVersion"] >= 1
    assert body["packs"]["errors"] == {}


def test_import_text_creates_custom_deck(client, tmp_path):
    text = "deposit,The landlord kept the deposit.,房东留下了押金。\n" \
           "refundable,The fee is refundable.,费用可退。"
    body = client.post("/api/packs/import", json={"name": "测试词表", "text": text})
    assert body.status_code == 200, body.text
    pid = body.json()["id"]
    assert body.json()["count"] == 2

    detail = client.get(f"/api/packs/{pid}").json()
    assert detail["kind"] == "deck"
    assert detail["items"][0]["word"] == "deposit"

    # 自定义包可删
    assert client.delete(f"/api/packs/{pid}").status_code == 200
    assert client.get(f"/api/packs/{pid}").status_code == 404
