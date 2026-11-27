-- 小头雅思 · Cloudflare D1 多用户数据库结构（v2）
-- 每个用户的原文、作答、复盘、生词与练习统计全部按 user_id 严格隔离。

CREATE TABLE IF NOT EXISTS users (
  id          TEXT    PRIMARY KEY,
  github_id   TEXT    NOT NULL UNIQUE,
  login       TEXT    NOT NULL,
  name        TEXT    NOT NULL DEFAULT '',
  avatar_url  TEXT    NOT NULL DEFAULT '',
  role        TEXT    NOT NULL DEFAULT 'user',    -- admin | user
  status      TEXT    NOT NULL DEFAULT 'pending', -- active | pending
  invite_code TEXT    NOT NULL DEFAULT '',
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_users_login ON users(login);

CREATE TABLE IF NOT EXISTS invites (
  code        TEXT    PRIMARY KEY,
  max_uses    INTEGER NOT NULL DEFAULT 1,
  used_count  INTEGER NOT NULL DEFAULT 0,
  created_by  TEXT    NOT NULL DEFAULT '',
  note        TEXT    NOT NULL DEFAULT '',
  created_at  INTEGER NOT NULL,
  revoked_at  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_invites_created ON invites(created_at);

CREATE TABLE IF NOT EXISTS vocab (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id          TEXT    NOT NULL,
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
CREATE UNIQUE INDEX IF NOT EXISTS ux_vocab_user_lemma ON vocab(user_id, lemma);
CREATE INDEX IF NOT EXISTS ix_vocab_user_due ON vocab(user_id, state, due_at);
CREATE INDEX IF NOT EXISTS ix_vocab_user_updated ON vocab(user_id, updated_at);

CREATE TABLE IF NOT EXISTS sessions (
  user_id    TEXT    NOT NULL,
  id         TEXT    NOT NULL,
  kind       TEXT    NOT NULL,
  pack_id    TEXT    NOT NULL DEFAULT '',
  mode       TEXT    NOT NULL DEFAULT '',
  planned    INTEGER NOT NULL DEFAULT 0,
  answered   INTEGER NOT NULL DEFAULT 0,
  correct    INTEGER NOT NULL DEFAULT 0,
  meta       TEXT    NOT NULL DEFAULT '{}',
  started_at INTEGER NOT NULL,
  ended_at   INTEGER,
  updated_at INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS ix_sessions_user_started ON sessions(user_id, started_at);
CREATE INDEX IF NOT EXISTS ix_sessions_user_updated ON sessions(user_id, updated_at);

CREATE TABLE IF NOT EXISTS attempts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     TEXT    NOT NULL,
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
CREATE UNIQUE INDEX IF NOT EXISTS ux_attempts_user_client ON attempts(user_id, client_id) WHERE client_id <> '';
CREATE INDEX IF NOT EXISTS ix_attempts_user_created ON attempts(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_attempts_user_pack ON attempts(user_id, pack_id);

CREATE TABLE IF NOT EXISTS packs (
  user_id      TEXT    NOT NULL,
  id           TEXT    NOT NULL,
  kind         TEXT    NOT NULL DEFAULT 'reading',
  origin       TEXT    NOT NULL DEFAULT 'custom',
  title        TEXT    NOT NULL DEFAULT '',
  mtime        INTEGER NOT NULL DEFAULT 0,
  summary_json TEXT    NOT NULL DEFAULT '{}',
  detail_json  TEXT    NOT NULL DEFAULT '{}',
  PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS ix_packs_user_mtime ON packs(user_id, mtime);

-- 公共只读核心词典（6.6 万高频/雅思/学术词），支持云端 ~250B 极速单次查词
CREATE TABLE IF NOT EXISTS dict (
  word_lower TEXT    PRIMARY KEY,
  word       TEXT    NOT NULL,
  phonetic   TEXT    NOT NULL DEFAULT '',
  trans      TEXT    NOT NULL DEFAULT '',
  tag        TEXT    NOT NULL DEFAULT '',
  flags      INTEGER NOT NULL DEFAULT 0,
  exchange   TEXT    NOT NULL DEFAULT ''
);
