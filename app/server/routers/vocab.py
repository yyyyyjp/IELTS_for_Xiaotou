"""生词本：收词、去重、复习队列、导入导出。

一个词头只存一条（lemma 唯一），不同篇目遇到同一个词只追加 context，
不重复建卡——否则复习队列会被同一个词塞满。
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

import db
import services.srs as srs
import tts_service

router = APIRouter(tags=["vocab"])

STATES = ("new", "learning", "review", "suspended")


def jdump(v) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def lemma_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())[:80]


class ContextIn(BaseModel):
    packId: str = ""
    sentenceId: str = ""
    en: str = ""
    zh: str = ""
    para: int = 0


class VocabIn(BaseModel):
    lemma: str = ""
    word: str = ""
    gloss: str = ""
    pos: str = ""
    phonetic: str = ""
    note: str = ""
    source: str = ""
    src: str = ""                 # 旧版 HTML 生词本字段名
    tags: list[str] = Field(default_factory=list)
    packId: str = ""
    context: str | ContextIn | None = None   # 允许直接传例句字符串
    zh: str = ""
    para: int = 0
    sentId: str = ""
    ts: int | None = None          # 旧版时间戳（毫秒）
    createdAt: int | None = None   # 秒


class VocabPatch(BaseModel):
    note: str | None = None
    gloss: str | None = None
    tags: list[str] | None = None
    state: str | None = None


class ReviewIn(BaseModel):
    grade: str
    durationMs: int = 0


class ImportIn(BaseModel):
    items: list[VocabIn] = Field(default_factory=list)
    packId: str = ""


def _context_of(payload: VocabIn) -> dict | None:
    ctx = payload.context
    pack_id = payload.packId
    if isinstance(ctx, ContextIn):
        d = ctx.model_dump()
    elif isinstance(ctx, str):
        d = {"en": ctx, "zh": payload.zh, "para": payload.para,
             "sentenceId": payload.sentId, "packId": pack_id}
    elif payload.zh or payload.sentId:
        d = {"en": "", "zh": payload.zh, "para": payload.para,
             "sentenceId": payload.sentId, "packId": pack_id}
    else:
        return None
    if not d.get("packId"):
        d["packId"] = pack_id
    if not d.get("en") and not d.get("zh"):
        return None
    return d


def row_out(r) -> dict:
    now = db.now()
    state = r["state"]
    due_at = r["due_at"] or 0
    audio_name = tts_service.cached(r["word"] or r["lemma"])
    return {
        "id": r["id"],
        "lemma": r["lemma"],
        "word": r["word"],
        "gloss": r["gloss"],
        "pos": r["pos"],
        "phonetic": r["phonetic"],
        "note": r["note"],
        "tags": json.loads(r["tags"] or "[]"),
        "contexts": json.loads(r["contexts"] or "[]"),
        "source": r["source"],
        "state": state,
        "dueAt": due_at,
        "due": state != "suspended" and due_at <= now,
        "intervalDays": r["interval_days"],
        "ease": r["ease"],
        "reps": r["reps"],
        "lapses": r["lapses"],
        "lastReviewedAt": r["last_reviewed_at"],
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
        "deletedAt": r["deleted_at"] if "deleted_at" in r.keys() else 0,
        "audioUrl": f"/api/audio/{audio_name}" if audio_name else "",
        "audioCached": bool(audio_name),
    }


def _merge(row, payload: VocabIn, ctx: dict | None) -> None:
    """已有卡片：只补空缺，不覆盖手工编辑过的内容。"""
    old_contexts = json.loads(row["contexts"] or "[]")
    contexts = list(old_contexts)
    if ctx and not any(c.get("packId") == ctx.get("packId")
                       and c.get("sentenceId") == ctx.get("sentenceId")
                       for c in contexts):
        contexts.append(ctx)
    tags = list(dict.fromkeys(json.loads(row["tags"] or "[]") + payload.tags))
    db.execute(
        "UPDATE vocab SET word=?,gloss=?,pos=?,phonetic=?,source=?,tags=?,contexts=?,updated_at=?"
        " WHERE id=?",
        (row["word"] or payload.word or payload.lemma,
         row["gloss"] or payload.gloss,
         row["pos"] or payload.pos,
         row["phonetic"] or payload.phonetic,
         row["source"] or payload.source or payload.src,
         jdump(tags), jdump(contexts), db.now(), row["id"]),
    )


def upsert(payload: VocabIn, pack_id: str = "") -> tuple[int, bool]:
    lemma = lemma_key(payload.lemma or payload.word)
    if not lemma:
        raise ValueError("缺少单词")
    if not payload.lemma:
        payload.lemma = lemma
    if pack_id and not payload.packId:
        payload.packId = pack_id
    ctx = _context_of(payload)
    ts = payload.createdAt
    if ts is None and payload.ts:
        ts = int(payload.ts / 1000) if payload.ts > 10_000_000_000 else int(payload.ts)
    now = db.now()
    created = ts or now

    row = db.one("SELECT * FROM vocab WHERE lemma=?", (lemma,))
    if row:
        if (row["deleted_at"] or 0) > 0:
            # 曾软删除过的词重新收录：复活并重置为新卡
            db.execute(
                "UPDATE vocab SET word=?,gloss=?,pos=?,phonetic=?,note=?,tags=?,contexts=?,source=?,"
                "state='new',due_at=?,interval_days=0,ease=2.4,reps=0,lapses=0,last_reviewed_at=0,"
                "created_at=?,updated_at=?,deleted_at=0 WHERE id=?",
                (payload.word or payload.lemma, payload.gloss, payload.pos, payload.phonetic,
                 payload.note, jdump(payload.tags), jdump([ctx] if ctx else []),
                 payload.source or payload.src, created, created, now, row["id"]),
            )
            return int(row["id"]), True
        _merge(row, payload, ctx)
        return int(row["id"]), False

    try:
        cur = db.execute(
            "INSERT INTO vocab(lemma,word,gloss,pos,phonetic,note,tags,contexts,source,state,"
            "due_at,interval_days,ease,reps,lapses,last_reviewed_at,created_at,updated_at,deleted_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,'new',?,0,2.4,0,0,0,?,?,0)",
            (lemma, payload.word or payload.lemma, payload.gloss, payload.pos, payload.phonetic,
             payload.note, jdump(payload.tags), jdump([ctx] if ctx else []),
             payload.source or payload.src, created, created, now),
        )
    except sqlite3.IntegrityError:
        # 并发双击：另一个请求刚插进去，退化成合并
        row = db.one("SELECT * FROM vocab WHERE lemma=?", (lemma,))
        if row:
            _merge(row, payload, ctx)
            return int(row["id"]), False
        raise
    return int(cur.lastrowid or 0), True


@router.get("/vocab")
def list_vocab(
    q: str = Query(default="", max_length=100),
    packId: str = Query(default=""),
    state: str = Query(default=""),
    due: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    where, params = ["deleted_at = 0"], []
    if q:
        where.append("(lemma LIKE ? OR gloss LIKE ? OR contexts LIKE ?)")
        kw = f"%{q}%"
        params += [kw, kw, kw]
    if packId:
        where.append("instr(contexts, ?) > 0")
        params.append(f'"packId":"{packId}"')
    if state:
        if state not in STATES:
            raise HTTPException(400, "非法状态")
        where.append("state = ?")
        params.append(state)
    if due:
        where.append("state != 'suspended' AND due_at <= ?")
        params.append(db.now())
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.scalar(f"SELECT COUNT(*) FROM vocab{sql_where}", tuple(params))
    rows = db.query(
        f"SELECT * FROM vocab{sql_where} ORDER BY due_at ASC, updated_at DESC LIMIT ? OFFSET ?",
        tuple(params) + (limit, offset),
    )
    return {"total": total, "items": [row_out(r) for r in rows]}


@router.post("/vocab")
def add_vocab(payload: VocabIn):
    try:
        vid, created = upsert(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    row = db.one("SELECT * FROM vocab WHERE id=?", (vid,))
    return {"created": created, "item": row_out(row)}


@router.patch("/vocab/{vid}")
def patch_vocab(vid: int, payload: VocabPatch):
    row = db.one("SELECT * FROM vocab WHERE id=? AND deleted_at=0", (vid,))
    if not row:
        raise HTTPException(404, "生词不存在")
    sets, params = [], []
    if payload.note is not None:
        sets.append("note=?")
        params.append(payload.note)
    if payload.gloss is not None:
        sets.append("gloss=?")
        params.append(payload.gloss)
    if payload.tags is not None:
        sets.append("tags=?")
        params.append(jdump(payload.tags))
    if payload.state is not None:
        if payload.state not in STATES:
            raise HTTPException(400, "非法状态")
        sets.append("state=?")
        params.append(payload.state)
    if sets:
        sets.append("updated_at=?")
        params.append(db.now())
        db.execute(f"UPDATE vocab SET {','.join(sets)} WHERE id=?", tuple(params) + (vid,))
    return {"item": row_out(db.one("SELECT * FROM vocab WHERE id=?", (vid,)))}


@router.delete("/vocab/{vid}")
def delete_vocab(vid: int):
    now = db.now()
    cur = db.execute(
        "UPDATE vocab SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at=0",
        (now, now, vid),
    )
    if cur.rowcount == 0:
        raise HTTPException(404, "生词不存在")
    return {"ok": True}


@router.get("/vocab/review")
def review_queue(limit: int = Query(default=20, ge=1, le=200), includeNew: bool = True):
    where = "deleted_at = 0 AND state != 'suspended' AND due_at <= ?"
    if not includeNew:
        where += " AND state != 'new'"
    rows = db.query(
        f"SELECT * FROM vocab WHERE {where} ORDER BY due_at ASC, id ASC LIMIT ?",
        (db.now(), limit),
    )
    return {"items": [row_out(r) for r in rows]}


@router.post("/vocab/{vid}/review")
def review_vocab(vid: int, payload: ReviewIn):
    row = db.one("SELECT * FROM vocab WHERE id=? AND deleted_at=0", (vid,))
    if not row:
        raise HTTPException(404, "生词不存在")
    now = db.now()
    try:
        nxt = srs.review(dict(row), payload.grade, now)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    db.execute(
        "UPDATE vocab SET state=?,ease=?,interval_days=?,reps=?,lapses=?,due_at=?,"
        "last_reviewed_at=?,updated_at=? WHERE id=?",
        (nxt["state"], nxt["ease"], nxt["interval_days"], nxt["reps"], nxt["lapses"],
         nxt["due_at"], nxt["last_reviewed_at"], now, vid),
    )
    db.insert_attempt(
        kind="vocab_review",
        ref=row["lemma"],
        input=payload.grade,
        expected="",
        correct=0 if payload.grade == "again" else 1,
        duration_ms=payload.durationMs,
        meta=jdump({"vocabId": vid, "grade": payload.grade,
                    "intervalDays": nxt["interval_days"]}),
        created_at=now,
    )
    return {
        "item": row_out(db.one("SELECT * FROM vocab WHERE id=?", (vid,))),
        "nextDueAt": nxt["due_at"],
        "intervalDays": nxt["interval_days"],
        "state": nxt["state"],
    }


@router.get("/vocab/stats")
def vocab_stats():
    now = db.now()
    total = db.scalar("SELECT COUNT(*) FROM vocab WHERE deleted_at = 0")
    rows = db.query("SELECT state, COUNT(*) n FROM vocab WHERE deleted_at = 0 GROUP BY state")
    by_state = {r["state"]: r["n"] for r in rows}
    due_now = db.scalar(
        "SELECT COUNT(*) FROM vocab WHERE deleted_at = 0 AND state != 'suspended' AND due_at <= ?",
        (now,),
    )
    added_today = db.scalar(
        "SELECT COUNT(*) FROM vocab WHERE deleted_at = 0 AND date(created_at,'unixepoch','localtime')"
        " = date('now','localtime')"
    )
    return {
        "total": total,
        "byState": {s: by_state.get(s, 0) for s in STATES},
        "dueNow": due_now,
        "addedToday": added_today,
    }


@router.post("/vocab/import")
def import_vocab(payload: ImportIn):
    created = merged = skipped = 0
    ids = []
    for item in payload.items:
        try:
            vid, is_new = upsert(item, payload.packId)
        except ValueError:
            skipped += 1
            continue
        ids.append(vid)
        created += 1 if is_new else 0
        merged += 0 if is_new else 1
    return {"created": created, "merged": merged, "skipped": skipped, "ids": ids}


@router.get("/vocab/export")
def export_vocab(format: str = Query(default="json", pattern="^(json|csv)$")):
    rows = db.query("SELECT * FROM vocab WHERE deleted_at = 0 ORDER BY created_at ASC")
    if format == "json":
        return {"items": [row_out(r) for r in rows]}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["lemma", "word", "pos", "gloss", "note", "state", "dueAt",
                     "reps", "lapses", "context", "contextZh", "source", "createdAt"])
    for r in rows:
        out = row_out(r)
        ctx = out["contexts"][0] if out["contexts"] else {}
        writer.writerow([out["lemma"], out["word"], out["pos"], out["gloss"], out["note"],
                         out["state"], out["dueAt"], out["reps"], out["lapses"],
                         ctx.get("en", ""), ctx.get("zh", ""), out["source"],
                         out["createdAt"]])
    data = "\ufeff" + buf.getvalue()
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=vocab.csv"},
    )
