"""发音：音色列表、按需合成、批量预热、音频投递。"""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import config
import db
import tts_service

router = APIRouter(tags=["media"])

RATE_RE = re.compile(r"^[+-]\d{1,2}%$")
AUDIO_HEADERS = {"Cache-Control": "public, max-age=31536000, immutable"}


def _check_voice(voice: str) -> str:
    if voice not in tts_service.VOICE_IDS:
        raise HTTPException(400, f"未知音色：{voice}")
    return voice


def _check_rate(rate: str) -> str:
    if not RATE_RE.fullmatch(rate):
        raise HTTPException(400, "语速格式应为 -10% ~ +10%")
    return rate


@router.get("/voices")
def list_voices():
    return {"default": tts_service.DEFAULT_VOICE, "rate": tts_service.DEFAULT_RATE,
            "items": tts_service.VOICES}


@router.get("/audio/{name}")
def get_audio(name: str):
    path = db.audio_path(name)
    if not path:
        raise HTTPException(404, "音频不存在")
    return FileResponse(path, media_type="audio/mpeg", headers=AUDIO_HEADERS)


@router.get("/tts/audio")
async def tts_audio(
    text: str = Query(..., min_length=1, max_length=config.TTS_MAX_CHARS),
    voice: str = Query(default=tts_service.DEFAULT_VOICE),
    rate: str = Query(default=tts_service.DEFAULT_RATE),
):
    """直接返回 mp3。缓存命中时几乎没有延迟，前端可以当普通音频地址用。"""
    _check_voice(voice)
    _check_rate(rate)
    name = await tts_service.synthesize(text, voice, rate)
    if not name:
        raise HTTPException(503, "语音生成失败，请稍后重试")
    return FileResponse(config.AUDIO_DIR / name, media_type="audio/mpeg", headers=AUDIO_HEADERS)


class TTSReq(BaseModel):
    text: str = Field(min_length=1, max_length=config.TTS_MAX_CHARS)
    voice: str = tts_service.DEFAULT_VOICE


@router.post("/tts")
async def make_tts(req: TTSReq):
    name = await tts_service.synthesize(req.text, _check_voice(req.voice))
    if not name:
        raise HTTPException(503, "语音生成失败，请稍后重试")
    return {"url": f"/api/audio/{name}"}


class BatchReq(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=config.TTS_MAX_BATCH)
    voice: str = tts_service.DEFAULT_VOICE


@router.post("/tts/batch")
async def batch_tts(req: BatchReq):
    """预生成。练习前调一次，之后播放就没有等待。"""
    voice = _check_voice(req.voice)
    texts = [t.strip() for t in req.texts if t and t.strip()][: config.TTS_MAX_BATCH]
    for t in texts:
        if len(t) > config.TTS_MAX_CHARS:
            raise HTTPException(400, f"文本过长：{t[:30]}…")
    stat = await tts_service.prepare(texts, voice)
    items = []
    for t in texts:
        name = tts_service.cached(t, voice)
        items.append({"text": t, "ok": bool(name),
                      "url": f"/api/audio/{name}" if name else ""})
    return {"items": items, **stat}
