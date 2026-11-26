-- 小头雅思 · Cloudflare D1 数据库结构（与本地 SQLite 同步协议对齐）

CREATE TABLE IF NOT EXISTS vocab (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  lemma            TEXT    NOT NULL,
  word             TEXT    NOT NULL,
  gloss            TEXT    NOT NULL DEFAULT '',
  pos              TEXT    NOT NULL DEFAULT '',
  phonetic         TEXT    NOT NULL DEFAULT '',
  note             TEXT    NOT NULL DEFAULT '',
  tags             TEXT    NOT NULL DEFAULT '[]',
  contexts         TEXT    NOT NULL DEFAULT '[]',
  source           TEXT    NOT NULL DEFAULT '',
  state            TEXT    NOT NULL DEFAULT 'new',
  due_at           INTEGER NOT NULL DEFAULT 0,
  interval_days    REAL    NOT NULL DEFAULT 0,
  ease             REAL    NOT NULL DEFAULT 2.4,
  reps             INTEGER NOT NULL DEFAULT 0,
  lapses           INTEGER NOT NULL DEFAULT 0,
  last_reviewed_at INTEGER NOT NULL DEFAULT 0,
  created_at       INTEGER NOT NULL,
  updated_at       INTEGER NOT NULL,
  deleted_at       INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_vocab_lemma ON vocab(lemma);
CREATE INDEX IF NOT EXISTS ix_vocab_due ON vocab(state, due_at);
CREATE INDEX IF NOT EXISTS ix_vocab_updated ON vocab(updated_at);

CREATE TABLE IF NOT EXISTS sessions (
  id         TEXT    PRIMARY KEY,
  kind       TEXT    NOT NULL,
  pack_id    TEXT    NOT NULL DEFAULT '',
  mode       TEXT    NOT NULL DEFAULT '',
  planned    INTEGER NOT NULL DEFAULT 0,
  answered   INTEGER NOT NULL DEFAULT 0,
  correct    INTEGER NOT NULL DEFAULT 0,
  meta       TEXT    NOT NULL DEFAULT '{}',
  started_at INTEGER NOT NULL,
  ended_at   INTEGER,
  updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_sessions_started ON sessions(started_at);
CREATE INDEX IF NOT EXISTS ix_sessions_updated ON sessions(updated_at);

CREATE TABLE IF NOT EXISTS attempts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id   TEXT    NOT NULL DEFAULT '',
  kind        TEXT    NOT NULL,
  ref         TEXT    NOT NULL,
  pack_id     TEXT    NOT NULL DEFAULT '',
  session_id  TEXT    NOT NULL DEFAULT '',
  input       TEXT    NOT NULL DEFAULT '',
  expected    TEXT    NOT NULL DEFAULT '',
  correct     INTEGER NOT NULL DEFAULT 0,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  meta        TEXT    NOT NULL DEFAULT '{}',
  created_at  INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_attempts_client_id ON attempts(client_id) WHERE client_id <> '';
CREATE INDEX IF NOT EXISTS ix_attempts_created ON attempts(created_at);
CREATE INDEX IF NOT EXISTS ix_attempts_pack ON attempts(pack_id);

CREATE TABLE IF NOT EXISTS packs (
  id           TEXT    PRIMARY KEY,
  kind         TEXT    NOT NULL DEFAULT 'reading',
  origin       TEXT    NOT NULL DEFAULT 'custom',
  title        TEXT    NOT NULL DEFAULT '',
  mtime        INTEGER NOT NULL DEFAULT 0,
  summary_json TEXT    NOT NULL DEFAULT '{}',
  detail_json  TEXT    NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_packs_mtime ON packs(mtime);
