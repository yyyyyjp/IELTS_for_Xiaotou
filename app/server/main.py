"""FastAPI 入口。

开发：uvicorn main:app --reload --port 8000
生产：先 npm run build 生成 web/dist，再 python main.py（同端口托管前端）
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config
import content.loader as loader
import db
import services.dictionary as dictionary
import tts_service
from routers import (
    dictation,
    dictionary as dictionary_router,
    legacy,
    media,
    packs,
    reading,
    stats,
    sync as sync_router,
    vocab,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    legacy.seed()
    loaded = loader.load_all(force=True)
    dstat = dictionary.status()
    dict_msg = f"离线词典 {dstat['entries']:,} 条" if dstat["ready"] else "离线词典未安装（仅用文章词表）"
    print(f"[xiaotou] 内容包 {len(loaded)} 个；{dict_msg}；音频缓存目录 {config.AUDIO_DIR}")
    for name, err in loader.errors().items():
        print(f"[xiaotou] 内容包有误 {name}: {err}")
    legacy.resume_pending()   # 上次没生成完的音频接着来
    yield


app = FastAPI(title="小头雅思 · 备考记录", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router in (packs.router, vocab.router, dictation.router, reading.router,
                stats.router, media.router, dictionary_router.router, sync_router.router,
                legacy.router):
    app.include_router(_router, prefix="/api")


@app.get("/api/health")
def health():
    dstat = dictionary.status()
    return {
        "ok": True,
        "ts": int(time.time()),
        "dbVersion": db.db_version(),
        "packs": {"loaded": len(loader.all_packs()), "errors": loader.errors()},
        "dict": {"ready": dstat["ready"], "entries": dstat["entries"]},
        "audio": {
            "defaultVoice": tts_service.DEFAULT_VOICE,
            "cached": len(list(config.AUDIO_DIR.glob("*.mp3"))),
        },
    }


# 生产模式：同端口托管打包后的前端
if config.WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(config.WEB_DIST), html=True), name="web")


@app.exception_handler(404)
async def spa_fallback(request, exc):
    """前端用 history 路由，未知路径回落到 index.html。"""
    index = config.WEB_DIST / "index.html"
    if request.url.path.startswith("/api") or not index.exists():
        detail = getattr(exc, "detail", "Not Found")
        return JSONResponse({"detail": detail}, status_code=404)
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
