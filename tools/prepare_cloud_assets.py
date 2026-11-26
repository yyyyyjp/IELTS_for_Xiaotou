"""准备 Cloudflare 上线素材：
1. 生成 core_dict.json.gz（6.6 万核心离线词库）与 dict_shards/*.json.gz（77 万按首字母分片）；
2. 将 app/server/content/packs/*.json 导出为 D1 初始化 SQL：app/cloud/seed_packs.sql；
3. 传入 --upload 时，自动通过 wrangler r2 object put --remote 批量上传词典与音频到 R2 xiaotou-ielts。

用法（仓库根目录）：
  app\\server\\.venv\\Scripts\\python.exe tools\\prepare_cloud_assets.py
  app\\server\\.venv\\Scripts\\python.exe tools\\prepare_cloud_assets.py --upload
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "app" / "server"
CLOUD = ROOT / "app" / "cloud"
TOOLS = Path(__file__).resolve().parent

sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(TOOLS))

import build_core_dict  # noqa: E402
import build_dict_shards  # noqa: E402
import content.loader as loader  # noqa: E402


def sql_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def generate_seed_sql(out_sql: Path) -> int:
    packs = loader.load_all(force=True)
    lines = ["-- 自动生成：将本地精读内容包同步到 Cloudflare D1 packs 表", ""]
    for pid in sorted(packs):
        lp = packs[pid]
        summary = json.dumps(lp.summary(), ensure_ascii=False, separators=(",", ":"))
        detail = json.dumps(lp.public(with_answers=True), ensure_ascii=False, separators=(",", ":"))
        mt = int(lp.mtime)
        lines.append(
            "INSERT INTO packs(id, kind, origin, title, mtime, summary_json, detail_json) VALUES("
            f"{sql_quote(lp.id)}, {sql_quote(lp.doc.kind)}, {sql_quote(lp.doc.origin)}, "
            f"{sql_quote(lp.doc.meta.title)}, {mt}, {sql_quote(summary)}, {sql_quote(detail)}"
            ") ON CONFLICT(id) DO UPDATE SET "
            "kind=excluded.kind, origin=excluded.origin, title=excluded.title, "
            "mtime=excluded.mtime, summary_json=excluded.summary_json, detail_json=excluded.detail_json;"
        )
    out_sql.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[prepare_cloud] 生成 D1 内容包 SQL：{len(packs)} 篇 -> {out_sql.relative_to(ROOT)}")
    return len(packs)


def upload_r2_object(wrangler_cmd: list[str], bucket: str, key: str, file_path: Path, content_type: str, content_encoding: str = "") -> None:
    cmd = wrangler_cmd + [
        "r2", "object", "put", f"{bucket}/{key}",
        "--file", str(file_path),
        "--content-type", content_type,
        "--remote",
    ]
    if content_encoding:
        cmd += ["--content-encoding", content_encoding]
    res = subprocess.run(cmd, cwd=str(CLOUD), capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"上传 {key} 失败：{res.stderr or res.stdout}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="准备并可选上传 Cloudflare D1/R2 静态资源")
    ap.add_argument("--bucket", default="xiaotou-ielts")
    ap.add_argument("--upload", action="store_true", help="调用 wrangler r2 object put 上传词库与缓存音频")
    ap.add_argument("--skip-audio", action="store_true", help="上传时跳过音频目录")
    args = ap.parse_args(argv)

    core_path = SERVER / "data" / "core_dict.json.gz"
    shards_dir = SERVER / "data" / "dict_shards"

    if not core_path.exists():
        build_core_dict.build_core(SERVER / "data" / "ecdict.db", core_path)
    if not shards_dir.exists() or len(list(shards_dir.glob("*.json.gz"))) < 26:
        build_dict_shards.build_shards(SERVER / "data" / "ecdict.db", shards_dir)

    generate_seed_sql(CLOUD / "seed_packs.sql")

    if not args.upload:
        print("[prepare_cloud] 离线准备完成。加 --upload 可直接上传词典分片和音频到 R2。")
        return 0

    npx = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    wrangler_cmd = [npx, "wrangler"]

    t0 = time.time()
    print(f"[prepare_cloud] 上传核心词库 -> R2 {args.bucket}/dict/core_dict.json.gz ...")
    upload_r2_object(wrangler_cmd, args.bucket, "dict/core_dict.json.gz", core_path, "application/json", "gzip")

    shard_files = sorted(shards_dir.glob("*.json.gz"))
    for i, sf in enumerate(shard_files, start=1):
        print(f"[prepare_cloud] 上传词典分片 ({i}/{len(shard_files)}) -> dict/shards/{sf.name}", flush=True)
        upload_r2_object(wrangler_cmd, args.bucket, f"dict/shards/{sf.name}", sf, "application/json", "gzip")

    if not args.skip_audio:
        audio_dir = SERVER / "data" / "audio"
        mp3s = sorted(audio_dir.glob("*.mp3")) if audio_dir.exists() else []
        for i, mp3 in enumerate(mp3s, start=1):
            print(f"[prepare_cloud] 上传音频 ({i}/{len(mp3s)}) -> audio/{mp3.name}", flush=True)
            upload_r2_object(wrangler_cmd, args.bucket, f"audio/{mp3.name}", mp3, "audio/mpeg")

    print(f"[prepare_cloud] R2 上传全部完成（耗时 {time.time() - t0:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
