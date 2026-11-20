from __future__ import annotations

import time


def _add(client, lemma="deposit", **kw):
    payload = {"lemma": lemma, "word": kw.pop("word", lemma), "gloss": "押金",
               "pos": "n.", "source": "mini"}
    payload.update(kw)
    return client.post("/api/vocab", json=payload)


def test_add_and_case_insensitive_dedupe(client):
    first = _add(client).json()
    assert first["created"] is True
    assert first["item"]["due"] is True          # 新词立刻进复习队列
    assert first["item"]["state"] == "new"

    again = _add(client, lemma="Deposit", word="Deposit", gloss="不该覆盖", context={
        "packId": "mini", "sentenceId": "p1s1", "en": "The deposit is refundable.",
        "zh": "押金可退。"}).json()
    assert again["created"] is False
    assert again["item"]["gloss"] == "押金"
    assert len(again["item"]["contexts"]) == 1

    same = _add(client, lemma="deposit", context={
        "packId": "mini", "sentenceId": "p1s1", "en": "The deposit is refundable.",
        "zh": "押金可退。"}).json()
    assert len(same["item"]["contexts"]) == 1      # 同一句不重复追加


def test_contexts_merge_across_passages(client):
    _add(client, context={"packId": "mini", "sentenceId": "p1s1", "en": "The deposit is refundable."})
    merged = _add(client, context={"packId": "other", "sentenceId": "p9s1",
                                   "en": "A deposit was taken."}).json()
    assert len(merged["item"]["contexts"]) == 2


def test_review_progression(client):
    vid = _add(client).json()["item"]["id"]
    now = int(time.time())

    good = client.post(f"/api/vocab/{vid}/review", json={"grade": "good"}).json()
    assert good["state"] == "review"
    assert good["intervalDays"] == 1
    assert good["nextDueAt"] > now

    again = client.post(f"/api/vocab/{vid}/review", json={"grade": "again"}).json()
    assert again["state"] == "learning"
    assert again["nextDueAt"] <= now + 11 * 60

    item = again["item"]
    assert item["reps"] == 2
    assert item["lapses"] == 1
    assert item["ease"] < 2.4


def test_invalid_grade(client):
    vid = _add(client).json()["item"]["id"]
    assert client.post(f"/api/vocab/{vid}/review", json={"grade": "perfect"}).status_code == 400


def test_filters_and_search(client):
    _add(client, lemma="deposit", context={"packId": "mini", "sentenceId": "p1s1",
                                           "en": "The deposit is refundable."})
    _add(client, lemma="wane", gloss="减弱", context={"packId": "other", "sentenceId": "p1",
                                                     "en": "Enthusiasm wanes."})

    assert client.get("/api/vocab?packId=mini").json()["total"] == 1
    assert client.get("/api/vocab?q=减弱").json()["items"][0]["lemma"] == "wane"
    assert client.get("/api/vocab?due=1").json()["total"] == 2


def test_patch_and_delete(client):
    vid = _add(client).json()["item"]["id"]
    patched = client.patch(f"/api/vocab/{vid}", json={"note": "常考", "tags": ["住宿"]}).json()
    assert patched["item"]["note"] == "常考"
    assert patched["item"]["tags"] == ["住宿"]
    assert client.delete(f"/api/vocab/{vid}").status_code == 200
    assert client.delete(f"/api/vocab/{vid}").status_code == 404


def test_import_legacy_localstorage_shape(client):
    body = client.post("/api/vocab/import", json={
        "packId": "cam18-t3-p3",
        "items": [
            {"word": "streaming", "lemma": "streaming", "gloss": "分流",
             "context": "The practice of 'streaming' involves separating students.",
             "zh": "分流的做法……", "para": 3, "sentId": "p3s1",
             "src": "剑桥雅思 18 · Test 3 · Passage 3", "ts": 1795089000000},
            {"word": "streaming", "lemma": "streaming", "gloss": "重复项"},
            {"lemma": "", "word": ""},
        ],
    }).json()
    assert body["created"] == 1
    assert body["merged"] == 1
    assert body["skipped"] == 1

    item = client.get("/api/vocab?q=streaming").json()["items"][0]
    assert item["source"].startswith("剑桥雅思")
    assert item["createdAt"] == 1795089000
    assert len(item["contexts"]) == 1


def test_export_json_and_csv(client):
    _add(client, lemma="deposit", context={"packId": "mini", "sentenceId": "p1s1",
                                           "en": "The deposit is refundable.", "zh": "押金可退。"})
    data = client.get("/api/vocab/export?format=json").json()
    assert data["items"][0]["lemma"] == "deposit"

    resp = client.get("/api/vocab/export?format=csv")
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.content.decode("utf-8")
    assert text.startswith("\ufeff")
    assert "lemma,word" in text.splitlines()[0]
    assert "deposit" in text


def test_stats(client):
    _add(client)
    stats = client.get("/api/vocab/stats").json()
    assert stats["total"] == 1
    assert stats["byState"]["new"] == 1
    assert stats["dueNow"] == 1
    assert stats["addedToday"] == 1
