"""本地离线词典服务（基于 ECDICT SQLite + 内容包 pack.lexicon 优先）。

分层查询顺序：
1. 当前文章包 pack.lexicon（语境优先，若命中则保留为首选释义，同时用 ECDICT 补全音标/标签/全义）
2. 本地 ECDICT SQLite（支持精确匹配、大小写/连字符规范匹配、exchange 词根追溯、规则词形还原、英美拼写转换）
3. 短语拆解兜底（2–6 个词且整段未命中时，拆分实词逐个查 ECDICT，返回 tokens 供前端展示）
"""
from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

import config
import content.loader as loader
import db

_local = threading.local()
_cached_path: str = ""
_cached_mtime: float = -1.0
_cached_count: int = 0

EDGE_PUNCT_RE = re.compile(r"^[^A-Za-z0-9]+|[^A-Za-z0-9]+$")
POS_LINE_RE = re.compile(r"^([a-z]{1,6}\.(?:\s*/\s*[a-z]{1,6}\.)*)\s+(.+)$", re.I)
WORD_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
LEADING_DET_RE = re.compile(r"^(?:the|a|an|to|this|that|these|those)\s+", re.I)

STOPWORDS = frozenset({
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "by", "with", "from",
    "as", "is", "am", "are", "was", "were", "be", "been", "being", "and", "or",
    "but", "if", "it", "its", "this", "that", "these", "those", "he", "she",
    "they", "we", "you", "i", "me", "him", "her", "us", "them", "my", "your",
    "his", "their", "our", "not", "no", "so", "than", "then", "into", "onto",
})

TAG_ORDER = ("ielts", "toefl", "gre", "cet6", "cet4", "ky", "gk", "zk")

FORM_CODE_LABELS = {
    "p": "过去式",
    "d": "过去分词",
    "i": "现在分词",
    "3": "第三人称单数",
    "r": "比较级",
    "t": "最高级",
    "s": "复数",
}

UK_TO_US_RULES = (
    ("isation", "ization"),
    ("isations", "izations"),
    ("ising", "izing"),
    ("ised", "ized"),
    ("ises", "izes"),
    ("ise", "ize"),
    ("our", "or"),
    ("ours", "ors"),
    ("oured", "ored"),
    ("ouring", "oring"),
    ("re", "er"),
    ("elling", "eling"),
    ("elled", "eled"),
    ("ence", "ense"),
    ("logue", "log"),
)


def strip_word(word: str) -> str:
    """与 ECDICT 官方一致的 sw 计算：只保留字母数字并小写。"""
    return "".join(ch for ch in word if ch.isalnum()).lower()


def clean_query(raw: str) -> str:
    text = (raw or "").replace("\u2019", "'").replace("\u2018", "'").replace("\u2014", "-")
    text = re.sub(r"\s+", " ", text).strip()
    text = EDGE_PUNCT_RE.sub("", text).strip()
    return text[:120]


def _dict_path() -> Path:
    return config.DICT_DB_PATH


def _get_conn() -> sqlite3.Connection | None:
    """返回只读 ECDICT SQLite 连接；文件不存在或不可用时返回 None。"""
    path = _dict_path()
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None

    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    conn_key = getattr(_local, "key", None)
    cur_key = (str(path), mtime)
    if conn is not None and conn_key == cur_key:
        return conn

    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass

    try:
        uri = f"{path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _local.conn = conn
        _local.key = cur_key
        return conn
    except sqlite3.Error:
        _local.conn = None
        _local.key = None
        return None


def reset_connection() -> None:
    """测试切换字典文件时重置缓存连接。"""
    global _cached_path, _cached_mtime, _cached_count
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _local.conn = None
    _local.key = None
    _cached_path = ""
    _cached_mtime = -1.0
    _cached_count = 0


def status() -> dict:
    """词典就绪状态（供 /api/dict/status 与 /api/health 使用）。"""
    global _cached_path, _cached_mtime, _cached_count
    path = _dict_path()
    if not path.exists():
        return {"ready": False, "entries": 0, "path": str(path)}
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"ready": False, "entries": 0, "path": str(path)}

    if _cached_path == str(path) and _cached_mtime == mtime:
        return {"ready": _cached_count > 0, "entries": _cached_count, "path": str(path)}

    conn = _get_conn()
    if conn is None:
        return {"ready": False, "entries": 0, "path": str(path)}
    try:
        row = conn.execute("SELECT COUNT(*) FROM stardict").fetchone()
        count = int(row[0]) if row else 0
    except sqlite3.Error:
        return {"ready": False, "entries": 0, "path": str(path)}

    _cached_path = str(path)
    _cached_mtime = mtime
    _cached_count = count
    return {"ready": count > 0, "entries": count, "path": str(path)}


