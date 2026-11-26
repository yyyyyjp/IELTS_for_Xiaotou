"""将完整 ecdict.db 按首字母切分为 27 个 Gzip JSON 分片（供 Cloudflare R2 静态托管）。

输出目录：app/server/data/dict_shards/
  - a.json.gz ~ z.json.gz（按 word 小写首字母分组）
  - other.json.gz（数字/符号开头的词条）

每个分片采用与 core_dict 兼容的紧凑结构：
{
  "version": 1,
  "shard": "a",
  "count": N,
  "entries": [[word, phonetic, translation, tag, flags, exchange], ...]
}
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
DEFAULT_OUT_DIR = ROOT / "app" / "server" / "data" / "dict_shards"

BASE_EX_RE = re.compile(r"(?:^|/)0:([^/]+)")


def clean_trans(raw: str | None) -> str:
    if not raw:
        return ""
    s = raw.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in s.split("\n") if ln.strip()]
    return "\n".join(lines)


def shard_key(word: str) -> str:
    if not word:
        return "other"
    ch = word[0].lower()
    if "a" <= ch <= "z":
        return ch
    return "other"


def build_shards(src_db: Path, out_dir: Path) -> dict[str, int]:
    if not src_db.exists():
        raise SystemExit(f"未找到源词典：{src_db}（请先运行 tools/setup_ecdict.py）")

    t0 = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.json.gz"):
        old.unlink()

    conn = sqlite3.connect(str(src_db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT word, phonetic, translation, tag, collins, oxford, exchange
        FROM stardict
        WHERE length(word) <= 64
          AND ((translation IS NOT NULL AND translation <> '') OR exchange LIKE '%0:%')
        """
    ).fetchall()
    conn.close()

    buckets: dict[str, list[tuple]] = {}
    for r in rows:
        w = r["word"]
        trans = clean_trans(r["translation"])
        ex = (r["exchange"] or "").strip()
        keep_ex = "/".join(p for p in ex.split("/") if p.startswith(("0:", "1:")))
        if not trans and not keep_ex:
            continue
        flags = (int(r["collins"] or 0) & 7) | (8 if r["oxford"] else 0)
        sk = shard_key(w)
        buckets.setdefault(sk, []).append((
            w,
            (r["phonetic"] or "").strip(),
            trans,
            (r["tag"] or "").strip(),
            flags,
            keep_ex,
        ))

    stats: dict[str, int] = {}
    total_bytes = 0
    total_entries = 0
    for sk in sorted(buckets):
        entries = sorted(buckets[sk], key=lambda x: x[0].lower())
        payload = {
            "version": 1,
            "shard": sk,
            "count": len(entries),
            "entries": entries,
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        gz = gzip.compress(raw, compresslevel=9)
        (out_dir / f"{sk}.json.gz").write_bytes(gz)
        stats[sk] = len(entries)
        total_bytes += len(gz)
        total_entries += len(entries)

    elapsed = time.time() - t0
    print(
        f"[build_dict_shards] 共 {len(stats)} 个分片，{total_entries:,} 条词目，"
        f"Gzip 总体积 {total_bytes / 1024 / 1024:.2f} MB ({elapsed:.1f}s) -> {out_dir}"
    )
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="构建按首字母切分的 ECDICT R2 分片")
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    args = ap.parse_args(argv)
    build_shards(args.src, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
