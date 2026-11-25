"""增量双向同步接口（Local-First 客户端 ↔ 服务端/云端）。

协议特点（直接与未来 Cloudflare Workers + D1 保持 1:1 兼容）：
1. 单次 HTTP 往返同时完成 Push（批量推送本地 outbox）与 Pull（基于游标的增量拉取），
   最大限度抵消跨网高 RTT 卡顿。
2. 冲突消解：
   - vocab（按唯一键 lemma）：contexts 与 tags 始终取集合并集；状态/SRS/备注/软删除墓碑
     按 updatedAt 最新者胜出（LWW）。
   - sessions（按 UUID id）：按 updatedAt 合并。
   - attempts（按 UUID clientId）：纯追加事件流（INSERT OR IGNORE 幂等去重）。
3. 支持可选口令校验（XIAOTOU_SYNC_TOKEN）：本地未配置时免鉴权，上线公网配置后自动拦截未授权请求。
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

import config
import content.loader as loader
import db
from routers.vocab import STATES, jdump, lemma_key, row_out

router = APIRouter(tags=["sync"])

PULL_ATTEMPTS_LIMIT = 2000


def verify_sync_token(
    authorization: str | None = Header(default=None),
    x_sync_token: str | None = Header(default=None),
) -> None:
    expected = config.SYNC_TOKEN
    if not expected:
        return
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_sync_token:
        token = x_sync_token.strip()
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "同步口令无效或未提供")


class SyncCursor(BaseModel):
    vocab: int = 0
    sessions: int = 0
    attempts: int = 0
    packs: int = 0


class VocabSyncItem(BaseModel):
    lemma: str
    word: str = ""
    gloss: str = ""
    pos: str = ""
    phonetic: str = ""
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    contexts: list[dict] = Field(default_factory=list)
    source: str = ""
    state: str = "new"
    dueAt: int = 0
    intervalDays: float = 0
    ease: float = 2.4
    reps: int = 0
    lapses: int = 0
    lastReviewedAt: int = 0
    createdAt: int = 0
    updatedAt: int = 0
    deletedAt: int = 0


class SessionSyncItem(BaseModel):
    id: str
    kind: str
    packId: str = ""
    mode: str = ""
    planned: int = 0
    answered: int = 0
    correct: int = 0
    meta: dict | str = Field(default_factory=dict)
    startedAt: int
    endedAt: int | None = None
    updatedAt: int = 0


class AttemptSyncItem(BaseModel):
    clientId: str
    kind: str
    ref: str
    packId: str = ""
    sessionId: str = ""
    input: str = ""
    expected: str = ""
    correct: int = 0
    durationMs: int = 0
    meta: dict | str = Field(default_factory=dict)
    createdAt: int = 0


class SyncPushPayload(BaseModel):
    vocab: list[VocabSyncItem] = Field(default_factory=list)
    sessions: list[SessionSyncItem] = Field(default_factory=list)
    attempts: list[AttemptSyncItem] = Field(default_factory=list)


class SyncRequest(BaseModel):
    cursor: SyncCursor = Field(default_factory=SyncCursor)
    push: SyncPushPayload = Field(default_factory=SyncPushPayload)


def _merge_contexts(a: list[dict], b: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for ctx in list(a) + list(b):
        if not isinstance(ctx, dict):
            continue
        key = (
            str(ctx.get("packId") or ""),
            str(ctx.get("sentenceId") or ""),
            str(ctx.get("en") or ""),
        )
        if key == ("", "", "") or key in seen:
            continue
        seen.add(key)
        out.append(ctx)
    return out


def _apply_vocab_item(item: VocabSyncItem, server_now: int) -> bool:
    lemma = lemma_key(item.lemma or item.word)
    if not lemma:
        return False
    state = item.state if item.state in STATES else "new"
    inc_updated = item.updatedAt or server_now
    inc_created = item.createdAt or inc_updated

    row = db.one("SELECT * FROM vocab WHERE lemma=?", (lemma,))
    if not row:
        db.execute(
            "INSERT INTO vocab(lemma,word,gloss,pos,phonetic,note,tags,contexts,source,state,"
            "due_at,interval_days,ease,reps,lapses,last_reviewed_at,created_at,updated_at,deleted_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                lemma,
                item.word or lemma,
                item.gloss,
                item.pos,
                item.phonetic,
                item.note,
                jdump(list(dict.fromkeys(item.tags))),
                jdump(_merge_contexts([], item.contexts)),
                item.source,
                state,
                item.dueAt or inc_created,
                item.intervalDays,
                max(1.3, min(3.0, item.ease or 2.4)),
                max(0, item.reps),
                max(0, item.lapses),
                item.lastReviewedAt or 0,
                inc_created,
                max(inc_updated, server_now),
                item.deletedAt or 0,
            ),
        )
        return True

    old_tags = json.loads(row["tags"] or "[]")
    old_contexts = json.loads(row["contexts"] or "[]")
    merged_tags = list(dict.fromkeys(old_tags + item.tags))
    merged_contexts = _merge_contexts(old_contexts, item.contexts)

    if inc_updated >= (row["updated_at"] or 0):
        # 客户端变更更新（或同秒）：以客户端状态为准，同时保留已有非空释义兜底
        new_updated = max(inc_updated, server_now)
        db.execute(
            "UPDATE vocab SET word=?,gloss=?,pos=?,phonetic=?,note=?,tags=?,contexts=?,source=?,"
            "state=?,due_at=?,interval_days=?,ease=?,reps=?,lapses=?,last_reviewed_at=?,"
            "updated_at=?,deleted_at=? WHERE id=?",
            (
                item.word or row["word"] or lemma,
                item.gloss if item.gloss != "" else row["gloss"],
                item.pos if item.pos != "" else row["pos"],
                item.phonetic if item.phonetic != "" else row["phonetic"],
                item.note,
                jdump(merged_tags),
                jdump(merged_contexts),
                item.source or row["source"],
                state,
                item.dueAt or row["due_at"],
                item.intervalDays,
                max(1.3, min(3.0, item.ease or 2.4)),
                max(0, item.reps),
                max(0, item.lapses),
                item.lastReviewedAt,
                new_updated,
                item.deletedAt or 0,
                row["id"],
            ),
        )
        return True

    # 客户端版本较旧：只合并不冲突的例句和标签，不覆盖较新的复习进度或墓碑
    if len(merged_contexts) != len(old_contexts) or len(merged_tags) != len(old_tags):
        db.execute(
            "UPDATE vocab SET tags=?, contexts=?, updated_at=? WHERE id=?",
            (jdump(merged_tags), jdump(merged_contexts), server_now, row["id"]),
        )
        return True
    return False


def _apply_session_item(item: SessionSyncItem, server_now: int) -> bool:
    if not item.id:
        return False
    meta_str = item.meta if isinstance(item.meta, str) else jdump(item.meta)
    inc_updated = item.updatedAt or item.endedAt or item.startedAt or server_now
    row = db.one("SELECT * FROM sessions WHERE id=?", (item.id,))
    if not row:
        db.execute(
            "INSERT INTO sessions(id,kind,pack_id,mode,planned,answered,correct,meta,started_at,ended_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                item.id,
                item.kind,
                item.packId,
                item.mode,
                item.planned,
                item.answered,
                item.correct,
                meta_str,
                item.startedAt,
                item.endedAt,
                max(inc_updated, server_now),
            ),
        )
        return True

    if inc_updated >= (row["updated_at"] or 0) or (item.endedAt and not row["ended_at"]):
        db.execute(
            "UPDATE sessions SET answered=?,correct=?,meta=?,ended_at=?,updated_at=? WHERE id=?",
            (
                max(row["answered"] or 0, item.answered),
                max(row["correct"] or 0, item.correct),
                meta_str,
                item.endedAt or row["ended_at"],
                max(inc_updated, server_now),
                item.id,
            ),
        )
        return True
    return False


def _apply_attempt_item(item: AttemptSyncItem, server_now: int) -> bool:
    if not item.clientId or not item.kind:
        return False
    existing = db.one("SELECT id FROM attempts WHERE client_id=?", (item.clientId,))
    if existing:
        return False
    meta_str = item.meta if isinstance(item.meta, str) else jdump(item.meta)
    db.insert_attempt(
        client_id=item.clientId,
        kind=item.kind,
        ref=item.ref,
        pack_id=item.packId,
        session_id=item.sessionId,
        input=item.input,
        expected=item.expected,
        correct=1 if item.correct else 0,
        duration_ms=item.durationMs,
        meta=meta_str,
        created_at=item.createdAt or server_now,
    )
    return True


def _session_out(r) -> dict:
    meta_raw = r["meta"] or "{}"
    try:
        meta = json.loads(meta_raw)
    except Exception:
        meta = {}
    return {
        "id": r["id"],
        "kind": r["kind"],
        "packId": r["pack_id"],
        "mode": r["mode"],
        "planned": r["planned"],
        "answered": r["answered"],
        "correct": r["correct"],
        "meta": meta,
        "startedAt": r["started_at"],
        "endedAt": r["ended_at"],
        "updatedAt": r["updated_at"] or r["ended_at"] or r["started_at"],
    }


def _attempt_out(r) -> dict:
    meta_raw = r["meta"] or "{}"
    try:
        meta = json.loads(meta_raw)
    except Exception:
        meta = {}
    return {
        "seq": r["id"],
        "clientId": r["client_id"] or f"legacy-{r['id']}",
        "kind": r["kind"],
        "ref": r["ref"],
        "packId": r["pack_id"],
        "sessionId": r["session_id"],
        "input": r["input"],
        "expected": r["expected"],
        "correct": r["correct"],
        "durationMs": r["duration_ms"],
        "meta": meta,
        "createdAt": r["created_at"],
    }


@router.post("/sync")
def sync_endpoint(
    req: SyncRequest,
    authorization: str | None = Header(default=None),
    x_sync_token: str | None = Header(default=None),
):
    verify_sync_token(authorization, x_sync_token)
    now = db.now()

    pushed_vocab = sum(1 for it in req.push.vocab if _apply_vocab_item(it, now))
    pushed_sessions = sum(1 for it in req.push.sessions if _apply_session_item(it, now))
    pushed_attempts = sum(1 for it in req.push.attempts if _apply_attempt_item(it, now))

    # 增量拉取（注意：为防止同一秒内的并发写入漏拉，若无新记录则保持原游标）
    v_rows = db.query(
        "SELECT * FROM vocab WHERE updated_at > ? ORDER BY updated_at ASC, id ASC",
        (req.cursor.vocab,),
    )
    s_rows = db.query(
        "SELECT * FROM sessions WHERE updated_at > ? ORDER BY updated_at ASC, id ASC",
        (req.cursor.sessions,),
    )
    a_rows = db.query(
        "SELECT * FROM attempts WHERE id > ? ORDER BY id ASC LIMIT ?",
        (req.cursor.attempts, PULL_ATTEMPTS_LIMIT + 1),
    )
    has_more_attempts = len(a_rows) > PULL_ATTEMPTS_LIMIT
    if has_more_attempts:
        a_rows = a_rows[:PULL_ATTEMPTS_LIMIT]

    all_packs = loader.all_packs()
    changed_packs = []
    max_pack_mtime = req.cursor.packs
    for p in all_packs.values():
        mt = int(p.mtime)
        if mt > max_pack_mtime:
            max_pack_mtime = mt
        if mt > req.cursor.packs:
            changed_packs.append({"id": p.id, "mtime": mt, "summary": p.summary()})

    next_cursor = {
        "vocab": max([req.cursor.vocab] + [int(r["updated_at"] or 0) for r in v_rows]),
        "sessions": max([req.cursor.sessions] + [int(r["updated_at"] or 0) for r in s_rows]),
        "attempts": max([req.cursor.attempts] + [int(r["id"]) for r in a_rows]),
        "packs": max_pack_mtime,
    }

    return {
        "ok": True,
        "serverTs": now,
        "authRequired": bool(config.SYNC_TOKEN),
        "pushed": {
            "vocab": pushed_vocab,
            "sessions": pushed_sessions,
            "attempts": pushed_attempts,
        },
        "pull": {
            "vocab": [row_out(r) for r in v_rows],
            "sessions": [_session_out(r) for r in s_rows],
            "attempts": [_attempt_out(r) for r in a_rows],
            "packs": changed_packs,
            "allPackIds": sorted(all_packs.keys()),
            "hasMore": has_more_attempts,
        },
        "cursor": next_cursor,
    }


@router.get("/sync/export")
def export_full_snapshot(
    authorization: str | None = Header(default=None),
    x_sync_token: str | None = Header(default=None),
):
    """导出全量学习状态快照（生词本 + 会话 + 作答事件），用于跨端迁移与离线兜底备份。"""
    verify_sync_token(authorization, x_sync_token)
    v_rows = db.query("SELECT * FROM vocab ORDER BY id ASC")
    s_rows = db.query("SELECT * FROM sessions ORDER BY started_at ASC")
    a_rows = db.query("SELECT * FROM attempts ORDER BY id ASC")
    return {
        "schemaVersion": 2,
        "exportedAt": db.now(),
        "vocab": [row_out(r) for r in v_rows],
        "sessions": [_session_out(r) for r in s_rows],
        "attempts": [_attempt_out(r) for r in a_rows],
    }


@router.post("/sync/import")
def import_full_snapshot(
    payload: dict[str, Any],
    authorization: str | None = Header(default=None),
    x_sync_token: str | None = Header(default=None),
):
    """幂等恢复全量备份快照。"""
    verify_sync_token(authorization, x_sync_token)
    now = db.now()
    vocab_in = [VocabSyncItem.model_validate(x) for x in (payload.get("vocab") or [])]
    sessions_in = [SessionSyncItem.model_validate(x) for x in (payload.get("sessions") or [])]
    attempts_in = [AttemptSyncItem.model_validate(x) for x in (payload.get("attempts") or [])]

    v_n = sum(1 for it in vocab_in if _apply_vocab_item(it, now))
    s_n = sum(1 for it in sessions_in if _apply_session_item(it, now))
    a_n = sum(1 for it in attempts_in if _apply_attempt_item(it, now))
    return {"ok": True, "merged": {"vocab": v_n, "sessions": s_n, "attempts": a_n}}