def _normalize_multiline(text: str | None) -> str:
    if not text:
        return ""
    s = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in s.split("\n") if line.strip()]
    return "\n".join(lines)


def _extract_pos_and_gloss(translation: str) -> tuple[str, str]:
    cleaned = _normalize_multiline(translation)
    if not cleaned:
        return "", ""
    poses: list[str] = []
    for line in cleaned.split("\n"):
        m = POS_LINE_RE.match(line)
        if m:
            p = m.group(1).strip()
            if p not in poses:
                poses.append(p)
    pos = " / ".join(poses[:3])
    return pos, cleaned


def _parse_exchange(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split("/"):
        if ":" in part:
            k, v = part.split(":", 1)
            k, v = k.strip(), v.strip()
            if k and v:
                out[k] = v
    return out


def _describe_form(lemma: str, code: str) -> str:
    if not lemma or not code:
        return ""
    labels: list[str] = []
    for ch in code:
        lbl = FORM_CODE_LABELS.get(ch)
        if lbl and lbl not in labels:
            labels.append(lbl)
    if not labels:
        return f"原型：{lemma}"
    return f"{lemma} 的{'/'.join(labels)}"


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    seen = {t.lower() for t in raw.split() if t.strip()}
    return [t for t in TAG_ORDER if t in seen]


def _query_exact(conn: sqlite3.Connection, word: str) -> sqlite3.Row | None:
    row = conn.execute(
        "SELECT word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange"
        " FROM stardict WHERE word = ? LIMIT 1",
        (word,),
    ).fetchone()
    if row:
        return row
    low = word.lower()
    if low != word:
        row = conn.execute(
            "SELECT word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange"
            " FROM stardict WHERE word = ? LIMIT 1",
            (low,),
        ).fetchone()
        if row:
            return row
    return None


def _query_by_sw(conn: sqlite3.Connection, word: str) -> sqlite3.Row | None:
    sw = strip_word(word)
    if not sw:
        return None
    rows = conn.execute(
        "SELECT word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange"
        " FROM stardict WHERE sw = ? LIMIT 10",
        (sw,),
    ).fetchall()
    if not rows:
        return None
    low = word.lower()
    for r in rows:
        if r["word"].lower() == low:
            return r
    # 优先有中文释义且带词频/标签的条目
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            0 if (r["translation"] or "").strip() else 1,
            0 if (r["oxford"] or 0) else 1,
            -(r["collins"] or 0),
            r["frq"] if (r["frq"] or 0) > 0 else 999999,
        ),
    )
    return rows_sorted[0]


def _morph_candidates(word: str) -> list[str]:
    """生成规则屈折还原与英美拼写候选词（按可信度排序）。"""
    w = word.lower()
    cands: list[str] = []

    def add(v: str) -> None:
        v = v.strip("-'")
        if v and v != w and v not in cands:
            cands.append(v)

    if w.endswith("'s"):
        add(w[:-2])
    if w.endswith("s'"):
        add(w[:-1])
    if w.endswith("n't"):
        add(w[:-3])

    # 规则词形变化
    if w.endswith("ies") and len(w) > 4:
        add(w[:-3] + "y")
    if w.endswith("ied") and len(w) > 4:
        add(w[:-3] + "y")
    if w.endswith("ier") and len(w) > 4:
        add(w[:-3] + "y")
    if w.endswith("iest") and len(w) > 5:
        add(w[:-4] + "y")
    if w.endswith("ves") and len(w) > 4:
        add(w[:-3] + "f")
        add(w[:-3] + "fe")
    if w.endswith("es") and len(w) > 3:
        add(w[:-2])
    if w.endswith("s") and len(w) > 2 and not w.endswith("ss"):
        add(w[:-1])
    if w.endswith("ed") and len(w) > 3:
        add(w[:-2])
        add(w[:-1])
        m = re.search(r"([a-z])\1ed$", w)
        if m:
            add(w[:-3])
    if w.endswith("ing") and len(w) > 4:
        add(w[:-3])
        add(w[:-3] + "e")
        m = re.search(r"([a-z])\1ing$", w)
        if m:
            add(w[:-4])
    if w.endswith("er") and len(w) > 4:
        add(w[:-2])
        add(w[:-1])
    if w.endswith("est") and len(w) > 5:
        add(w[:-3])
        add(w[:-2])

    # 英式 -> 美式拼写变体（含其屈折词干）
    base_list = [w] + list(cands)
    for item in base_list:
        for uk, us in UK_TO_US_RULES:
            if item.endswith(uk) and len(item) > len(uk) + 2:
                add(item[: -len(uk)] + us)

    return cands


