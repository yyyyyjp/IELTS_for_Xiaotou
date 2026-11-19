"""把用户粘贴/上传的词书文本解析成题目。

兼容三种形态：
1) CSV / Excel 导出：单词,例句,例句翻译,释义（顺序不限，自动识别哪列是句子）
2) 带分隔符的 TXT：Tab / | / ; / ,
3) 内联标记的段落：The {{deposit}} is {{refundable}}. （一行可多空）
"""
from __future__ import annotations

import re

CN_RE = re.compile(r"[\u4e00-\u9fa5]")
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")
HEADER_RE = re.compile(
    r"^(单词|词汇|例句|句子|翻译|释义|词性|音标|编号|序号|word|sentence|example|translation|meaning|pos|phonetic|no)$",
    re.I,
)
MARK_RE = re.compile(r"\{\{([^}]+)\}\}|\[\[([^\]]+)\]\]")

STOP = set(
    """a an the of to in on at for and or but is are was were be been being it its this that these those
    with by as from i you he she we they my your his her our their me him them us do does did have has had
    will would can could should may might must not no so if than then there here what which who when where
    how very too also just about into over after before more most some any all one two three""".split()
)


def parse_csv(raw: str) -> list[list[str]]:
    """严格 CSV：支持引号包裹、引号内逗号与换行，同时把 Tab/|/; 当分隔符。"""
    rows: list[list[str]] = []
    row: list[str] = []
    cell: list[str] = []
    in_quote = False
    s = raw.replace("\r\n", "\n").replace("\r", "\n")
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_quote:
            if c == '"':
                if i + 1 < n and s[i + 1] == '"':
                    cell.append('"')
                    i += 2
                    continue
                in_quote = False
                i += 1
                continue
            cell.append(c)
            i += 1
            continue
        if c == '"':
            in_quote = True
            i += 1
            continue
        if c in ",\t|;":
            row.append("".join(cell))
            cell = []
            i += 1
            continue
        if c == "\n":
            row.append("".join(cell))
            rows.append(row)
            row, cell = [], []
            i += 1
            continue
        cell.append(c)
        i += 1
    if cell or row:
        row.append("".join(cell))
        rows.append(row)

    out = []
    for r in rows:
        cells = [x.strip() for x in r]
        if any(cells):
            out.append([c for c in cells if c])
    return out


def looks_sentence(s: str) -> bool:
    return len(WORD_RE.findall(s)) >= 4 or bool(re.search(r"[.?!]\s*$", s.strip()))


def pick_key_word(sentence: str) -> str:
    words = WORD_RE.findall(sentence or "")
    cand = [w for w in words if len(w) >= 4 and w.lower() not in STOP]
    if not cand:
        return words[0] if words else ""
    best = cand[0]
    for w in cand:          # 同长度取更靠后的，信息量通常更大
        if len(w) >= len(best):
            best = w
    return best


def _contains(text: str, word: str) -> bool:
    return re.search(r"(?<![A-Za-z])" + re.escape(word) + r"(?![A-Za-z])", text, re.I) is not None


def row_to_question(cells: list[str]) -> dict | None:
    fields = [c.strip() for c in cells if c and c.strip()]
    if not fields:
        return None

    text = ""
    answers: list[str] = []

    # ① 内联标记优先（可多空）
    marked = next((f for f in fields if MARK_RE.search(f)), None)
    if marked:
        for m in MARK_RE.finditer(marked):
            answers.append((m.group(1) or m.group(2)).strip())
        text = MARK_RE.sub(lambda m: (m.group(1) or m.group(2)).strip(), marked)

    # ② 最长的「像句子」的英文字段
    if not text:
        cands = [f for f in fields if not CN_RE.search(f) and looks_sentence(f)]
        text = max(cands, key=len) if cands else ""
    if not text:
        cands = [f for f in fields if not CN_RE.search(f)]
        text = max(cands, key=len) if cands else fields[0]

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None

    # ③ 中文：长的当翻译，次短的当释义
    cn_fields = sorted([f for f in fields if CN_RE.search(f) and f != text], key=len, reverse=True)
    translation = cn_fields[0] if cn_fields else ""
    meaning = min(cn_fields[1:], key=len) if len(cn_fields) > 1 else ""

    # ④ 挖空词
    if not answers:
        pool = [f for f in fields if f not in (text, translation, meaning) and not CN_RE.search(f)]
        hit = next((c for c in pool if _contains(text, c)), None)
        ans = hit or pick_key_word(text)
        answers = [ans] if ans else []
    if not answers:
        return None

    # ⑤ 校验：答案必须能在原文里定位，否则退化为自动挑词
    if not any(_contains(text, a) for a in answers):
        kw = pick_key_word(text)
        if not kw:
            return None
        answers = [kw]

    seen, uniq = set(), []
    for a in answers:
        k = a.lower()
        if k not in seen and _contains(text, a):
            seen.add(k)
            uniq.append(a)
    if not uniq:
        return None

    return {
        "text": text,
        "answers": uniq,
        "translation": translation,
        "meaning": meaning,
        "title": "段落填空" if len(uniq) > 2 else "句子听写",
    }


def parse_text(raw: str) -> list[dict]:
    rows = parse_csv(raw)
    out: list[dict] = []
    header_skipped = False
    for r in rows:
        if not header_skipped and len(r) >= 2 and all(HEADER_RE.match(c) for c in r):
            header_skipped = True
            continue
        q = row_to_question(r)
        if q:
            out.append(q)
    return out
