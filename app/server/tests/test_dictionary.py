"""离线词典服务与接口测试：独立构建轻量 ECDICT fixture，不依赖完整词库。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def mini_ecdict(tmp_path: Path, monkeypatch):
    import config
    import services.dictionary as dictionary

    db_path = tmp_path / "mini_ecdict.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE stardict (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word VARCHAR(64) NOT NULL UNIQUE,
            sw VARCHAR(64) NOT NULL,
            phonetic VARCHAR(64),
            definition TEXT,
            translation TEXT,
            pos VARCHAR(16),
            collins INTEGER DEFAULT 0,
            oxford INTEGER DEFAULT 0,
            tag VARCHAR(64),
            bnc INTEGER DEFAULT 0,
            frq INTEGER DEFAULT 0,
            exchange TEXT
        );
        CREATE INDEX idx_stardict_sw ON stardict (sw);
        """
    )
    rows = [
        ("deposit", "deposit", "dɪ'pɒzɪt", "a sum of money paid into a bank",
         "n. 存款, 押金\\nvt. 存放, 沉积", "n:60/v:40", 3, 1, "cet4 cet6 ielts toefl", 2000, 1800,
         "p:deposited/d:deposited/i:depositing/3:deposits"),
        ("go", "go", "gəʊ", "move from one place to another",
         "vi. 去, 走, 进行\\nn. 尝试", "v:90/n:10", 5, 1, "zk gk cet4", 30, 25,
         "p:went/d:gone/i:going/3:goes"),
        ("went", "went", "went", "past tense of go",
         "v. 去（go的过去式）", "", 0, 0, "", 0, 0,
         "0:go/1:p"),
        ("authorization", "authorization", "ˌɔːθəraɪ'zeɪʃən", "official permission",
         "n. 授权, 批准", "n:100", 2, 0, "cet6 ielts toefl", 5000, 4500, ""),
        ("waste", "waste", "weɪst", "unwanted material",
         "n. 浪费, 废物\\nvt. 浪费", "n:50/v:50", 4, 1, "zk gk cet4 ielts", 1100, 1000, ""),
        ("disposal", "disposal", "dɪ'spəʊzl", "the action of throwing away",
         "n. 处理, 处置, 安排", "n:100", 3, 1, "cet6 ielts toefl", 4200, 3900, ""),
        ("take for granted", "takeforgranted", "", "fail to appreciate",
         "认为……理所当然", "", 0, 0, "", 0, 0, ""),
        ("mixed-ability", "mixedability", "", "including learners of different levels",
         "adj. 混合能力的", "", 0, 0, "", 0, 0, ""),
    ]
    conn.executemany(
        "INSERT INTO stardict (word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "DICT_DB_PATH", db_path)
    dictionary.reset_connection()
    yield db_path
    dictionary.reset_connection()


def test_dict_status_and_health(client, mini_ecdict):
    res = client.get("/api/dict/status")
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is True
    assert body["entries"] == 8

    health = client.get("/api/health").json()
    assert health["dict"]["ready"] is True
    assert health["dict"]["entries"] == 8


def test_lookup_ecdict_exact_and_exchange(client, mini_ecdict):
    # 直接查单词（处理字面 \n 换行、音标、标签）
    r1 = client.get("/api/dict/lookup", params={"q": "deposit"}).json()
    assert r1["found"] is True
    assert r1["source"] == "ecdict"
    assert r1["lemma"] == "deposit"
    assert r1["phonetic"] == "dɪ'pɒzɪt"
    assert "n." in r1["pos"] and "vt." in r1["pos"]
    assert "\n" in r1["gloss"]
    assert "ielts" in r1["tags"]
    assert r1["oxford"] is True
    assert r1["collins"] == 3
    assert r1["saved"] is False

    # 不规则过去式 went -> 通过 exchange 还原到 go 并补齐词根信息
    r2 = client.get("/api/dict/lookup", params={"q": "went"}).json()
    assert r2["found"] is True
    assert r2["lemma"] == "go"
    assert "过去式" in r2["formNote"]
    assert r2["collins"] == 5
    assert "去" in r2["gloss"]


def test_lookup_uk_spelling_and_pack_override(client, mini_ecdict):
    # 英式拼写复数 authorisations -> authorization
    r_uk = client.get("/api/dict/lookup", params={"q": "authorisations"}).json()
    assert r_uk["found"] is True
    assert r_uk["lemma"] == "authorization"
    assert "授权" in r_uk["gloss"]

    # 传 packId=mini 时，pack.lexicon 的语境释义优先，但音标和词典全义由 ECDICT 补全
    r_pack = client.get("/api/dict/lookup", params={"q": "deposit", "packId": "mini"}).json()
    assert r_pack["found"] is True
    assert r_pack["source"] == "pack"
    assert r_pack["gloss"] == "押金"
    assert r_pack["phonetic"] == "dɪ'pɒzɪt"
    assert "存款" in r_pack["dictGloss"]
    assert "ielts" in r_pack["tags"]


def test_lookup_phrase_and_tokens_fallback(client, mini_ecdict):
    # 词典收录的短语精确命中
    r_phrase = client.get("/api/dict/lookup", params={"q": "take for granted"}).json()
    assert r_phrase["found"] is True
    assert r_phrase["source"] == "ecdict"
    assert "理所当然" in r_phrase["gloss"]

    # 未整体收录的多词短语 -> 自动拆实词查 ECDICT
    r_tokens = client.get("/api/dict/lookup", params={"q": "the waste disposal"}).json()
    assert r_tokens["found"] is True
    assert r_tokens["source"] == "tokens"
    words = [item["lemma"] for item in r_tokens["tokens"]]
    assert words == ["waste", "disposal"]


def test_lookup_reflects_vocab_saved_state(client, mini_ecdict):
    add = client.post("/api/vocab", json={"lemma": "deposit", "word": "deposit", "gloss": "押金"})
    assert add.status_code == 200
    vid = add.json()["item"]["id"]

    res = client.get("/api/dict/lookup", params={"q": "deposits"}).json()
    assert res["found"] is True
    assert res["lemma"] == "deposit"
    assert res["saved"] is True
    assert res["vocabId"] == vid


def test_lookup_graceful_when_dict_missing(client, tmp_path: Path, monkeypatch):
    import config
    import services.dictionary as dictionary

    monkeypatch.setattr(config, "DICT_DB_PATH", tmp_path / "nonexistent.db")
    dictionary.reset_connection()
    try:
        res = client.get("/api/dict/lookup", params={"q": "deposit", "packId": "mini"}).json()
        assert res["dictReady"] is False
        assert res["found"] is True
        assert res["source"] == "pack"
        assert res["gloss"] == "押金"

        miss = client.get("/api/dict/lookup", params={"q": "unknownword"}).json()
        assert miss["found"] is False
        assert miss["dictReady"] is False
    finally:
        dictionary.reset_connection()