def _lookup_ecdict_row(conn: sqlite3.Connection, text: str) -> tuple[sqlite3.Row | None, sqlite3.Row | None, str]:
    """查询 ECDICT，返回 (命中行, 原型行, 形态说明)。"""
    row = _query_exact(conn, text) or _query_by_sw(conn, text)
    form_note = ""

    # 短语去掉开头冠词/介词重试（例如 "the deposit" / "a breakthrough"）
    if row is None and " " in text:
        stripped = LEADING_DET_RE.sub("", text).strip()
        if stripped and stripped != text:
            row = _query_exact(conn, stripped) or _query_by_sw(conn, stripped)

    # 单字屈折/英美拼写回退
    if row is None and " " not in text:
        for cand in _morph_candidates(text):
            row = _query_exact(conn, cand)
            if row:
                break

    if row is None:
        return None, None, ""

    # 利用 ECDICT exchange 字段追溯词根（0:<lemma>, 1:<形态代码>）
    ex = _parse_exchange(row["exchange"])
    base_row: sqlite3.Row | None = None
    lemma_name = ex.get("0", "")
    if lemma_name and lemma_name.lower() != row["word"].lower():
        base_row = _query_exact(conn, lemma_name)
        form_note = _describe_form(lemma_name, ex.get("1", ""))

    return row, base_row, form_note


def _lookup_pack_lexicon(text: str, pack_id: str) -> tuple[str, dict] | None:
    if not pack_id:
        return None
    pack = loader.get(pack_id)
    if not pack or not pack.doc.lexicon:
        return None
    lex = pack.doc.lexicon
    low = text.lower()
    candidates = [text, low]
    if " " not in low:
        candidates.extend(_morph_candidates(low))
    for cand in candidates:
        entry = lex.get(cand)
        if entry:
            return cand, entry.model_dump()
    return None


def _lookup_vocab_saved(lemma: str, word: str) -> int | None:
    keys = []
    for k in (lemma, word):
        cleaned = re.sub(r"\s+", " ", (k or "").strip().lower())
        if cleaned and cleaned not in keys:
            keys.append(cleaned)
    for k in keys:
        row = db.one("SELECT id FROM vocab WHERE lemma=? AND deleted_at=0", (k,))
        if row:
            return int(row["id"])
    return None


def _row_to_entry(row: sqlite3.Row, base_row: sqlite3.Row | None, form_note: str) -> dict:
    """将 ECDICT 命中行（与可选词根行）整理为统一返回结构。"""
    word = row["word"]
    lemma = (base_row["word"] if base_row else word).lower()

    trans = _normalize_multiline(row["translation"])
    base_trans = _normalize_multiline(base_row["translation"]) if base_row else ""
    # 如果变形词本身没有中文释义，或仅有简单形态标注，优先补上原型释义
    effective_trans = trans or base_trans
    if base_row and base_trans and trans and len(trans) < 20 and lemma in trans.lower():
        effective_trans = base_trans

    pos, gloss = _extract_pos_and_gloss(effective_trans)
    phonetic = (row["phonetic"] or (base_row["phonetic"] if base_row else "") or "").strip()
    definition = _normalize_multiline(row["definition"] or (base_row["definition"] if base_row else ""))

    tags = _parse_tags(row["tag"])
    if not tags and base_row:
        tags = _parse_tags(base_row["tag"])

    collins = int(row["collins"] or 0)
    if not collins and base_row:
        collins = int(base_row["collins"] or 0)

    oxford = bool(row["oxford"] or (base_row["oxford"] if base_row else 0))

    return {
        "word": word,
        "lemma": lemma,
        "phonetic": phonetic,
        "pos": pos,
        "gloss": gloss,
        "definition": definition,
        "tags": tags,
        "collins": collins,
        "oxford": oxford,
        "formNote": form_note,
    }


def _phrase_tokens(conn: sqlite3.Connection, text: str) -> list[dict]:
    """当多词短语整体未命中时，拆分实词逐个查 ECDICT 作为辅助理解。"""
    raw_words = WORD_TOKEN_RE.findall(text)
    if len(raw_words) < 2 or len(raw_words) > 8:
        return []
    seen: set[str] = set()
    items: list[dict] = []
    for raw in raw_words:
        low = raw.lower()
        if low in STOPWORDS or low in seen or len(low) < 2:
            continue
        seen.add(low)
        row, base_row, form_note = _lookup_ecdict_row(conn, raw)
        if not row:
            continue
        info = _row_to_entry(row, base_row, form_note)
        if not info["gloss"]:
            continue
        first_line = info["gloss"].split("\n")[0]
        items.append({
            "word": raw,
            "lemma": info["lemma"],
            "phonetic": info["phonetic"],
            "pos": info["pos"],
            "gloss": first_line,
            "formNote": info["formNote"],
        })
        if len(items) >= 6:
            break
    return items


