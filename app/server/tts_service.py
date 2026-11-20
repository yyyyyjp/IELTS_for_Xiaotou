"""用微软 Edge 的神经网络 TTS 生成 mp3，落盘缓存。

同一个「文本 + 音色 + 语速」只生成一次，文件名是内容哈希，
所以改词、改音色都会自然产生新文件，不需要清缓存。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging

import edge_tts

import config

log = logging.getLogger("tts")

DEFAULT_VOICE = config.DEFAULT_VOICE
DEFAULT_RATE = config.DEFAULT_RATE
CONCURRENCY = config.TTS_CONCURRENCY

VOICES = [
    {"id": "en-GB-SoniaNeural", "label": "英音女声 Sonia（最接近雅思）", "lang": "en-GB"},
    {"id": "en-GB-LibbyNeural", "label": "英音女声 Libby", "lang": "en-GB"},
    {"id": "en-GB-MaisieNeural", "label": "英音女声 Maisie（年轻）", "lang": "en-GB"},
    {"id": "en-GB-RyanNeural", "label": "英音男声 Ryan", "lang": "en-GB"},
    {"id": "en-GB-ThomasNeural", "label": "英音男声 Thomas", "lang": "en-GB"},
    {"id": "en-AU-NatashaNeural", "label": "澳音女声 Natasha", "lang": "en-AU"},
    {"id": "en-AU-WilliamNeural", "label": "澳音男声 William", "lang": "en-AU"},
]

VOICE_IDS = {v["id"] for v in VOICES}


def cache_name(text: str, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE) -> str:
    key = hashlib.md5(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:20]
    return f"{key}.mp3"


def cached(text: str, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE) -> str | None:
    name = cache_name(text, voice, rate)
    p = config.AUDIO_DIR / name
    return name if p.exists() and p.stat().st_size > 1024 else None


async def synthesize(text: str, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE) -> str | None:
    """生成（或复用）音频，返回文件名；失败返回 None。"""
    text = (text or "").strip()
    if not text:
        return None
    hit = cached(text, voice, rate)
    if hit:
        return hit

    name = cache_name(text, voice, rate)
    path = config.AUDIO_DIR / name
    tmp = config.AUDIO_DIR / (name + ".part")
    for attempt in range(3):
        try:
            await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp))
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


async def prepare(texts: list[str], voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE,
                  on_done=None) -> dict:
    """并发预生成一批文本。on_done(done, total, failed) 用于上报进度。"""
    todo = [t for t in dict.fromkeys((t or "").strip() for t in texts) if t]
    total, done, failed = len(todo), 0, 0
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(text: str) -> bool:
        nonlocal done, failed
        async with sem:
            name = await synthesize(text, voice, rate)
            done += 1
            if not name:
                failed += 1
            if on_done:
                on_done(done, total, failed)
            return bool(name)

    results = await asyncio.gather(*(one(t) for t in todo)) if todo else []
    return {"total": total, "done": done, "failed": failed,
            "ok": sum(1 for r in results if r)}
