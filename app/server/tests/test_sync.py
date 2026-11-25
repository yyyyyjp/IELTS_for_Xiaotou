"""测试增量双向同步接口（/api/sync、墓碑软删除、冲突合并、幂等去重、口令鉴权）。"""
from __future__ import annotations

import config


def test_vocab_soft_delete_tombstone_and_revive(client):
    r = client.post("/api/vocab", json={"lemma": "wane", "word": "wane", "gloss": "衰退"})
    assert r.status_code == 200
    vid = r.json()["item"]["id"]

    # 删除后对普通查询不可见，但增量同步能拉到 deletedAt > 0 的墓碑
    assert client.delete(f"/api/vocab/{vid}").status_code == 200
    assert client.get("/api/vocab").json()["total"] == 0

    sync_res = client.post("/api/sync", json={"cursor": {"vocab": 0}}).json()
    tombstones = [v for v in sync_res["pull"]["vocab"] if v["lemma"] == "wane"]
    assert len(tombstones) == 1
    assert tombstones[0]["deletedAt"] > 0

    # 重新添加同名生词：自动复活且重置为 new
    revived = client.post("/api/vocab", json={"lemma": "wane", "word": "wane", "gloss": "减弱"}).json()
    assert revived["created"] is True
    assert revived["item"]["deletedAt"] == 0
    assert revived["item"]["gloss"] == "减弱"
    assert client.get("/api/vocab").json()["total"] == 1


def test_sync_push_pull_and_idempotent_attempts(client):
    push_payload = {
        "cursor": {"vocab": 0, "sessions": 0, "attempts": 0, "packs": 0},
        "push": {
            "vocab": [
                {
                    "lemma": "ubiquitous",
                    "word": "ubiquitous",
                    "gloss": "无处不在的",
                    "pos": "adj.",
                    "phonetic": "juːˈbɪkwɪtəs",
                    "contexts": [{"packId": "mini", "sentenceId": "p1s1", "en": "Phones are ubiquitous."}],
                    "tags": ["ielts"],
                    "state": "review",
                    "intervalDays": 3,
                    "reps": 2,
                    "createdAt": 1795000000,
                    "updatedAt": 1795000100,
                }
            ],
            "sessions": [
                {
                    "id": "rs_local_001",
                    "kind": "reading",
                    "packId": "mini",
                    "mode": "practice",
                    "planned": 4,
                    "answered": 4,
                    "correct": 3,
                    "meta": {"nos": [1, 2, 3, 4]},
                    "startedAt": 1795000000,
                    "endedAt": 1795000600,
                    "updatedAt": 1795000600,
                }
            ],
            "attempts": [
                {
                    "clientId": "att_local_unique_1",
                    "kind": "vocab_review",
                    "ref": "ubiquitous",
                    "input": "good",
                    "correct": 1,
                    "durationMs": 1800,
                    "createdAt": 1795000100,
                }
            ],
        },
    }

    res1 = client.post("/api/sync", json=push_payload)
    assert res1.status_code == 200
    b1 = res1.json()
    assert b1["pushed"] == {"vocab": 1, "sessions": 1, "attempts": 1}
    assert any(v["lemma"] == "ubiquitous" for v in b1["pull"]["vocab"])
    assert any(a["clientId"] == "att_local_unique_1" for a in b1["pull"]["attempts"])

    # 使用返回的新 cursor 再次发送相同 attempt：幂等跳过且增量 pull 为空
    res2 = client.post(
        "/api/sync",
        json={
            "cursor": b1["cursor"],
            "push": {"attempts": push_payload["push"]["attempts"]},
        },
    )
    assert res2.status_code == 200
    b2 = res2.json()
    assert b2["pushed"]["attempts"] == 0
    assert b2["pull"]["vocab"] == []
    assert b2["pull"]["sessions"] == []
    assert b2["pull"]["attempts"] == []

    # 旧时间戳客户端推送同一词的新例句：不覆盖新状态，但自动合并例句并集
    res3 = client.post(
        "/api/sync",
        json={
            "cursor": b2["cursor"],
            "push": {
                "vocab": [
                    {
                        "lemma": "ubiquitous",
                        "word": "ubiquitous",
                        "gloss": "旧释义",
                        "state": "new",
                        "reps": 0,
                        "contexts": [{"packId": "other", "sentenceId": "p2s1", "en": "Plastic is ubiquitous."}],
                        "createdAt": 1794000000,
                        "updatedAt": 1794000000,
                    }
                ]
            },
        },
    ).json()
    assert res3["pushed"]["vocab"] == 1
    merged = client.get("/api/vocab?q=ubiquitous").json()["items"][0]
    assert merged["state"] == "review"
    assert merged["reps"] == 2
    assert len(merged["contexts"]) == 2


def test_sync_token_protection_and_snapshot(client, monkeypatch):
    monkeypatch.setattr(config, "SYNC_TOKEN", "my-secret-token")

    # 未带 token 返回 401
    unauth = client.post("/api/sync", json={})
    assert unauth.status_code == 401

    # 带 Bearer token 放行
    ok = client.post(
        "/api/sync",
        json={},
        headers={"Authorization": "Bearer my-secret-token"},
    )
    assert ok.status_code == 200
    assert ok.json()["authRequired"] is True

    snap = client.get("/api/sync/export", headers={"X-Sync-Token": "my-secret-token"})
    assert snap.status_code == 200
    assert snap.json()["schemaVersion"] == 2