def lookup(raw_query: str, pack_id: str = "") -> dict:
    """统一查词入口：合并文章语境词表 + 本地 ECDICT + 生词本收录状态。"""
    cleaned = clean_query(raw_query)
    dict_stat = status()
    if not cleaned:
        return {
            "query": "",
            "found": False,
            "source": "none",
            "word": "",
            "lemma": "",
            "phonetic": "",
            "pos": "",
            "gloss": "",
            "dictGloss": "",
            "definition": "",
            "tags": [],
            "collins": 0,
            "oxford": False,
            "formNote": "",
            "tokens": [],
            "saved": False,
            "vocabId": None,
            "dictReady": dict_stat["ready"],
        }

    pack_hit = _lookup_pack_lexicon(cleaned, pack_id)

    conn = _get_conn()
    ec_info: dict | None = None
    tokens: list[dict] = []

    if conn is not None:
        # 如果 pack 命中了更标准的词头，也用它查一次 ECDICT 以获取完整音标和标签
        row, base_row, form_note = _lookup_ecdict_row(conn, cleaned)
        if row is None and pack_hit:
            row, base_row, form_note = _lookup_ecdict_row(conn, pack_hit[0])
        if row is not None:
            ec_info = _row_to_entry(row, base_row, form_note)
        elif " " in cleaned:
            tokens = _phrase_tokens(conn, cleaned)

    if pack_hit:
        p_lemma, p_entry = pack_hit
        lemma = (ec_info["lemma"] if ec_info else p_lemma).lower()
        # 如果 pack 里明确以短语或原词为 key（如 streaming），且与当前查词一致，优先保留 pack key 作 lemma 兼容已有生词本
        if p_lemma.lower() == cleaned.lower():
            lemma = p_lemma.lower()
        gloss = (p_entry.get("gloss") or "").strip()
        pos = (p_entry.get("pos") or (ec_info["pos"] if ec_info else "")).strip()
        phonetic = (p_entry.get("phonetic") or (ec_info["phonetic"] if ec_info else "")).strip()
        dict_gloss = ec_info["gloss"] if ec_info and ec_info["gloss"] != gloss else ""
        vocab_id = _lookup_vocab_saved(lemma, cleaned)
        return {
            "query": cleaned,
            "found": True,
            "source": "pack",
            "word": cleaned,
            "lemma": lemma,
            "phonetic": phonetic,
            "pos": pos,
            "gloss": gloss or (ec_info["gloss"] if ec_info else ""),
            "dictGloss": dict_gloss,
            "definition": ec_info["definition"] if ec_info else "",
            "tags": ec_info["tags"] if ec_info else [],
            "collins": ec_info["collins"] if ec_info else 0,
            "oxford": ec_info["oxford"] if ec_info else False,
            "formNote": ec_info["formNote"] if ec_info else "",
            "tokens": [],
            "saved": vocab_id is not None,
            "vocabId": vocab_id,
            "dictReady": dict_stat["ready"],
        }

    if ec_info and (ec_info["gloss"] or ec_info["definition"]):
        lemma = ec_info["lemma"]
        vocab_id = _lookup_vocab_saved(lemma, cleaned)
        return {
            "query": cleaned,
            "found": True,
            "source": "ecdict",
            "word": cleaned,
            "lemma": lemma,
            "phonetic": ec_info["phonetic"],
            "pos": ec_info["pos"],
            "gloss": ec_info["gloss"],
            "dictGloss": "",
            "definition": ec_info["definition"],
            "tags": ec_info["tags"],
            "collins": ec_info["collins"],
            "oxford": ec_info["oxford"],
            "formNote": ec_info["formNote"],
            "tokens": [],
            "saved": vocab_id is not None,
            "vocabId": vocab_id,
            "dictReady": dict_stat["ready"],
        }

    # 短语拆分命中
    lemma = cleaned.lower()
    vocab_id = _lookup_vocab_saved(lemma, cleaned)
    return {
        "query": cleaned,
        "found": bool(tokens),
        "source": "tokens" if tokens else "none",
        "word": cleaned,
        "lemma": lemma,
        "phonetic": "",
        "pos": "",
        "gloss": "",
        "dictGloss": "",
        "definition": "",
        "tags": [],
        "collins": 0,
        "oxford": False,
        "formNote": "",
        "tokens": tokens,
        "saved": vocab_id is not None,
        "vocabId": vocab_id,
        "dictReady": dict_stat["ready"],
    }
