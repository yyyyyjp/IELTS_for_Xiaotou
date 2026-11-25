"""测试 Web 端导出包合成与 AI 复盘导入接口。"""
from __future__ import annotations

import json


SAMPLE_PASSAGE = {
    "passage_id": "reading:999",
    "book": "剑雅20",
    "test": "Test 2",
    "part": "Passage 1",
    "title": "Urban Rooftop Gardens",
    "paragraphs": [{"label": "1"}, {"label": "2"}],
    "sentences": [
        {"i": 0, "paragraph": "1", "text": "Rooftop gardens cool buildings.", "translation": "屋顶花园给建筑降温。"},
        {"i": 1, "paragraph": "1", "text": "They also absorb rainwater.", "translation": "它们还能吸收雨水。"},
        {"i": 2, "paragraph": "2", "text": "Maintenance costs remain high.", "translation": "维护成本依然高昂。"},
    ],
}

SAMPLE_ATTEMPT = {
    "attempt_id": "reading:999:1",
    "passage_id": "reading:999",
    "book": "剑雅20",
    "test": "Test 2",
    "part": "Passage 1",
    "submitted_at": "2026-11-20T12:00:00Z",
    "duration_sec": 1200,
    "by_type": [{"question_type": "tfng", "question_type_zh": "判断题", "correct": 1, "total": 2, "accuracy": 0.5}],
    "marks": {
        "highlights": [
            {"text": "cool buildings", "scope": "article", "paragraph": "1"},
            {"text": "high", "scope": "question", "question_number": 2},
        ],
        "notes": [{"content": "注意转折"}],
    },
}

SAMPLE_GROUPS = [
    {
        "group_id": "g_tfng",
        "attempt_id": "reading:999:1",
        "question_type": "tfng",
        "instruction": "Questions 1-2\nTRUE / FALSE / NOT GIVEN",
    }
]

SAMPLE_QUESTIONS = [
    {
        "question_id": "q:1",
        "attempt_id": "reading:999:1",
        "group_id": "g_tfng",
        "q_number": 1,
        "question_type": "tfng",
        "stem": "Rooftop gardens reduce building temperature.",
        "correct_answer": "TRUE",
        "yours": "TRUE",
        "is_correct": True,
    },
    {
        "question_id": "q:2",
        "attempt_id": "reading:999:1",
        "group_id": "g_tfng",
        "q_number": 2,
        "question_type": "tfng",
        "stem": "Maintenance is cheap.",
        "correct_answer": "FALSE",
        "yours": "TRUE",
        "is_correct": False,
    },
]


