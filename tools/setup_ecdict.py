"""构建本地离线 ECDICT SQLite 数据库（app/server/data/ecdict.db）。

用法（仓库根目录执行）：
    app\\server\\.venv\\Scripts\\python.exe tools\\setup_ecdict.py
    app\\server\\.venv\\Scripts\\python.exe tools\\setup_ecdict.py --tgz app\\server\\data\\ecdict-0.0.4.tgz
    app\\server\\.venv\\Scripts\\python.exe tools\\setup_ecdict.py --csv path\\to\\ecdict.csv

默认会从阿里云 npmmirror 拉取开源 MIT 协议的 ecdict@0.0.4 包内的 ecdict.csv，
并流式导入到 app/server/data/ecdict.db（含 word / sw 索引，查询延迟 < 2ms）。
"""
from __future__ import annotations

import argparse
import csv
import io
import sqlite3
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "app" / "server" / "data" / "ecdict.db"
DEFAULT_TGZ_URL = "https://registry.npmmirror.com/ecdict/-/ecdict-0.0.4.tgz"

SCHEMA_SQL = """
CREATE TABLE stardict (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word VARCHAR(64) NOT NULL UNIQUE,
    sw VARCHAR(64) NOT NULL,
    phonetic VARCHAR(64),
    definition TEXT,
    translation TEXT,
    pos VARCHAR(16),
    collins INTEGER DEFAULT 0,
    oxford INTEGER DEFAULT 0,
    tag VARCHAR(64),
    bnc INTEGER DEFAULT 0,
    frq INTEGER DEFAULT 0,
    exchange TEXT,
    detail TEXT,
    audio TEXT
);
"""

INDEX_SQL = """
CREATE INDEX idx_stardict_sw ON stardict (sw);
"""


def strip_word(word: str) -> str:
    return "".join(ch for ch in word if ch.isalnum()).lower()


def to_int(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def build_from_stream(stream: io.TextIOBase, out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = out_path.with_suffix(".db.building")
    if tmp_db.exists():
        tmp_db.unlink()

    conn = sqlite3.connect(str(tmp_db))
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA cache_size = -64000")
    conn.executescript(SCHEMA_SQL)

    reader = csv.DictReader(stream)
    insert_sql = (
        "INSERT OR IGNORE INTO stardict"
        " (word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange, detail, audio)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )

    batch: list[tuple] = []
    total = 0
    t0 = time.time()
    for row in reader:
        word = (row.get("word") or "").strip()
        if not word:
            continue
        batch.append((
            word,
            strip_word(word),
            (row.get("phonetic") or "").strip(),
            row.get("definition") or "",
            row.get("translation") or "",
            (row.get("pos") or "").strip(),
            to_int(row.get("collins")),
            to_int(row.get("oxford")),
            (row.get("tag") or "").strip(),
            to_int(row.get("bnc")),
            to_int(row.get("frq")),
            (row.get("exchange") or "").strip(),
            row.get("detail") or "",
            row.get("audio") or "",
        ))
        if len(batch) >= 20000:
            conn.executemany(insert_sql, batch)
            total += len(batch)
            batch.clear()
            print(f"[setup_ecdict] 已导入 {total:,} 条 ({time.time() - t0:.1f}s)...", flush=True)

    if batch:
        conn.executemany(insert_sql, batch)
        total += len(batch)

    conn.commit()
    print(f"[setup_ecdict] 正在建立索引...", flush=True)
    conn.executescript(INDEX_SQL)
    conn.execute("ANALYZE")
    conn.commit()
    final_count = conn.execute("SELECT COUNT(*) FROM stardict").fetchone()[0]
    conn.close()

    if out_path.exists():
        out_path.unlink()
    tmp_db.replace(out_path)
    print(f"[setup_ecdict] 完成：{final_count:,} 条 -> {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB, {time.time() - t0:.1f}s)")
    return int(final_count)


def build_from_tgz(tgz_path: Path, out_path: Path) -> int:
    with tarfile.open(tgz_path, "r:gz") as tf:
        csv_member = next((m for m in tf.getmembers() if m.name.endswith("ecdict.csv")), None)
        if not csv_member:
            raise RuntimeError(f"{tgz_path} 中未找到 ecdict.csv")
        raw = tf.extractfile(csv_member)
        if raw is None:
            raise RuntimeError("无法读取 ecdict.csv")
        text_stream = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
        return build_from_stream(text_stream, out_path)


def download(url: str, dest: Path) -> None:
    print(f"[setup_ecdict] 下载 {url} ...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "xiaotou-ielts/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as fp:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            fp.write(chunk)
            done += len(chunk)
            if total:
                pct = done * 100 / total
                print(f"\r[setup_ecdict] {done / 1024 / 1024:.1f}/{total / 1024 / 1024:.1f} MB ({pct:.0f}%)", end="", flush=True)
    print("")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="构建本地 ECDICT SQLite 离线词典")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出 SQLite 路径")
    ap.add_argument("--csv", type=Path, default=None, help="本地 ecdict.csv 路径")
    ap.add_argument("--tgz", type=Path, default=None, help="本地 ecdict .tgz 包路径")
    ap.add_argument("--url", default=DEFAULT_TGZ_URL, help="在线下载 tgz 的 URL")
    args = ap.parse_args(argv)

    if args.csv:
        with args.csv.open("r", encoding="utf-8-sig", errors="replace", newline="") as fp:
            build_from_stream(fp, args.out)
        return 0

    if args.tgz:
        build_from_tgz(args.tgz, args.out)
        return 0

    with tempfile.TemporaryDirectory(prefix="ecdict-dl-") as tmp:
        tgz_path = Path(tmp) / "ecdict.tgz"
        download(args.url, tgz_path)
        build_from_tgz(tgz_path, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
