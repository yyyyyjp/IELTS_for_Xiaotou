"""旧版「句子听写」接口，冻结保留。

新前端上线后整个文件连同 db.MIGRATION_1 里的 books/questions 一起删掉即可；
在此期间旧页面仍能正常用，不因为改架构而中断。
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import db
import parser
import tts_service

router = APIRouter(tags=["legacy"])

_progress: dict[str, dict] = {}
_tasks: dict[str, asyncio.Task] = {}


class CreateBook(BaseModel):
    name: str = ""
    text: str = Field(min_length=1)
    voice: str = tts_service.DEFAULT_VOICE


class ParseReq(BaseModel):
    text: str = Field(min_length=1)


class ProgressReq(BaseModel):
    questionId: int
    status: str
    attempts: int = 1
    final: str = ""


def question_json(r) -> dict:
    answers = json.loads(r["answers"]) if r["answers"] else []
    audio = r["audio"]
    return {
        "id": r["id"],
        "bookId": r["book_id"],
        "ord": r["ord"],
        "text": r["text"],
        "answers": answers,
        "translation": r["translation"],
        "meaning": r["meaning"],
        "title": r["title"],
        "audioUrl": f"/api/audio/{audio}" if audio else "",
        "sourceAudio": r["source_audio"],
        "status": r["status"],
        "attempts": r["attempts"],
        "final": r["final"],
    }


def book_json(r, stat: dict | None = None) -> dict:
    stat = stat or {}
    return {
        "id": r["id"],
        "name": r["name"],
        "intro": r["intro"],
        "voice": r["voice"],
        "source": r["source"],
        "createdAt": r["created_at"],
        "total": stat.get("total", 0),
        "done": stat.get("done", 0),
        "pendingAudio": stat.get("pending", 0),
    }


def stats_map() -> dict[str, dict]:
    rows = db.query(
        "SELECT book_id, COUNT(*) AS total,"
        " SUM(CASE WHEN status='correct' THEN 1 ELSE 0 END) AS done,"
        " SUM(CASE WHEN audio='' AND source_audio='' THEN 1 ELSE 0 END) AS pending"
        " FROM questions GROUP BY book_id"
    )
    return {r["book_id"]: {"total": r["total"], "done": r["done"], "pending": r["pending"]}
            for r in rows}


async def _run_book(book_id: str, voice: str) -> None:
    rows = db.query(
        "SELECT id, text FROM questions WHERE book_id=? AND audio='' AND source_audio=''",
        (book_id,),
    )
    items = [dict(r) for r in rows]
    prog = _progress.setdefault(book_id, {"total": 0, "done": 0, "failed": 0, "ready": False})
    prog.update(total=len(items), done=0, failed=0, ready=(len(items) == 0))
    if not items:
        return
    sem = asyncio.Semaphore(tts_service.CONCURRENCY)

    async def one(item: dict) -> None:
        async with sem:
            name = await tts_service.synthesize(item["text"], voice)
            if name:
                db.execute("UPDATE questions SET audio=? WHERE id=?", (name, item["id"]))
            else:
                prog["failed"] += 1
            prog["done"] += 1

    try:
        await asyncio.gather(*(one(i) for i in items))
    finally:
        prog["ready"] = True


def start_prepare(book_id: str, voice: str = tts_service.DEFAULT_VOICE) -> None:
    task = _tasks.get(book_id)
    if task and not task.done():
        return
    _progress[book_id] = {"total": 0, "done": 0, "failed": 0, "ready": False}
    _tasks[book_id] = asyncio.create_task(_run_book(book_id, voice))


def progress_of(book_id: str) -> dict:
    return _progress.get(book_id, {"total": 0, "done": 0, "failed": 0, "ready": True})


def resume_pending() -> None:
    for row in db.query(
        "SELECT b.id AS book_id, b.voice FROM books b WHERE b.source='import' AND b.id IN"
        " (SELECT DISTINCT book_id FROM questions WHERE audio='' AND source_audio='')"
    ):
        start_prepare(row["book_id"], row["voice"])


# 内置示例词包：来自早期抓包的真实录音直链
BUILTIN = [
    ("statement", "Your monthly statement has been sent to your email.",
     "您的月度对账单已发送至您的电子邮箱。", "对账单/账目清单", "名词", "/ˈsteɪtmənt/",
     "https://to8mini.oss-accelerate.aliyuncs.com/audio/dictation/phrase_dict-20044-Rupert-uk.mp3?v=26073101",
     "https://to8mini.oss-accelerate.aliyuncs.com/assets/img/phrase_dict_dictation/20044_69cf59478aa1d.jpg"),
    ("authorisation", "Please ensure you have the landlord's authorisation before painting the walls.",
     "在粉刷墙壁之前，请确保你已获得房东的授权。", "授权", "名词", "/ˌɔːθəraɪˈzeɪʃn/",
     "https://to8mini.oss-accelerate.aliyuncs.com/audio/dictation/phrase_dict-20045-Victoria-uk.mp3?v=26073101",
     "https://to8mini.oss-accelerate.aliyuncs.com/assets/img/phrase_dict_dictation/20045_69cf595719d55.jpg"),
    ("disposal", "The apartment has a convenient system for waste disposal.",
     "这套公寓配有一个便捷的垃圾处理系统。", "处理/清理", "名词", "/dɪˈspəʊzl/",
     "https://to8mini.oss-accelerate.aliyuncs.com/audio/dictation/phrase_dict-20046-Ronald-uk.mp3?v=26073101",
     "https://to8mini.oss-accelerate.aliyuncs.com/assets/img/phrase_dict_dictation/20046_69cf5966eb7c6.jpg"),
    ("recycling", "Please use the blue bins for paper recycling.",
     "请使用蓝色垃圾桶进行纸张回收。", "回收利用", "名词", "/ˌriːˈsaɪklɪŋ/",
     "https://to8mini.oss-accelerate.aliyuncs.com/audio/dictation/phrase_dict-1952-Ronald-uk.mp3?v=26073101",
     "https://to8mini.oss-accelerate.aliyuncs.com/assets/img/phrase_dict_dictation/1952_69cf4190ae736.jpg"),
    ("complaint", "I'd like to make a complaint about the noise.",
     "我想投诉噪音问题。", "投诉", "名词", "/kəmˈpleɪnt/",
     "https://to8mini.oss-accelerate.aliyuncs.com/audio/dictation/phrase_dict-6544-Duncan-uk.mp3?v=26073101",
     "https://to8mini.oss-accelerate.aliyuncs.com/assets/img/phrase_dict_dictation/6544_69cf4d1d28547.jpg"),
]


def seed() -> None:
    if db.one("SELECT 1 FROM books WHERE id='builtin'"):
        return
    db.execute(
        "INSERT INTO books(id,name,intro,source,voice,created_at) VALUES(?,?,?,?,?,?)",
        ("builtin", "内置真题包 · 住房与住宿服务",
         "to-8 抓包真实数据 · 5 题 · 真人录音", "builtin", tts_service.DEFAULT_VOICE, db.now()),
    )
    db.executemany(
        "INSERT INTO questions(book_id,ord,text,answers,translation,meaning,title,audio,source_audio)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        [("builtin", i, text, json.dumps([word], ensure_ascii=False), cn,
          f"{pos} {ph} {meaning}", "听力真题原文", "", audio)
         for i, (word, text, cn, meaning, pos, ph, audio, _img) in enumerate(BUILTIN)],
    )


@router.get("/books")
def list_books():
    sm = stats_map()
    rows = db.query("SELECT * FROM books ORDER BY source='import' DESC, created_at DESC")
    out = []
    for r in rows:
        item = book_json(r, sm.get(r["id"]))
        if r["source"] == "import":
            item["prepare"] = progress_of(r["id"])
        out.append(item)
    return out


@router.get("/books/{book_id}")
def get_book(book_id: str):
    r = db.one("SELECT * FROM books WHERE id=?", (book_id,))
    if not r:
        raise HTTPException(404, "词书不存在")
    item = book_json(r, stats_map().get(book_id))
    item["prepare"] = progress_of(book_id)
    return item


@router.get("/books/{book_id}/questions")
def list_questions(book_id: str):
    if not db.one("SELECT 1 FROM books WHERE id=?", (book_id,)):
        raise HTTPException(404, "词书不存在")
    rows = db.query("SELECT * FROM questions WHERE book_id=? ORDER BY ord", (book_id,))
    return {"items": [question_json(r) for r in rows]}


@router.post("/parse")
def parse_only(req: ParseReq):
    items = parser.parse_text(req.text)
    blanks = sum(len(i["answers"]) for i in items)
    return {"count": len(items), "blanks": blanks, "items": items[:20]}


@router.post("/books")
async def create_book(req: CreateBook):
    items = parser.parse_text(req.text)
    if not items:
        raise HTTPException(400, "没有解析出任何题目，检查每行是否有英文句子")
    name = req.name.strip() or f"导入 {time.strftime('%m-%d %H:%M')}"
    book_id = db.new_id()
    blanks = sum(len(i["answers"]) for i in items)
    db.execute(
        "INSERT INTO books(id,name,intro,source,voice,created_at) VALUES(?,?,?,?,?,?)",
        (book_id, name, f"自定义导入 · {len(items)} 题 · {blanks} 个空", "import",
         req.voice or tts_service.DEFAULT_VOICE, db.now()),
    )
    db.executemany(
        "INSERT INTO questions(book_id,ord,text,answers,translation,meaning,title)"
        " VALUES(?,?,?,?,?,?,?)",
        [(book_id, i, it["text"], json.dumps(it["answers"], ensure_ascii=False),
          it["translation"], it["meaning"], it["title"]) for i, it in enumerate(items)],
    )
    start_prepare(book_id, req.voice or tts_service.DEFAULT_VOICE)
    return {"id": book_id, "name": name, "count": len(items), "blanks": blanks}


@router.delete("/books/{book_id}")
def delete_book(book_id: str):
    r = db.one("SELECT source FROM books WHERE id=?", (book_id,))
    if not r:
        raise HTTPException(404, "词书不存在")
    if r["source"] == "builtin":
        raise HTTPException(400, "内置词包不能删除")
    db.execute("DELETE FROM books WHERE id=?", (book_id,))
    return {"ok": True}


@router.post("/books/{book_id}/reset")
def reset_book(book_id: str):
    db.execute("UPDATE questions SET status='todo', attempts=0, final='' WHERE book_id=?",
               (book_id,))
    return {"ok": True}


@router.get("/books/{book_id}/prepare")
def prepare_progress(book_id: str):
    return progress_of(book_id)


@router.post("/progress")
def save_progress(req: ProgressReq):
    if req.status not in ("todo", "correct", "wrong", "skipped"):
        raise HTTPException(400, "非法状态")
    db.execute("UPDATE questions SET status=?, attempts=?, final=? WHERE id=?",
               (req.status, req.attempts, req.final, req.questionId))
    return {"ok": True}
