#!/usr/bin/env python
"""把旧精读页「复制 JSON」得到的生词数组导入后端。

用法：
    python tools/import_vocab.py vocab.json --pack cam18-t3-p3
    python tools/import_vocab.py vocab.json --pack cam18-t3-p3 --post http://127.0.0.1:8000

dry-run 只打印将要导入的条目数；带 --post 才真正写入。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_items(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(raw, dict):
        raw = raw.get("items") or []
    if not isinstance(raw, list):
        raise SystemExit("JSON 顶层应该是数组，或带 items 数组的对象")
    items = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        if not (it.get("lemma") or it.get("word")):
            continue
        items.append(it)
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("json", help="旧页面导出的 JSON 文件")
    ap.add_argument("--pack", default="", help="这些词属于哪个内容包 id")
    ap.add_argument("--post", default="", metavar="http://127.0.0.1:8000",
                    help="POST 到运行中的服务；不给则只预览")
    args = ap.parse_args()

    items = load_items(Path(args.json))
    print(f"待导入生词：{len(items)} 条")
    for it in items[:8]:
        print(f"  {it.get('word', ''):<20} {it.get('gloss', '')[:40]}")
    if len(items) > 8:
        print(f"  …… 其余 {len(items) - 8} 条")
    if not args.post:
        print("\n加 --post http://127.0.0.1:8000 才会真正写入")
        return

    payload = {"items": items, "packId": args.pack}
    req = urllib.request.Request(
        args.post.rstrip("/") + "/api/vocab/import",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print("\n导入结果：", resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print("\n导入失败：", exc.code, exc.read().decode("utf-8", "replace"))
        sys.exit(1)


if __name__ == "__main__":
    main()
