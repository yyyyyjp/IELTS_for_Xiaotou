"""备考记录：今日概览、连续天数、每日趋势、分篇目进度、易错词。

所有数字都从 attempts / sessions 现算，不维护汇总表——
汇总表迟早会和事实表对不上，而个人站点的数据量根本不需要预聚合。
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query

import content.loader as loader
import db

router = APIRouter(tags=["stats"])

KINDS = ("dictation", "reading", "review")
MAX_DAYS = 365


def _today() -> str:
    return date.today().isoformat()


def _daily(days: int) -> dict[str, dict]:
    since = db.now() - days * 86400
    rows = db.query(
        "SELECT date(created_at,'unixepoch','localtime') d, kind,"
        " COUNT(*) n, SUM(correct) c"
        " FROM attempts WHERE created_at >= ? GROUP BY d, kind",
        (since,),
    )
    out: dict[str, dict] = {}
    for r in rows:
        bucket = out.setdefault(r["d"], {
            "date": r["d"],
            "dictation": {"attempts": 0, "correct": 0},
            "reading": {"answered": 0, "correct": 0},
            "review": 0,
            "attempts": 0,
            "correct": 0,
            "minutes": 0,
        })
        kind = r["kind"] or ""
        n, c = r["n"] or 0, r["c"] or 0
        if kind.startswith("dictation"):
            bucket["dictation"]["attempts"] += n
            bucket["dictation"]["correct"] += c
        elif kind == "reading_question":
            bucket["reading"]["answered"] += n
            bucket["reading"]["correct"] += c
        elif kind == "vocab_review":
            bucket["review"] += n
        bucket["attempts"] += n
        bucket["correct"] += c

    mins = db.query(
        "SELECT date(started_at,'unixepoch','localtime') d,"
        " SUM(COALESCE(ended_at, started_at) - started_at) secs"
        " FROM sessions WHERE ended_at IS NOT NULL AND started_at >= ? GROUP BY d",
        (since,),
    )
    for r in mins:
        bucket = out.setdefault(r["d"], {
            "date": r["d"],
            "dictation": {"attempts": 0, "correct": 0},
            "reading": {"answered": 0, "correct": 0},
            "review": 0,
            "attempts": 0,
            "correct": 0,
            "minutes": 0,
        })
        bucket["minutes"] = round((r["secs"] or 0) / 60, 1)
    return out


def _streak(days: set[str]) -> tuple[int, int]:
    if not days:
        return 0, 0
    ordered = sorted(days)
    longest = run = 1
    for prev, cur in zip(ordered, ordered[1:]):
        run = run + 1 if (date.fromisoformat(cur) - date.fromisoformat(prev)).days == 1 else 1
        longest = max(longest, run)

    cursor = date.today()
    if cursor.isoformat() not in days:
        cursor -= timedelta(days=1)
    current = 0
    while cursor.isoformat() in days:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


@router.get("/stats/overview")
def overview():
    daily = _daily(1)
    today = _today()
    t = daily.get(today, {
        "dictation": {"attempts": 0, "correct": 0},
        "reading": {"answered": 0, "correct": 0},
        "review": 0, "attempts": 0, "correct": 0, "minutes": 0,
    })
    day_rows = db.query(
        "SELECT DISTINCT date(created_at,'unixepoch','localtime') d FROM attempts"
    )
    all_days = {r["d"] for r in day_rows if r["d"]}
    current, longest = _streak(all_days)

    attempts_today = t["attempts"]
    correct_today = t["correct"]
    now = db.now()
    return {
        "date": today,
        "today": {
            "attempts": attempts_today,
            "correct": correct_today,
            "accuracy": round(correct_today / attempts_today, 4) if attempts_today else 0,
            "minutes": t["minutes"],
            "dictation": t["dictation"],
            "reading": t["reading"],
            "review": t["review"],
        },
        "streak": {"current": current, "longest": longest, "studyDays": len(all_days)},
        "totals": {
            "words": db.scalar("SELECT COUNT(*) FROM vocab"),
            "dueNow": db.scalar(
                "SELECT COUNT(*) FROM vocab WHERE state != 'suspended' AND due_at <= ?", (now,)),
            "attempts": db.scalar("SELECT COUNT(*) FROM attempts"),
            "correct": db.scalar("SELECT COALESCE(SUM(correct),0) FROM attempts"),
            "dictationAttempts": db.scalar(
                "SELECT COUNT(*) FROM attempts WHERE kind LIKE 'dictation_%'"),
            "readingQuestions": db.scalar(
                "SELECT COUNT(*) FROM attempts WHERE kind='reading_question'"),
            "packs": len(loader.all_packs()),
        },
        "lastStudyAt": db.scalar("SELECT MAX(created_at) FROM attempts", default=None),
    }


@router.get("/stats/daily")
def daily(days: int = Query(default=30, ge=1, le=MAX_DAYS)):
    data = _daily(days)
    start = date.today() - timedelta(days=days - 1)
    items = []
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        items.append(data.get(d, {
            "date": d,
            "dictation": {"attempts": 0, "correct": 0},
            "reading": {"answered": 0, "correct": 0},
            "review": 0, "attempts": 0, "correct": 0, "minutes": 0,
        }))
    return {"from": items[0]["date"], "to": items[-1]["date"], "items": items}


@router.get("/stats/packs")
def pack_stats():
    rows = db.query(
        "SELECT pack_id,"
        " SUM(CASE WHEN kind LIKE 'dictation_%' THEN 1 ELSE 0 END) AS d_n,"
        " SUM(CASE WHEN kind LIKE 'dictation_%' AND correct=1 THEN 1 ELSE 0 END) AS d_c,"
        " SUM(CASE WHEN kind='reading_question' THEN 1 ELSE 0 END) AS r_n,"
        " SUM(CASE WHEN kind='reading_question' AND correct=1 THEN 1 ELSE 0 END) AS r_c,"
        " MAX(created_at) AS last"
        " FROM attempts WHERE pack_id<>'' GROUP BY pack_id"
    )
    by_pack = {r["pack_id"]: r for r in rows}
    best = db.query(
        "SELECT pack_id, MAX(correct * 1.0 / planned) AS best"
        " FROM sessions WHERE kind='reading' AND planned > 0 AND answered > 0"
        " GROUP BY pack_id"
    )
    best_map = {r["pack_id"]: r["best"] for r in best}

    out = []
    for p in loader.all_packs().values():
        r = by_pack.get(p.id)
        s = p.summary()
        s["stats"] = {
            "dictation": {"attempts": (r["d_n"] or 0) if r else 0,
                          "correct": (r["d_c"] or 0) if r else 0},
            "reading": {"answered": (r["r_n"] or 0) if r else 0,
                        "correct": (r["r_c"] or 0) if r else 0},
            "bestScore": round(best_map[p.id], 4) if p.id in best_map else None,
            "lastAt": r["last"] if r else None,
        }
        out.append(s)
    out.sort(key=lambda x: x["stats"]["lastAt"] or 0, reverse=True)
    return {"items": out}


@router.get("/stats/weak-words")
def weak_words(limit: int = Query(default=20, ge=1, le=100)):
    rows = db.query(
        "SELECT ref, COUNT(*) n, SUM(correct) c FROM attempts"
        " WHERE kind='dictation_word' GROUP BY ref HAVING SUM(correct) < COUNT(*)",
        (),
    )
    ranked = sorted(
        (
            {"word": r["ref"], "attempts": r["n"], "wrong": r["n"] - (r["c"] or 0)}
            for r in rows
        ),
        key=lambda x: (-x["wrong"], -x["attempts"]),
    )[:limit]

    out = []
    for item in ranked:
        v = db.one("SELECT id, lemma, word, gloss, pos, state FROM vocab WHERE lemma=?",
                   (item["word"],))
        out.append({**item,
                    "gloss": v["gloss"] if v else "",
                    "pos": v["pos"] if v else "",
                    "vocabId": v["id"] if v else None})
    return {"items": out}


@router.get("/stats/kinds")
def kinds():
    """给前端作图例用。"""
    return {"items": [
        {"kind": "dictation_word", "label": "单词听写"},
        {"kind": "dictation_sentence", "label": "句子听写"},
        {"kind": "reading_question", "label": "阅读题"},
        {"kind": "vocab_review", "label": "复习"},
    ]}
