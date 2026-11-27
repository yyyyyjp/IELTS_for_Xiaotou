"""将 6.6 万核心离线词典（core_dict.json.gz）分批导入 Cloudflare D1 dict 表。

用途：在浏览器尚未缓存完 2MB 离线词库前，通过 /api/dict/lookup 仅传输 ~250B 实现 <0.3s 极速查词。
用法（仓库根目录）：
  app\\server\\.venv\\Scripts\\python.exe tools\\seed_d1_dict.py
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / "app" / "cloud"
DEFAULT_CORE = ROOT / "app" / "server" / "data" / "core_dict.json.gz"


def sql_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def find_wrangler() -> list[str]:
    local = CLOUD / "node_modules" / ".bin" / ("wrangler.cmd" if sys.platform == "win32" else "wrangler")
    if local.exists():
        return [str(local)]
    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    return [npx, "wrangler"]


def run_sql_file(wrangler: list[str], db_name: str, sql_path: Path, timeout_sec: int = 120) -> None:
    cmd = wrangler + ["d1", "execute", db_name, "--remote", "--yes", "--file", str(sql_path)]
    res = subprocess.run(
        cmd,
        cwd=str(CLOUD),
        stdin=subprocess.DEVNULL,
        timeout=timeout_sec,
        encoding="utf-8",
        errors="replace",
    )
    if res.returncode != 0:
        raise RuntimeError(f"执行 {sql_path.name} 失败（exit={res.returncode}）")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="将核心词典导入 Cloudflare D1 dict 表")
    ap.add_argument("--db", default="xiaotou-ielts-db")
    ap.add_argument("--core", default=str(DEFAULT_CORE))
    ap.add_argument("--rows-per-stmt", type=int, default=80)
    ap.add_argument("--rows-per-file", type=int, default=16000)
    ap.add_argument("--start-batch", type=int, default=1)
    ap.add_argument("--limit", type=int, default=0, help="仅导入前 N 条（调试用，0 表示全部）")
    args = ap.parse_args(argv)

    core_path = Path(args.core)
    if not core_path.exists():
        print(f"找不到核心词典文件：{core_path}", file=sys.stderr)
        return 1

    with gzip.open(core_path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries") or []

    # 按 word_lower 去重（保留第一条，通常为词频更高的主词条）
    dedup: dict[str, tuple[str, str, str, str, int, str]] = {}
    for tup in entries:
        w = str(tup[0]).strip()
        if not w:
            continue
        low = w.lower()
        if low in dedup:
            continue
        dedup[low] = (
            w,
            str(tup[1] or ""),
            str(tup[2] or ""),
            str(tup[3] or ""),
            int(tup[4] or 0),
            str(tup[5] or ""),
        )

    rows = list(dedup.items())
    if args.limit > 0:
        rows = rows[: args.limit]
    wrangler = find_wrangler()
    t0 = time.time()
    print(f"[seed_d1_dict] 准备导入 {len(rows)} 条词典记录到 D1 {args.db} ...", flush=True)

    with tempfile.TemporaryDirectory(prefix="xt_d1_dict_") as tmp:
        tmp_dir = Path(tmp)
        if args.start_batch <= 1:
            ddl = tmp_dir / "00_ddl.sql"
            ddl.write_text(
                "CREATE TABLE IF NOT EXISTS dict (\n"
                "  word_lower TEXT PRIMARY KEY,\n"
                "  word TEXT NOT NULL,\n"
                "  phonetic TEXT NOT NULL DEFAULT '',\n"
                "  trans TEXT NOT NULL DEFAULT '',\n"
                "  tag TEXT NOT NULL DEFAULT '',\n"
                "  flags INTEGER NOT NULL DEFAULT 0,\n"
                "  exchange TEXT NOT NULL DEFAULT ''\n"
                ");\n",
                encoding="utf-8",
            )
            run_sql_file(wrangler, args.db, ddl)

        total_files = (len(rows) + args.rows_per_file - 1) // args.rows_per_file
        for f_idx in range(total_files):
            if f_idx + 1 < args.start_batch:
                continue
            chunk = rows[f_idx * args.rows_per_file : (f_idx + 1) * args.rows_per_file]
            stmts: list[str] = []
            for s_idx in range(0, len(chunk), args.rows_per_stmt):
                part = chunk[s_idx : s_idx + args.rows_per_stmt]
                vals = ",".join(
                    f"({sql_quote(low)},{sql_quote(w)},{sql_quote(ph)},{sql_quote(tr)},{sql_quote(tag)},{fl},{sql_quote(ex)})"
                    for low, (w, ph, tr, tag, fl, ex) in part
                )
                stmts.append(
                    f"INSERT OR REPLACE INTO dict(word_lower,word,phonetic,trans,tag,flags,exchange) VALUES {vals};"
                )
            sql_file = tmp_dir / f"batch_{f_idx + 1:02d}.sql"
            sql_file.write_text("\n".join(stmts) + "\n", encoding="utf-8")
            size_kb = sql_file.stat().st_size / 1024
            print(f"[seed_d1_dict] 上传批次 {f_idx + 1}/{total_files} ({len(chunk)} 词, {size_kb:.0f} KB) ...", flush=True)
            bt = time.time()
            run_sql_file(wrangler, args.db, sql_file, timeout_sec=180)
            print(
                f"[seed_d1_dict] 批次 {f_idx + 1}/{total_files} 完成，耗时 {time.time() - bt:.1f}s",
                flush=True,
            )

    print(f"[seed_d1_dict] 全部完成，共 {len(rows)} 词，总耗时 {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
