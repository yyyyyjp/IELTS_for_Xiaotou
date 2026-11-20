"""判分规则：听写填空与客观题共用。

雅思听写扣分主要在拼写，所以归一化只处理「大小写、标点、撇号写法、多余空格」，
不处理拼写近似——把 authorisation 判成 authorization 算错，这是有意的：
练习时放宽，考场上就还回来了。
"""
from __future__ import annotations

import re
import unicodedata

APOSTROPHES = "'’‘`´"
DASHES = "-–—−‐"
_WS_RE = re.compile(r"\s+")
_JUNK_RE = re.compile(r"[^\w\s']", re.UNICODE)


def normalize(value: str) -> str:
    s = unicodedata.normalize("NFKC", value or "")
    for ch in APOSTROPHES:
        s = s.replace(ch, "'")
    for ch in DASHES:
        s = s.replace(ch, " ")      # 连字符与空格等价：mixed-ability = mixed ability
    s = s.replace("\u00a0", " ")
    s = _JUNK_RE.sub(" ", s)        # 标点一律当分隔
    s = _WS_RE.sub(" ", s).strip().lower()
    return s.strip("'")


def as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def compare(expected: list[str], given) -> dict:
    """逐空比对，返回每空对错。空数不齐按缺答处理。"""
    got = as_list(given)
    if len(got) < len(expected):
        got = got + [""] * (len(expected) - len(got))
    parts = [normalize(a) == normalize(b) for a, b in zip(expected, got)]
    return {
        "ok": bool(parts) and all(parts),
        "parts": parts,
        "expected": expected,
        "given": got[: len(expected)],
    }


def same(expected: list[str], given) -> bool:
    return compare(expected, given)["ok"]
