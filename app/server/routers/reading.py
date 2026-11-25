"""精读篇目的作答：开一轮练习、交卷判分、写入记录。

答案只存在服务端内容包里；开练习时下发的题目不含答案，
复盘时才用 ?answers=1 或交卷返回的字段拿到正确答案。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import content.loader as loader
import db
import services.grading as grading

router = APIRouter(tags=["reading"])


class CreateIn(BaseModel):
    packId: str = Field(min_length=1)
    nos: list[int] = Field(default_factory=list, description="只做其中几题，空表示全做")


class SubmitIn(BaseModel):
    answers: dict[str, str | list[str]] = Field(default_factory=dict)
    durationMs: int = 0


class HistoryIn(BaseModel):
    packId: str = Field(min_length=1)
    answers: dict[str, str | list[str]] = Field(default_factory=dict)
    finishedAt: int | None = None
    durationMs: int = 0


def _subset(pack, nos: list[int], with_answers: bool) -> dict:
    data = pack.public(with_answers=with_answers)
    keep = set(nos)
    groups = []
    for g in data["questionGroups"]:
        items = [q for q in g["items"] if q["no"] in keep]
        if items:
            g = dict(g)
            g["items"] = items
            groups.append(g)
    data["questionGroups"] = groups
    return data


def _grade(pack, nos: list[int], given: dict, session_id: str, created_at: int) -> dict:
    index = pack.question_index()
    results = []
    for no in nos:
        hit = index.get(no)
        if not hit:
            continue
        group, q = hit
        expected = q.answer_list()
        user = given.get(str(no), given.get(no, ""))
        res = grading.compare(expected, user)
        db.insert_attempt(
            kind="reading_question",
            ref=str(no),
            pack_id=pack.id,
            session_id=session_id,
            input=json.dumps(user, ensure_ascii=False) if isinstance(user, list) else str(user),
            expected="|".join(expected),
            correct=1 if res["ok"] else 0,
            meta=json.dumps({"group": group.id, "type": group.type}, ensure_ascii=False),
            created_at=created_at,
        )
        results.append({
            "no": no,
            "group": group.id,
            "mine": user,
            "answer": expected,
            "correct": res["ok"],
        })
    correct = sum(1 for r in results if r["correct"])
    return {
        "score": correct,
        "total": len(results),
        "accuracy": round(correct / len(results), 4) if results else 0,
        "items": results,
    }


@router.post("/reading/sessions")
def create_session(payload: CreateIn):
    pack = loader.get(payload.packId)
    if not pack:
        raise HTTPException(404, "内容包不存在")
    if pack.doc.kind != "reading" or pack.doc.question_count == 0:
        raise HTTPException(400, "这个内容包没有阅读题")

    index = pack.question_index()
    nos = sorted(set(payload.nos)) if payload.nos else sorted(index)
    missing = [n for n in nos if n not in index]
    if missing:
        raise HTTPException(400, f"题号不存在：{missing}")

    sid = db.new_id("rs")
    now = db.now()
    db.execute(
        "INSERT INTO sessions(id,kind,pack_id,mode,planned,answered,correct,meta,started_at,updated_at)"
        " VALUES(?,?,?,?,?,0,0,?,?,?)",
        (sid, "reading", pack.id, "practice", len(nos),
         json.dumps({"nos": nos}, ensure_ascii=False), now, now),
    )
    return {
        "sessionId": sid,
        "startedAt": now,
        "nos": nos,
        "pack": _subset(pack, nos, with_answers=False),
    }


@router.post("/reading/sessions/{sid}/submit")
def submit(sid: str, payload: SubmitIn):
    row = db.one("SELECT * FROM sessions WHERE id=?", (sid,))
    if not row or row["kind"] != "reading":
        raise HTTPException(404, "练习不存在")
    if row["ended_at"]:
        raise HTTPException(409, "这次练习已交卷")
    pack = loader.get(row["pack_id"])
    if not pack:
        raise HTTPException(409, "内容包已被删除或改名，无法判分")

    meta = json.loads(row["meta"] or "{}")
    nos = meta.get("nos") or sorted(pack.question_index())
    now = db.now()
    graded = _grade(pack, nos, payload.answers, sid, now)
    duration_ms = payload.durationMs or max(0, now - row["started_at"]) * 1000

    db.execute(
        "UPDATE sessions SET answered=?, correct=?, ended_at=?, meta=?, updated_at=? WHERE id=?",
        (graded["total"], graded["score"], now,
         json.dumps({**meta, "answers": payload.answers, "durationMs": duration_ms},
                    ensure_ascii=False), now, sid),
    )
    return {
        "sessionId": sid,
        "durationMs": duration_ms,
        **graded,
        "pack": _subset(pack, nos, with_answers=True),
    }


@router.post("/reading/history")
def import_history(payload: HistoryIn):
    """补录旧页面上的历史成绩（如「剑雅18 T3 P3 · 5/14」）。"""
    pack = loader.get(payload.packId)
    if not pack:
        raise HTTPException(404, "内容包不存在")
    finished = payload.finishedAt or db.now()
    duration_ms = payload.durationMs or 0
    started = finished - int(duration_ms / 1000)
    nos = sorted(pack.question_index())
    sid = db.new_id("rs")

    now = db.now()
    db.execute(
        "INSERT INTO sessions(id,kind,pack_id,mode,planned,answered,correct,meta,started_at,ended_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (sid, "reading", pack.id, "history", len(nos), 0, 0,
         json.dumps({"nos": nos, "imported": True}, ensure_ascii=False), started, finished, now),
    )
    graded = _grade(pack, nos, payload.answers, sid, finished)
    db.execute(
        "UPDATE sessions SET answered=?, correct=?, meta=?, updated_at=? WHERE id=?",
        (graded["total"], graded["score"],
         json.dumps({"nos": nos, "imported": True, "answers": payload.answers,
                     "durationMs": duration_ms}, ensure_ascii=False), now, sid),
    )
    return {"sessionId": sid, **graded}


@router.get("/reading/sessions")
def list_sessions(limit: int = Query(default=20, ge=1, le=100)):
    rows = db.query(
        "SELECT * FROM sessions WHERE kind='reading' AND (answered > 0 OR ended_at IS NOT NULL)"
        " ORDER BY started_at DESC LIMIT ?",
        (limit,),
    )
    return {"items": [
        {
            "sessionId": r["id"],
            "packId": r["pack_id"],
            "mode": r["mode"],
            "score": r["correct"],
            "total": r["planned"],
            "accuracy": round(r["correct"] / r["planned"], 4) if r["planned"] else 0,
            "startedAt": r["started_at"],
            "endedAt": r["ended_at"],
        }
        for r in rows
    ]}
