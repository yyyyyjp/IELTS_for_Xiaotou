"""听写：题目生成、练习会话、判分与记录。

一次练习 = 一个 session；每答一题 = 一条 attempt。
题目快照存在 session.meta 里，所以中途改了内容包，这一轮仍按原题判分。
"""
from __future__ import annotations

import json
import re
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import content.loader as loader
import db
import services.dictation as dictation
import services.grading as grading
import tts_service

router = APIRouter(tags=["dictation"])

Mode = Literal["word", "word_in_context", "sentence"]
Source = Literal["vocab", "pack", "auto"]


# ---------------------------------------------------------------- 题目生成
def _vocab_rows(pack_id: str) -> list:
    rows = db.query("SELECT * FROM vocab WHERE state != 'suspended' ORDER BY due_at ASC, id ASC")
    if not pack_id:
        return list(rows)
    needle = f'"packId":"{pack_id}"'
    return [r for r in rows if needle in (r["contexts"] or "")]


def _lexicon_candidates(pack) -> list[tuple[int, str, dict, str, str]]:
    """原文词表里值得听写的词，按在文中首次出现的顺序。"""
    sentences = pack.sentences()
    out = []
    for word, entry in pack.doc.lexicon.items():
        low = word.lower()
        if len(low) < 4 or low in dictation.STOP:
            continue
        if not (entry.gloss or "").strip():
            continue
        for i, (_p, s) in enumerate(sentences):
            if re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", s.en, re.I):
                out.append((i, word, entry.model_dump(), s.en, s.zh))
                break
    out.sort(key=lambda x: (x[0], x[1].lower()))
    return out


def build_items(pack, mode: str, source: str, limit: int) -> list[dictation.Item]:
    items: list[dictation.Item] = []

    if mode in ("word", "word_in_context"):
        if pack.doc.kind == "deck":
            for i, row in enumerate(pack.doc.items):
                it = dictation.deck_item(pack, i, row.model_dump(), mode)
                if it:
                    items.append(it)
                if len(items) >= limit:
                    break
            return items

        rows = _vocab_rows(pack.id) if source in ("vocab", "auto") else []
        for r in rows:
            sentence, zh = dictation.resolve_context(r, pack.id)
            items.append(dictation.vocab_word_item(pack.id, r, mode, sentence, zh))
            if len(items) >= limit:
                break
        if not items and source in ("auto", "pack") and pack.doc.kind == "reading":
            for _i, word, entry, sentence, zh in _lexicon_candidates(pack):
                items.append(dictation.lexicon_word_item(
                    pack.id, word, entry, mode, sentence, zh))
                if len(items) >= limit:
                    break
    elif mode == "sentence":
        focus = {r["lemma"] for r in _vocab_rows(pack.id)}
        if pack.doc.kind == "deck":
            for i, row in enumerate(pack.doc.items):
                it = dictation.deck_item(pack, i, row.model_dump(), "sentence")
                if it:
                    items.append(it)
                if len(items) >= limit:
                    break
        else:
            for _p, s in pack.sentences():
                it = dictation.sentence_item(pack.id, s.id, s.en, s.zh, focus)
                if it:
                    items.append(it)
                if len(items) >= limit:
                    break
    return items


def _public_items(items: list[dictation.Item], voice: str) -> list[dict]:
    return [i.public(voice) for i in items]


# ---------------------------------------------------------------- schemas
class SessionIn(BaseModel):
    packId: str = Field(min_length=1)
    mode: Mode = "word"
    source: Source = "auto"
    limit: int = Field(default=20, ge=1, le=100)
    itemIds: list[str] = Field(default_factory=list)
    voice: str = tts_service.DEFAULT_VOICE


class AnswerIn(BaseModel):
    itemId: str
    input: str | list[str] = ""
    replays: int = 0
    durationMs: int = 0


# ---------------------------------------------------------------- routes
@router.get("/dictation/items")
def preview_items(
    packId: str = Query(..., min_length=1),
    mode: Mode = Query(default="word"),
    source: Source = Query(default="auto"),
    limit: int = Query(default=20, ge=1, le=100),
    voice: str = Query(default=tts_service.DEFAULT_VOICE),
):
    pack = loader.get(packId)
    if not pack:
        raise HTTPException(404, "内容包不存在")
    if voice not in tts_service.VOICE_IDS:
        raise HTTPException(400, "未知音色")
    items = build_items(pack, mode, source, limit)
    return {"items": _public_items(items, voice), "count": len(items)}


@router.post("/dictation/sessions")
def create_session(payload: SessionIn):
    pack = loader.get(payload.packId)
    if not pack:
        raise HTTPException(404, "内容包不存在")
    if payload.voice not in tts_service.VOICE_IDS:
        raise HTTPException(400, "未知音色")

    build_limit = 100 if payload.itemIds else payload.limit
    items = build_items(pack, payload.mode, payload.source, build_limit)
    if payload.itemIds:
        keep = set(payload.itemIds)
        items = [i for i in items if i.id in keep]
    if not items:
        hint = "生词本里还没有这个词包的词；先精读收词，或把 source 传 pack 用原文词表"
        raise HTTPException(400, f"没有可听写的内容。{hint if payload.mode != 'sentence' else '这篇没有可用句子'}")

    sid = db.new_id("ds")
    now = db.now()
    meta = {"items": [i.stored() for i in items], "voice": payload.voice, "answers": {}}
    db.execute(
        "INSERT INTO sessions(id,kind,pack_id,mode,planned,answered,correct,meta,started_at)"
        " VALUES(?,?,?,?,?,0,0,?,?)",
        (sid, "dictation", pack.id, payload.mode, len(items), json.dumps(meta, ensure_ascii=False), now),
    )
    return {
        "sessionId": sid,
        "packId": pack.id,
        "mode": payload.mode,
        "voice": payload.voice,
        "startedAt": now,
        "items": _public_items(items, payload.voice),
    }


