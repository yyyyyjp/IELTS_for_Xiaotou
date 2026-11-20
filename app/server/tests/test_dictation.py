from __future__ import annotations


def _add_word(client, lemma="deposit", **kw):
    payload = {
        "lemma": lemma,
        "word": kw.pop("word", lemma),
        "gloss": kw.pop("gloss", "押金"),
        "context": {"packId": "mini", "sentenceId": "p1s1",
                    "en": kw.pop("en", "The deposit is refundable if you cancel early."),
                    "zh": "押金可退。"},
    }
    payload.update(kw)
    return client.post("/api/vocab", json=payload).json()["item"]


def test_word_items_come_from_vocab_without_leaking_answers(client):
    _add_word(client)
    body = client.get("/api/dictation/items?packId=mini&mode=word&limit=5").json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["type"] == "word"
    assert item["text"] == ""
    assert "answers" not in item
    assert item["audioText"] == "deposit"
    assert item["hint"]["gloss"] == "押金"
    assert "/api/tts/audio" in item["audioUrl"]


def test_lexicon_fallback_when_vocab_empty(client):
    body = client.get("/api/dictation/items?packId=mini&mode=word&source=auto").json()
    words = {i["audioText"].lower() for i in body["items"]}
    assert {"deposit", "refundable", "disposal"} <= words


def test_source_pack_ignores_vocab(client):
    _add_word(client, lemma="wane", en="Enthusiasm wanes quickly.", gloss="减弱")
    body = client.get("/api/dictation/items?packId=mini&mode=word&source=pack").json()
    assert all(i["source"] == "pack" for i in body["items"])
    assert "wane" not in {i["audioText"].lower() for i in body["items"]}


def test_word_in_context_masks_the_word(client):
    _add_word(client)
    body = client.get("/api/dictation/items?packId=mini&mode=word_in_context").json()
    item = body["items"][0]
    assert "{{}}" in item["text"]
    assert "deposit" not in item["text"].lower()
    assert item["blankLengths"] == [7]
    assert item["audioText"] == "deposit"


def test_sentence_items_are_masked_and_do_not_leak_answers(client):
    body = client.get("/api/dictation/items?packId=mini&mode=sentence&limit=3").json()
    assert body["count"] == 3
    for item in body["items"]:
        assert "{{}}" in item["text"]
        assert "answers" not in item
        assert item["text"].count("{{}}") == item["blankCount"]
        assert len(item["blankLengths"]) == item["blankCount"]


def test_session_answer_and_finish(client):
    _add_word(client)
    created = client.post("/api/dictation/sessions",
                          json={"packId": "mini", "mode": "word", "limit": 5}).json()
    assert created["items"] and created["sessionId"]
    item_id = created["items"][0]["id"]

    wrong = client.post(f"/api/dictation/sessions/{created['sessionId']}/answer",
                        json={"itemId": item_id, "input": "deposite", "durationMs": 3000}).json()
    assert wrong["correct"] is False
    assert wrong["expected"] == ["deposit"]

    # 重听后再答对：不重复计入 answered
    right = client.post(f"/api/dictation/sessions/{created['sessionId']}/answer",
                        json={"itemId": item_id, "input": "  Deposit. ", "replays": 1}).json()
    assert right["correct"] is True
    assert right["firstTime"] is False

    detail = client.get(f"/api/dictation/sessions/{created['sessionId']}").json()
    assert detail["answered"] == 1
    assert detail["correct"] == 1

    summary = client.post(f"/api/dictation/sessions/{created['sessionId']}/finish").json()
    assert summary["total"] == 1
    assert summary["correct"] == 1
    assert summary["accuracy"] == 1.0

    # 结束后不能再答
    assert client.post(f"/api/dictation/sessions/{created['sessionId']}/answer",
                       json={"itemId": item_id, "input": "deposit"}).status_code == 409


def test_multi_blank_grading(client):
    long_sentence = ("The deposit is refundable if you cancel early, but the authorisation "
                     "must be signed before the landlord agrees to return it.")
    _add_word(client, lemma="deposit", en=long_sentence, gloss="押金")
    _add_word(client, lemma="authorisation", word="authorisation", en=long_sentence, gloss="授权")

    created = client.post("/api/dictation/sessions",
                          json={"packId": "mini", "mode": "sentence", "limit": 10}).json()
    item = next(i for i in created["items"] if "must be signed" in i["text"])
    assert item["blankCount"] == 2
    assert item["blankLengths"] == [7, 13]

    body = client.post(f"/api/dictation/sessions/{created['sessionId']}/answer",
                       json={"itemId": item["id"],
                             "input": ["deposit", "authorisation"]}).json()
    assert body["correct"] is True
    assert body["parts"] == [True, True]

    wrong = client.post(f"/api/dictation/sessions/{created['sessionId']}/answer",
                        json={"itemId": item["id"],
                              "input": ["deposit", "authorization"]}).json()
    assert wrong["correct"] is False
    assert wrong["parts"] == [True, False]


def test_session_without_content_is_explained(client):
    r = client.post("/api/dictation/sessions", json={"packId": "mini", "mode": "word",
                                                    "source": "vocab"})
    assert r.status_code == 400
    assert "生词本" in r.json()["detail"]


def test_unknown_pack(client):
    assert client.get("/api/dictation/items?packId=nope").status_code == 404
    assert client.post("/api/dictation/sessions", json={"packId": "nope"}).status_code == 404


def test_item_ids_filter(client):
    _add_word(client, lemma="deposit")
    _add_word(client, lemma="refundable", word="refundable", gloss="可退还的",
              en="The deposit is refundable if you cancel early.")
    all_items = client.get("/api/dictation/items?packId=mini&mode=word").json()["items"]
    target = all_items[-1]["id"]
    created = client.post("/api/dictation/sessions",
                          json={"packId": "mini", "mode": "word", "itemIds": [target]}).json()
    assert [i["id"] for i in created["items"]] == [target]


def test_attempts_and_weak_words(client):
    _add_word(client)
    sid = client.post("/api/dictation/sessions",
                      json={"packId": "mini", "mode": "word"}).json()
    client.post(f"/api/dictation/sessions/{sid['sessionId']}/answer",
                json={"itemId": sid["items"][0]["id"], "input": "deposite"})
    weak = client.get("/api/stats/weak-words").json()["items"]
    assert weak[0]["word"] == "deposit"
    assert weak[0]["wrong"] == 1
    assert weak[0]["gloss"] == "押金"
