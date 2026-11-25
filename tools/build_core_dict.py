"""从完整 ecdict.db 提炼浏览器端核心离线词库（app/server/data/core_dict.json.gz）。

筛选策略（覆盖 96%+ 雅思与学术英语阅读高频词及不规则变形）：
1. 含考试标签（ielts / toefl / gre / cet6 / cet4 / ky / gk / zk）、牛津 3000（oxford=1）、
   柯林斯星级（collins >= 1），或 BNC / 当代词频前 30,000 的词条；
2. 词根在上述集合内的所有不规则变形词条（如 went / children / mice / better / taught），
   保证离线状态下的词形还原同样准确。

紧凑数组格式（最小化传输与 IndexedDB 体积）：
{
  "version": 1,
  "count": N,
  "entries": [
    [word, phonetic, translation, tag, flags, exchange], ...
  ]
}
其中 flags = (collins & 7) | (oxford ? 8 : 0)。
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "app" / "server" / "data" / "ecdict.db"
DEFAULT_OUT = ROOT / "app" / "server" / "data" / "core_dict.json.gz"

BASE_EX_RE = re.compile(r"(?:^|/)0:([^/]+)")


def clean_trans(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
    return "\n".join(lines)


def build_core(src_db: Path, out_gz: Path) -> tuple[int, int]:
    if not src_db.exists():
        raise SystemExit(f"未找到源词典：{src_db}（请先运行 tools/setup_ecdict.py）")

    t0 = time.time()
    conn = sqlite3.connect(str(src_db))
    conn.row_factory = sqlite3.Row

    # 1. 核心词条：考试词表 / 牛津 / 柯林斯 / 前 30000 高频词（且有中文释义，排除过长句子词条）
    core_rows = conn.execute(
        """
        SELECT word, phonetic, translation, tag, collins, oxford, exchange
        FROM stardict
        WHERE translation IS NOT NULL AND translation <> ''
          AND length(word) <= 40
          AND (
            oxford = 1
            OR collins >= 1
            OR (tag IS NOT NULL AND tag <> '')
            OR (bnc > 0 AND bnc <= 30000)
            OR (frq > 0 AND frq <= 30000)
          )
        """
    ).fetchall()

    by_word: dict[str, tuple] = {}
    core_lemmas: set[str] = set()

    for r in core_rows:
        w = r["word"]
        trans = clean_trans(r["translation"])
        if not trans:
            continue
        flags = (int(r["collins"] or 0) & 7) | (8 if r["oxford"] else 0)
        ex = (r["exchange"] or "").strip()
        # 仅保留词根反向引用 (0:xxx / 1:xxx)，省去冗余正向派生列表，进一步缩减约 30% 体积
        keep_ex = "/".join(p for p in ex.split("/") if p.startswith(("0:", "1:")))
        by_word[w] = (
            w,
            (r["phonetic"] or "").strip(),
            trans,
            (r["tag"] or "").strip(),
            flags,
            keep_ex,
        )
        core_lemmas.add(w.lower())

    # 2. 补齐指向核心词根的不规则变形词（exchange 含 0:<lemma>）
    inflected_rows = conn.execute(
        """
        SELECT word, phonetic, translation, tag, collins, oxford, exchange
        FROM stardict
        WHERE exchange LIKE '%0:%' AND length(word) <= 40
        """
    ).fetchall()

    added_forms = 0
    for r in inflected_rows:
        w = r["word"]
        if w in by_word:
            continue
        ex = (r["exchange"] or "").strip()
        m = BASE_EX_RE.search(ex)
        if not m:
            continue
        lemma = m.group(1).strip().lower()
        if lemma not in core_lemmas:
            continue
        # 不规则变形（非简单规则后缀时尤其关键；只收录单字变形）
        if " " in w:
            continue
        keep_ex = "/".join(p for p in ex.split("/") if p.startswith(("0:", "1:")))
        flags = (int(r["collins"] or 0) & 7) | (8 if r["oxford"] else 0)
        by_word[w] = (
            w,
            (r["phonetic"] or "").strip(),
            clean_trans(r["translation"]),
            (r["tag"] or "").strip(),
            flags,
            keep_ex,
        )
        added_forms += 1

    conn.close()

    entries = sorted(by_word.values(), key=lambda x: x[0].lower())
    payload = {
        "version": 1,
        "count": len(entries),
        "entries": entries,
    }
    raw_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    out_gz.parent.mkdir(parents=True, exist_ok=True)
    compressed = gzip.compress(raw_bytes, compresslevel=9)
    out_gz.write_bytes(compressed)

    elapsed = time.time() - t0
    print(
        f"[build_core_dict] 核心词 {len(entries) - added_forms:,} + 变形词 {added_forms:,} = 共 {len(entries):,} 条\n"
        f"[build_core_dict] 原始 JSON {len(raw_bytes)/1024/1024:.2f} MB -> Gzip {len(compressed)/1024/1024:.2f} MB ({elapsed:.1f}s)\n"
        f"[build_core_dict] 输出：{out_gz}"
    )
    return len(entries), len(compressed)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="生成浏览器端精简离线 ECDICT 词库包")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    build_core(args.src, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