def _session(sid: str):
    row = db.one("SELECT * FROM sessions WHERE id=?", (sid,))
    if not row or row["kind"] != "dictation":
        raise HTTPException(404, "练习不存在")
    return row


@router.get("/dictation/sessions/{sid}")
def get_session(sid: str):
    row = _session(sid)
    meta = json.loads(row["meta"] or "{}")
    items = [dictation.Item.from_stored(d) for d in meta.get("items", [])]
    return {
        "sessionId": sid,
        "packId": row["pack_id"],
        "mode": row["mode"],
        "voice": meta.get("voice", tts_service.DEFAULT_VOICE),
        "startedAt": row["started_at"],
        "endedAt": row["ended_at"],
        "planned": row["planned"],
        "answered": row["answered"],
        "correct": row["correct"],
        "items": _public_items(items, meta.get("voice", tts_service.DEFAULT_VOICE)),
        "answers": meta.get("answers", {}),
    }


@router.post("/dictation/sessions/{sid}/answer")
def answer(sid: str, payload: AnswerIn):
    row = _session(sid)
    if row["ended_at"]:
        raise HTTPException(409, "这次练习已结束")
    meta = json.loads(row["meta"] or "{}")
    items = {d["id"]: d for d in meta.get("items", [])}
    item = items.get(payload.itemId)
    if not item:
        raise HTTPException(404, "题目不在本次练习里")

    expected = list(item.get("answers") or [])
    result = grading.compare(expected, payload.input)
    kind = "dictation_word" if item.get("type") in ("word", "word_in_context") else "dictation_sentence"
    ref = expected[0].lower() if kind == "dictation_word" and expected else item["id"]

    answers = meta.setdefault("answers", {})
    prev = answers.get(payload.itemId)
    answers[payload.itemId] = {
        "input": payload.input,
        "correct": result["ok"],
        "replays": payload.replays,
    }
    # 会话统计按「最终答案」算：答错后重听改对，仍记为对，但两条记录都留在 attempts
    delta = (1 if result["ok"] else 0) - (1 if prev and prev.get("correct") else 0)

    now = db.now()
    db.insert_attempt(
        kind=kind,
        ref=ref,
        pack_id=row["pack_id"],
        session_id=sid,
        input=json.dumps(payload.input, ensure_ascii=False)
        if isinstance(payload.input, list) else str(payload.input),
        expected="|".join(expected),
        correct=1 if result["ok"] else 0,
        duration_ms=payload.durationMs,
        meta=json.dumps({"itemId": payload.itemId, "answers": expected,
                         "replays": payload.replays}, ensure_ascii=False),
        created_at=now,
    )
    if prev is None:
        db.execute(
            "UPDATE sessions SET answered=answered+1, correct=correct+?, meta=? WHERE id=?",
            (1 if result["ok"] else 0, json.dumps(meta, ensure_ascii=False), sid),
        )
    else:
        db.execute(
            "UPDATE sessions SET correct=correct+?, meta=? WHERE id=?",
            (delta, json.dumps(meta, ensure_ascii=False), sid),
        )

    return {
        "itemId": payload.itemId,
        "correct": result["ok"],
        "parts": result["parts"],
        "expected": result["expected"],
        "firstTime": prev is None,
    }


@router.post("/dictation/sessions/{sid}/finish")
def finish_session(sid: str):
    row = _session(sid)
    meta = json.loads(row["meta"] or "{}")
    now = db.now()
    ended = row["ended_at"] or now
    if not row["ended_at"]:
        db.execute("UPDATE sessions SET ended_at=? WHERE id=?", (ended, sid))

    answers = meta.get("answers", {})
    items = meta.get("items", [])
    wrong, skipped = [], []
    for it in items:
        got = answers.get(it["id"])
        if not got:
            skipped.append({"itemId": it["id"], "answers": it.get("answers", []),
                            "text": it.get("masked_text", "")})
        elif not got.get("correct"):
            wrong.append({"itemId": it["id"], "answers": it.get("answers", []),
                          "input": got.get("input"), "text": it.get("masked_text", "")})

    total = len(items)
    answered = len(answers)
    correct = sum(1 for a in answers.values() if a.get("correct"))
    return {
        "sessionId": sid,
        "packId": row["pack_id"],
        "mode": row["mode"],
        "total": total,
        "answered": answered,
        "correct": correct,
        "accuracy": round(correct / answered, 4) if answered else 0,
        "durationSec": max(0, ended - row["started_at"]),
        "wrong": wrong,
        "skipped": skipped,
    }


@router.get("/dictation/sessions")
def list_sessions(limit: int = Query(default=20, ge=1, le=100)):
    rows = db.query(
        "SELECT * FROM sessions WHERE kind='dictation' ORDER BY started_at DESC LIMIT ?", (limit,)
    )
    out = []
    for r in rows:
        ended = r["ended_at"] or r["started_at"]
        out.append({
            "sessionId": r["id"],
            "packId": r["pack_id"],
            "mode": r["mode"],
            "planned": r["planned"],
            "answered": r["answered"],
            "correct": r["correct"],
            "accuracy": round(r["correct"] / r["answered"], 4) if r["answered"] else 0,
            "durationSec": max(0, ended - r["started_at"]),
            "startedAt": r["started_at"],
            "endedAt": r["ended_at"],
        })
    return {"items": out}
