-- 无损迁移：将单用户 D1 表升级为多用户按 user_id 隔离结构
-- 原有数据（4 篇精读、生词本、会话与作答记录）全部归属到管理员账号 u_admin（yyyyyjp）。

CREATE TABLE IF NOT EXISTS users (
  id          TEXT    PRIMARY KEY,
  github_id   TEXT    NOT NULL UNIQUE,
  login       TEXT    NOT NULL,
  name        TEXT    NOT NULL DEFAULT '',
  avatar_url  TEXT    NOT NULL DEFAULT '',
  role        TEXT    NOT NULL DEFAULT 'user',
  status      TEXT    NOT NULL DEFAULT 'pending',
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

-- 1. 迁移 vocab
CREATE TABLE vocab_v2 (
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
INSERT INTO vocab_v2(
  id, user_id, lemma, word, gloss, pos, phonetic, note, tags, contexts, source,
  state, due_at, interval_days, ease, reps, lapses, last_reviewed_at, created_at, updated_at, deleted_at
)
SELECT
  id, 'u_admin', lemma, word, gloss, pos, phonetic, note, tags, contexts, source,
  state, due_at, interval_days, ease, reps, lapses, last_reviewed_at, created_at, updated_at, deleted_at
FROM vocab;
DROP TABLE vocab;
ALTER TABLE vocab_v2 RENAME TO vocab;
CREATE UNIQUE INDEX ux_vocab_user_lemma ON vocab(user_id, lemma);
CREATE INDEX ix_vocab_user_due ON vocab(user_id, state, due_at);
CREATE INDEX ix_vocab_user_updated ON vocab(user_id, updated_at);

-- 2. 迁移 sessions（主键改为 (user_id, id)）
CREATE TABLE sessions_v2 (
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
INSERT INTO sessions_v2(
  user_id, id, kind, pack_id, mode, planned, answered, correct, meta, started_at, ended_at, updated_at
)
SELECT
  'u_admin', id, kind, pack_id, mode, planned, answered, correct, meta, started_at, ended_at, updated_at
FROM sessions;
DROP TABLE sessions;
ALTER TABLE sessions_v2 RENAME TO sessions;
CREATE INDEX ix_sessions_user_started ON sessions(user_id, started_at);
CREATE INDEX ix_sessions_user_updated ON sessions(user_id, updated_at);

-- 3. 迁移 attempts
CREATE TABLE attempts_v2 (
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
INSERT INTO attempts_v2(
  id, user_id, client_id, kind, ref, pack_id, session_id, input, expected, correct, duration_ms, meta, created_at
)
SELECT
  id, 'u_admin', client_id, kind, ref, pack_id, session_id, input, expected, correct, duration_ms, meta, created_at
FROM attempts;
DROP TABLE attempts;
ALTER TABLE attempts_v2 RENAME TO attempts;
CREATE UNIQUE INDEX ux_attempts_user_client ON attempts(user_id, client_id) WHERE client_id <> '';
CREATE INDEX ix_attempts_user_created ON attempts(user_id, created_at);
CREATE INDEX ix_attempts_user_pack ON attempts(user_id, pack_id);

-- 4. 迁移 packs（主键改为 (user_id, id)）
CREATE TABLE packs_v2 (
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
INSERT INTO packs_v2(user_id, id, kind, origin, title, mtime, summary_json, detail_json)
SELECT 'u_admin', id, kind, origin, title, mtime, summary_json, detail_json
FROM packs;
DROP TABLE packs;
ALTER TABLE packs_v2 RENAME TO packs;
CREATE INDEX ix_packs_user_mtime ON packs(user_id, mtime);
