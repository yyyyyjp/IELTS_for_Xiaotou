"""用微软 Edge 的神经网络 TTS 生成 mp3，落盘缓存。

设计要点：
- 同一句（同音色、同语速）只生成一次，缓存命中直接返回文件名
- 导入词书后后台并发预生成，前端轮询进度
- 生成失败重试 3 次，仍失败则返回 None，由前端回退浏览器合成
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

import edge_tts

import db

log = logging.getLogger("tts")

DEFAULT_VOICE = "en-GB-SoniaNeural"
DEFAULT_RATE = "-5%"  # 0.95 倍速，雅思听力约 150 wpm
CONCURRENCY = 4

VOICES = [
    {"id": "en-GB-SoniaNeural", "label": "英音女声 Sonia（最接近雅思）", "lang": "en-GB"},
    {"id": "en-GB-LibbyNeural", "label": "英音女声 Libby", "lang": "en-GB"},
    {"id": "en-GB-MaisieNeural", "label": "英音女声 Maisie（年轻）", "lang": "en-GB"},
    {"id": "en-GB-RyanNeural", "label": "英音男声 Ryan", "lang": "en-GB"},
    {"id": "en-GB-ThomasNeural", "label": "英音男声 Thomas", "lang": "en-GB"},
    {"id": "en-AU-NatashaNeural", "label": "澳音女声 Natasha", "lang": "en-AU"},
    {"id": "en-AU-WilliamNeural", "label": "澳音男声 William", "lang": "en-AU"},
]

# book_id -> {"total": n, "done": n, "failed": n, "ready": bool}
_progress: dict[str, dict] = {}
_tasks: dict[str, asyncio.Task] = {}


def cache_name(text: str, voice: str, rate: str = DEFAULT_RATE) -> str:
    key = hashlib.md5(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:20]
    return f"{key}.mp3"


async def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE) -> str | None:
    """生成（或复用）音频，返回文件名；失败返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    name = cache_name(text, voice, rate)
    path = db.AUDIO_DIR / name
    if path.exists() and path.stat().st_size > 1024:
        return name

    tmp = db.AUDIO_DIR / (name + ".part")
    for attempt in range(3):
        try:
            comm = edge_tts.Communicate(text, voice, rate=rate)
            await comm.save(str(tmp))
            if tmp.exists() and tmp.stat().st_size > 1024:
                tmp.replace(path)
                return name
        except Exception as exc:  # 网络抖动 / 接口限流
            log.warning("tts failed (%s/%s) %s: %s", attempt + 1, 3, name, exc)
            await asyncio.sleep(1.2 * (attempt + 1))
        finally:
            if tmp.exists() and not path.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
    return None


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

    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(item: dict) -> None:
        async with sem:
            name = await synthesize(item["text"], voice)
            if name:
                db.execute("UPDATE questions SET audio=? WHERE id=?", (name, item["id"]))
            else:
                prog["failed"] += 1
            prog["done"] += 1

    try:
        await asyncio.gather(*(one(i) for i in items))
    finally:
        prog["ready"] = True


def start_prepare(book_id: str, voice: str = DEFAULT_VOICE) -> None:
    """启动后台预生成（幂等：同一本书不重复起任务）。"""
    task = _tasks.get(book_id)
    if task and not task.done():
        return
    _progress[book_id] = {"total": 0, "done": 0, "failed": 0, "ready": False}
    _tasks[book_id] = asyncio.create_task(_run_book(book_id, voice))


def progress_of(book_id: str) -> dict:
    return _progress.get(book_id, {"total": 0, "done": 0, "failed": 0, "ready": True})


def audio_path(name: str) -> Path | None:
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    p = db.AUDIO_DIR / name
    return p if p.exists() else None
