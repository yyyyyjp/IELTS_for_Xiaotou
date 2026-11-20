"""SQLite 存取层。

设计原则：
- **内容不是数据**。篇目/题目/词表放在 content/packs/*.json，随 git 走版本；
  数据库只存「学习记录」（作答事件、会话、生词本与复习状态），所以内容改版
  不需要写迁移，删库也不会丢教材。
- **记录是事件流**。每次作答写一条 attempts，而不是覆盖题目的 status 字段；
  这样才能回答「哪天练了什么、哪个词错了几次」。
- 迁移用 PRAGMA user_version 递进，MIGRATIONS 只追加、不修改历史项。
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from pathlib import Path

import config

BASE_DIR = config.BASE_DIR
DATA_DIR = config.DATA_DIR
AUDIO_DIR = config.AUDIO_DIR
DB_PATH = config.DB_PATH

MIGRATION_1 = """
CREATE TABLE IF NOT EXISTS vocab (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  lemma            TEXT    NOT NULL,              -- 归一化后的词头，唯一键
  word             TEXT    NOT NULL,              -- 首次收录时的原形（可能是复数/变形）
  gloss            TEXT    NOT NULL DEFAULT '',   -- 释义
  pos              TEXT    NOT NULL DEFAULT '',   -- 词性
  phonetic         TEXT    NOT NULL DEFAULT '',
  note             TEXT    NOT NULL DEFAULT '',
  tags             TEXT    NOT NULL DEFAULT '[]',
  contexts         TEXT    NOT NULL DEFAULT '[]', -- [{packId,sentenceId,en,zh,para}]
  source           TEXT    NOT NULL DEFAULT '',   -- 首次出处，如「剑雅18 · Test 3 · Passage 3」
  state            TEXT    NOT NULL DEFAULT 'new',-- new | learning | review | suspended
  due_at           INTEGER NOT NULL DEFAULT 0,
  interval_days    REAL    NOT NULL DEFAULT 0,
  ease             REAL    NOT NULL DEFAULT 2.4,
  reps             INTEGER NOT NULL DEFAULT 0,
  lapses           INTEGER NOT NULL DEFAULT 0,
  last_reviewed_at INTEGER NOT NULL DEFAULT 0,
  created_at       INTEGER NOT NULL,
  updated_at       INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_vocab_lemma ON vocab(lemma);
CREATE INDEX IF NOT EXISTS ix_vocab_due ON vocab(state, due_at);

CREATE TABLE IF NOT EXISTS sessions (
  id         TEXT    PRIMARY KEY,
  kind       TEXT    NOT NULL,                    -- dictation | reading
  pack_id    TEXT    NOT NULL DEFAULT '',
  mode       TEXT    NOT NULL DEFAULT '',
  planned    INTEGER NOT NULL DEFAULT 0,
  answered   INTEGER NOT NULL DEFAULT 0,
  correct    INTEGER NOT NULL DEFAULT 0,
  meta       TEXT    NOT NULL DEFAULT '{}',
  started_at INTEGER NOT NULL,
  ended_at   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_sessions_started ON sessions(started_at);

CREATE TABLE IF NOT EXISTS attempts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  kind        TEXT    NOT NULL,                   -- dictation_word | dictation_sentence | reading_question | vocab_review
  ref         TEXT    NOT NULL,                   -- 词（小写） / 句子 id / 题号
  pack_id     TEXT    NOT NULL DEFAULT '',
  session_id  TEXT    NOT NULL DEFAULT '',
  input       TEXT    NOT NULL DEFAULT '',
  expected    TEXT    NOT NULL DEFAULT '',
  correct     INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  meta        TEXT    NOT NULL DEFAULT '{}',
  created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attempts_created ON attempts(created_at);
CREATE INDEX IF NOT EXISTS ix_attempts_kind_created ON attempts(kind, created_at);
CREATE INDEX IF NOT EXISTS ix_attempts_pack ON attempts(pack_id);
CREATE INDEX IF NOT EXISTS ix_attempts_ref ON attempts(ref);
CREATE INDEX IF NOT EXISTS ix_attempts_session ON attempts(session_id);

-- ↓ 旧版（句子听写）表，随 routers/legacy.py 一起退役，新代码不要再用
CREATE TABLE IF NOT EXISTS books (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  intro       TEXT NOT NULL DEFAULT '',
  source      TEXT NOT NULL DEFAULT 'import',
  voice       TEXT NOT NULL DEFAULT 'en-GB-SoniaNeural',
  created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id      TEXT NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  ord          INTEGER NOT NULL,
  text         TEXT NOT NULL,
  answers      TEXT NOT NULL,
  translation  TEXT NOT NULL DEFAULT '',
  meaning      TEXT NOT NULL DEFAULT '',
  title        TEXT NOT NULL DEFAULT '句子听写',
  audio        TEXT NOT NULL DEFAULT '',
  source_audio TEXT NOT NULL DEFAULT '',
  status       TEXT NOT NULL DEFAULT 'todo',
  attempts     INTEGER NOT NULL DEFAULT 0,
  final        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_q_book ON questions(book_id, ord);
CREATE INDEX IF NOT EXISTS idx_q_audio ON questions(audio);
"""

MIGRATIONS = [MIGRATION_1]

_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("PRAGMA foreign_keys=ON")
_conn.execute("PRAGMA busy_timeout=5000")
_LOCK = threading.RLock()


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _LOCK:
        return _conn.execute(sql, params).fetchall()


def one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    with _LOCK:
        return _conn.execute(sql, params).fetchone()


def scalar(sql: str, params: tuple = (), default=0):
    row = one(sql, params)
    if row is None:
        return default
    v = row[0]
    return default if v is None else v


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    with _LOCK:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur


def executemany(sql: str, seq) -> None:
    with _LOCK:
        _conn.executemany(sql, seq)
        _conn.commit()


def insert_attempt(**kw) -> int:
    """写一条作答记录。字段缺省即用默认值，避免每个调用点重复。"""
    row = {
        "kind": "",
        "ref": "",
        "pack_id": "",
        "session_id": "",
        "input": "",
        "expected": "",
        "correct": 0,
        "duration_ms": 0,
        "meta": "{}",
        "created_at": now(),
    }
    row.update({k: v for k, v in kw.items() if v is not None})
    cur = execute(
        "INSERT INTO attempts(kind,ref,pack_id,session_id,input,expected,correct,"
        "duration_ms,meta,created_at) VALUES(:kind,:ref,:pack_id,:session_id,:input,"
        ":expected,:correct,:duration_ms,:meta,:created_at)",
        row,
    )
    return int(cur.lastrowid or 0)


def new_id(prefix: str = "b") -> str:
    return prefix + uuid.uuid4().hex[:10]


def now() -> int:
    return int(time.time())


def init_db() -> None:
    with _LOCK:
        version = _conn.execute("PRAGMA user_version").fetchone()[0]
        for i in range(version, len(MIGRATIONS)):
            _conn.executescript(MIGRATIONS[i])
            _conn.execute(f"PRAGMA user_version={i + 1}")
            _conn.commit()


def db_version() -> int:
    return int(_conn.execute("PRAGMA user_version").fetchone()[0])


def audio_path(name: str) -> Path | None:
    """音频文件名 → 路径，挡掉路径穿越。"""
    if not name or "/" in name or "\\" in name or ".." in name:
        return None
    p = AUDIO_DIR / name
    return p if p.exists() else None
