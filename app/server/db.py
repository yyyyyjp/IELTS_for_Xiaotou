"""SQLite 存取层。单文件数据库，随项目走，无需额外服务。"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
AUDIO_DIR = DATA_DIR / "audio"
DB_PATH = DATA_DIR / "app.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  intro       TEXT NOT NULL DEFAULT '',
  source      TEXT NOT NULL DEFAULT 'import',
  voice       TEXT NOT NULL DEFAULT 'en-GB-SoniaNeural',
  created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id     TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  ord         INTEGER NOT NULL,
  text        TEXT NOT NULL,
  answers     TEXT NOT NULL,              -- JSON array
  translation TEXT NOT NULL DEFAULT '',
  meaning     TEXT NOT NULL DEFAULT '',
  title       TEXT NOT NULL DEFAULT '句子听写',
  audio       TEXT NOT NULL DEFAULT '',    -- 文件名，空表示未生成
  source_audio TEXT NOT NULL DEFAULT '',   -- 外部现成 mp3 直链（内置真题用）
  status      TEXT NOT NULL DEFAULT 'todo',
  attempts    INTEGER NOT NULL DEFAULT 0,
  final       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_q_book ON questions(book_id, ord);
CREATE INDEX IF NOT EXISTS idx_q_audio ON questions(audio);
"""

_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("PRAGMA foreign_keys=ON")


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return _conn.execute(sql, params).fetchall()


def one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return _conn.execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    cur = _conn.execute(sql, params)
    _conn.commit()
    return cur


def executemany(sql: str, seq) -> None:
    _conn.executemany(sql, seq)
    _conn.commit()


def new_id(prefix: str = "b") -> str:
    return prefix + uuid.uuid4().hex[:10]


def init_db() -> None:
    _conn.executescript(SCHEMA)
    _conn.commit()
    _seed_builtin()


# 内置示例词包：来自 prototype/data.js 的真实抓包（含真人录音直链）
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


def _seed_builtin() -> None:
    if one("SELECT 1 FROM books WHERE id='builtin'"):
        return
    execute(
        "INSERT INTO books(id,name,intro,source,voice,created_at) VALUES(?,?,?,?,?,?)",
        ("builtin", "内置真题包 · 住房与住宿服务",
         "to-8 抓包真实数据 · 5 题 · 真人录音", "builtin", "en-GB-SoniaNeural", int(time.time())),
    )
    rows = []
    for i, (word, text, cn, meaning, pos, ph, audio, img) in enumerate(BUILTIN):
        rows.append((None, "builtin", i, text, json.dumps([word], ensure_ascii=False),
                     cn, f"{pos} {ph} {meaning}", "听力真题原文", "", audio))
    executemany(
        "INSERT INTO questions(book_id,ord,text,answers,translation,meaning,title,audio,source_audio)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        [r[1:] for r in rows],
    )