def test_export_prompt_includes_sentence_indices_and_highlights(client):
    res = client.post(
        "/api/packs/export-prompt",
        json={
            "passage": SAMPLE_PASSAGE,
            "attempt": SAMPLE_ATTEMPT,
            "questions": SAMPLE_QUESTIONS,
            "groups": SAMPLE_GROUPS,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == "cam20-t2-p1"
    assert "[p1, b=0] Rooftop gardens cool buildings." in body["prompt"]
    assert "[p2, b=0] Maintenance costs remain high." in body["prompt"]
    assert "cool buildings" in body["prompt"]
    assert "注意转折" in body["prompt"]


def test_import_from_export_with_fenced_ai_json_and_idempotent_history(client):
    ai_reply = """好的，下面是为你生成的复盘 JSON：
```json
{
  "review": {
    "title": "1 道错题：反义形容词误判",
    "sections": [
      {
        "kind": "tfng",
        "from": 1,
        "to": 2,
        "items": [
          {"no": 2, "label": "错在哪", "diag": "原文是 high 而非 cheap", "cites": ["p2s1"]},
          {"no": 99, "label": "why-wrong", "diag": "测试越界题号", "cites": [{"p": 9, "b": [0]}]}
        ]
      }
    ]
  },
  "guide": {
    "title": "屋顶花园的利与弊",
    "band": [{"n": 1, "f": "优势", "s": "t"}, {"n": 2, "f": "成本瓶颈", "s": "a"}]
  },
  "lexicon": {
    "rooftop": "n. 屋顶"
  }
}
```
希望对你有帮助！"""

    # 1. dryRun 预览：不落盘，但返回解析摘要与越界告警
    preview = client.post(
        "/api/packs/from-export",
        json={
            "passage": SAMPLE_PASSAGE,
            "attempt": SAMPLE_ATTEMPT,
            "questions": SAMPLE_QUESTIONS,
            "groups": SAMPLE_GROUPS,
            "analysisText": ai_reply,
            "dryRun": True,
        },
    )
    assert preview.status_code == 200
    p_data = preview.json()
    assert p_data["id"] == "cam20-t2-p1"
    assert p_data["exists"] is False
    assert p_data["analysis"]["hasReview"] is True
    assert p_data["analysis"]["hasGuide"] is True
    assert any("99" in w for w in p_data["warnings"])
    assert any("p=9" in w for w in p_data["warnings"])
    assert client.get("/api/packs/cam20-t2-p1").status_code == 404

    # 2. 正式导入：落盘 + 写入历史记录
    saved = client.post(
        "/api/packs/from-export",
        json={
            "passage": SAMPLE_PASSAGE,
            "attempt": SAMPLE_ATTEMPT,
            "questions": SAMPLE_QUESTIONS,
            "groups": SAMPLE_GROUPS,
            "analysisText": ai_reply,
            "dryRun": False,
        },
    )
    assert saved.status_code == 200
    s_data = saved.json()
    assert s_data["created"] is True
    assert s_data["historyRecorded"] is True

    # 3. 再次导入同一提交：历史成绩幂等不重复插入
    again = client.post(
        "/api/packs/from-export",
        json={
            "passage": SAMPLE_PASSAGE,
            "attempt": SAMPLE_ATTEMPT,
            "questions": SAMPLE_QUESTIONS,
            "groups": SAMPLE_GROUPS,
            "analysisText": ai_reply,
            "dryRun": False,
        },
    )
    assert again.status_code == 200
    assert again.json()["historyRecorded"] is False

    sessions = client.get("/api/reading/sessions").json()["items"]
    matching = [s for s in sessions if s["packId"] == "cam20-t2-p1"]
    assert len(matching) == 1

    # 4. 读取完整内容包，验证 p2s1 已转为 {p:2, b:[0]}
    full = client.get("/api/packs/cam20-t2-p1?answers=1").json()
    assert full["review"]["title"] == "1 道错题：反义形容词误判"
    assert full["review"]["sections"][0]["items"][0]["cites"] == [{"p": 2, "b": [0]}]
    assert full["lexicon"]["rooftop"]["gloss"] == "屋顶"

    # 清理测试生成的自定义包文件
    assert client.delete("/api/packs/cam20-t2-p1").status_code == 200


def test_update_analysis_on_existing_pack_and_get_prompt(client):
    # 为 mini 包获取提示词
    prompt_res = client.get("/api/packs/mini/prompt")
    assert prompt_res.status_code == 200
    assert "[p1, b=0]" in prompt_res.json()["prompt"]

    # 为已有 mini 包单独注入 AI 复盘（dryRun -> 正式保存）
    payload = {
        "review": {
            "title": "Mini 测试复盘",
            "sections": [
                {
                    "kind": "mcq",
                    "from": 1,
                    "to": 2,
                    "items": [{"no": 1, "label": "why-right", "diag": "押金可退", "cites": [{"p": 1, "b": [0]}]}],
                }
            ],
        },
        "lexicon": {"authorisation": "n. 授权"},
    }
    res = client.post(
        "/api/packs/mini/analysis",
        json={"analysisText": json.dumps(payload, ensure_ascii=False), "dryRun": True},
    )
    assert res.status_code == 200
    assert res.json()["warnings"] == []
    assert res.json()["analysis"]["reviewTitle"] == "Mini 测试复盘"
    assert res.json()["analysis"]["lexiconCount"] == 1
