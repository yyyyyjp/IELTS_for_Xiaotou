"""FastAPI 入口：词书 / 题目 / 发音 / 进度。

开发：uvicorn main:app --reload --port 8000
生产：先 npm run build 生成 web/dist，再直接 python main.py（同一端口托管前端）
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db
import parser
import tts_service

WEB_DIST = db.BASE_DIR.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # 上次没生成完的，启动时接着来
    for row in db.query(
        "SELECT b.id AS book_id, b.voice FROM books b WHERE b.source='import' AND b.id IN"
        " (SELECT DISTINCT book_id FROM questions WHERE audio='' AND source_audio='')"
    ):
        tts_service.start_prepare(row["book_id"], row["voice"])
    yield


app = FastAPI(title="Tifo IELTS Dictation", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- schemas
class CreateBook(BaseModel):
    name: str = ""
    text: str = Field(min_length=1)
    voice: str = tts_service.DEFAULT_VOICE


class ParseReq(BaseModel):
    text: str = Field(min_length=1)


class TTSReq(BaseModel):
    text: str = Field(min_length=1)
    voice: str = tts_service.DEFAULT_VOICE


class ProgressReq(BaseModel):
    questionId: int
    status: str          # todo / correct / wrong / skipped
    attempts: int = 1
    final: str = ""      # direct / rewrite


# ---------------------------------------------------------------- helpers
def question_json(r) -> dict:
    import json

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
    return {r["book_id"]: {"total": r["total"], "done": r["done"], "pending": r["pending"]} for r in rows}


# ---------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    return {"ok": True, "ts": int(time.time())}


@app.get("/api/voices")
def voices():
    return {"default": tts_service.DEFAULT_VOICE, "rate": tts_service.DEFAULT_RATE,
            "items": tts_service.VOICES}


@app.get("/api/books")
def list_books():
    sm = stats_map()
    rows = db.query("SELECT * FROM books ORDER BY source='import' DESC, created_at DESC")
    out = []
    for r in rows:
        item = book_json(r, sm.get(r["id"]))
        if r["source"] == "import":
            item["prepare"] = tts_service.progress_of(r["id"])
        out.append(item)
    return out


@app.get("/api/books/{book_id}")
def get_book(book_id: str):
    r = db.one("SELECT * FROM books WHERE id=?", (book_id,))
    if not r:
        raise HTTPException(404, "词书不存在")
    item = book_json(r, stats_map().get(book_id))
    item["prepare"] = tts_service.progress_of(book_id)
    return item


@app.get("/api/books/{book_id}/questions")
def list_questions(book_id: str):
    if not db.one("SELECT 1 FROM books WHERE id=?", (book_id,)):
        raise HTTPException(404, "词书不存在")
    rows = db.query("SELECT * FROM questions WHERE book_id=? ORDER BY ord", (book_id,))
    return {"items": [question_json(r) for r in rows]}


@app.post("/api/parse")
def parse_only(req: ParseReq):
    items = parser.parse_text(req.text)
    blanks = sum(len(i["answers"]) for i in items)
    return {"count": len(items), "blanks": blanks, "items": items[:20]}


@app.post("/api/books")
async def create_book(req: CreateBook):
    items = parser.parse_text(req.text)
    if not items:
        raise HTTPException(400, "没有解析出任何题目，检查每行是否有英文句子")
    name = req.name.strip() or f"导入 {time.strftime('%m-%d %H:%M')}"
    voice = req.voice or tts_service.DEFAULT_VOICE
    book_id = db.new_id()
    blanks = sum(len(i["answers"]) for i in items)
    db.execute(
        "INSERT INTO books(id,name,intro,source,voice,created_at) VALUES(?,?,?,?,?,?)",
        (book_id, name, f"自定义导入 · {len(items)} 题 · {blanks} 个空", "import", voice,
         int(time.time())),
    )
    import json

    db.executemany(
        "INSERT INTO questions(book_id,ord,text,answers,translation,meaning,title)"
        " VALUES(?,?,?,?,?,?,?)",
        [
            (book_id, i, it["text"], json.dumps(it["answers"], ensure_ascii=False),
             it["translation"], it["meaning"], it["title"])
            for i, it in enumerate(items)
        ],
    )
    tts_service.start_prepare(book_id, voice)
    return {"id": book_id, "name": name, "count": len(items), "blanks": blanks}


@app.delete("/api/books/{book_id}")
def delete_book(book_id: str):
    r = db.one("SELECT source FROM books WHERE id=?", (book_id,))
    if not r:
        raise HTTPException(404, "词书不存在")
    if r["source"] == "builtin":
        raise HTTPException(400, "内置词包不能删除")
    db.execute("DELETE FROM books WHERE id=?", (book_id,))
    return {"ok": True}


@app.post("/api/books/{book_id}/reset")
def reset_book(book_id: str):
    db.execute(
        "UPDATE questions SET status='todo', attempts=0, final='' WHERE book_id=?", (book_id,)
    )
    return {"ok": True}


@app.get("/api/books/{book_id}/prepare")
def prepare_progress(book_id: str):
    return tts_service.progress_of(book_id)


@app.post("/api/tts")
async def make_tts(req: TTSReq):
    name = await tts_service.synthesize(req.text, req.voice)
    if not name:
        raise HTTPException(503, "语音生成失败，请稍后重试")
    return {"url": f"/api/audio/{name}"}


@app.get("/api/audio/{name}")
def get_audio(name: str):
    path = tts_service.audio_path(name)
    if not path:
        raise HTTPException(404, "音频不存在")
    return FileResponse(path, media_type="audio/mpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.post("/api/progress")
def save_progress(req: ProgressReq):
    if req.status not in ("todo", "correct", "wrong", "skipped"):
        raise HTTPException(400, "非法状态")
    db.execute(
        "UPDATE questions SET status=?, attempts=?, final=? WHERE id=?",
        (req.status, req.attempts, req.final, req.questionId),
    )
    return {"ok": True}


# 生产模式：同端口托管打包后的前端
if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIST), html=True), name="web")


@app.exception_handler(404)
async def spa_fallback(request, exc):
    """前端用 history 路由，未知路径回落到 index.html。"""
    index = WEB_DIST / "index.html"
    if request.url.path.startswith("/api") or not index.exists():
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
