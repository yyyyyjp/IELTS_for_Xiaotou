"""测试环境：临时数据目录 + 合成内容包，绝不碰真实 app.db。"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

TMP = Path(tempfile.mkdtemp(prefix="tifo-test-"))
os.environ["TIFO_DATA_DIR"] = str(TMP / "data")
os.environ["TIFO_CONTENT_DIR"] = str(TMP / "content")

PACKS = TMP / "content" / "packs"
PACKS.mkdir(parents=True, exist_ok=True)

# 真实内容包也一起拷进来，顺带回归导入结果
REAL_PACKS = Path(__file__).resolve().parents[1] / "content" / "packs"
for f in REAL_PACKS.glob("*.json"):
    shutil.copy(f, PACKS / f.name)

MINI = {
    "id": "mini",
    "kind": "reading",
    "origin": "custom",
    "meta": {"book": "测试", "test": "Test 1", "passage": "Passage 1", "title": "Mini"},
    "paragraphs": [
        {"no": 1, "sentences": [
            {"id": "p1s1", "en": "The deposit is refundable if you cancel early.",
             "zh": "如果提前取消，押金可退。"},
            {"id": "p1s2", "en": "Landlords usually require authorisation before painting.",
             "zh": "房东通常要求粉刷前获得授权。"},
        ]},
        {"no": 2, "sentences": [
            {"id": "p2s1", "en": "Waste disposal is included in the monthly rent.",
             "zh": "垃圾处理费包含在月租里。"},
            {"id": "p2s2", "en": "The deposit is refundable if you cancel early, but the "
                                 "authorisation must be signed before the landlord agrees to "
                                 "return it.",
             "zh": "如果提前取消押金可退，但房东同意退款前必须签署授权书。"},
        ]},
    ],
    "questionGroups": [
        {"id": "mcq", "type": "mcq", "from": 1, "to": 2, "instruction": "Choose A or B",
         "items": [
             {"no": 1, "stem": "What is refundable?",
              "options": [{"key": "A", "text": "the deposit"},
                          {"key": "B", "text": "the rent"}], "answer": "A"},
             {"no": 2, "stem": "What is included?",
              "options": [{"key": "A", "text": "water"},
                          {"key": "B", "text": "waste disposal"}], "answer": "B"},
         ]},
        {"id": "ynng", "type": "ynng", "from": 3, "to": 4, "instruction": "YES/NO/NG",
         "items": [
             {"no": 3, "stem": "The deposit is refundable.", "answer": "YES"},
             {"no": 4, "stem": "Pets are allowed.", "answer": "NG"},
         ]},
    ],
    "lexicon": {"deposit": "n. 押金", "refundable": "adj. 可退还的", "disposal": "n. 处理"},
}
(PACKS / "mini.json").write_text(json.dumps(MINI, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db(client):
    import db

    for table in ("attempts", "sessions", "vocab"):
        db.execute(f"DELETE FROM {table}")
    yield
