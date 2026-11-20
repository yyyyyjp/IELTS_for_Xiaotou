#!/usr/bin/env python
"""把单文件精读页（内嵌 const DATA / const DICT）转成后端内容包。

用法：
    python tools/pack_from_html.py "剑雅18-Test3-Passage3-精读与生词本.html" --id cam18-t3-p3

产出：
    app/server/content/packs/<id>.json          内容包（原文、译文、题目、词表）
    app/server/content/imports/<id>-history.json 可选，旧页面上已作答的记录

只依赖标准库 + 后端已装的 pydantic。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "app" / "server"
sys.path.insert(0, str(SERVER))

from content.loader import Pack, PackMeta, Paragraph, Sentence  # noqa: E402


def grab_js_object(src: str, name: str) -> dict:
    """从 `const NAME = {...};` 里按括号配平截出对象字面量。"""
    marker = f"const {name} = "
    start = src.find(marker)
    if start < 0:
        raise SystemExit(f"没找到 {marker.strip()}，确认是精读页原文件")
    i = start + len(marker)
    depth, in_str, esc = 0, False, False
    for j in range(i, len(src)):
        c = src[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(src[i:j + 1])
    raise SystemExit(f"{name} 没有闭合，文件可能被截断")


def parse_duration(text: str) -> int:
    m = re.search(r"(?:(\d+)\s*分)?\s*(\d+)\s*秒", text or "")
    if m:
        return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    m = re.search(r"(\d+):(\d+)", text or "")
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return 0


def derive_id(meta: dict) -> str:
    nums = re.findall(r"\d+", meta.get("book", ""))
    book = f"cam{nums[0]}" if nums else "pack"
    t = re.search(r"\d+", meta.get("test", ""))
    p = re.search(r"\d+", meta.get("passage", ""))
    parts = [book]
    if t:
        parts.append(f"t{t.group()}")
    if p:
        parts.append(f"p{p.group()}")
    return "-".join(parts)


def build_pack(data: dict, dict_words: dict, pack_id: str, origin: str) -> Pack:
    meta = data.get("meta", {})
    paragraphs = []
    for p in data.get("paragraphs", []):
        no = int(p.get("idx") or len(paragraphs) + 1)
        sentences = [
            Sentence(id=f"p{no}s{i}", en=s["en"].strip(), zh=(s.get("zh") or "").strip())
            for i, s in enumerate(p.get("sentences", []), start=1)
        ]
        paragraphs.append(Paragraph(no=no, sentences=sentences))

    desc = data.get("desc", [])
    groups = []

    mcq = data.get("mcq", [])
    if mcq:
        groups.append({
            "id": "mcq",
            "type": "mcq",
            "from": mcq[0]["no"],
            "to": mcq[-1]["no"],
            "instruction": desc[0] if len(desc) > 0 else "",
            "items": [
                {
                    "no": q["no"],
                    "stem": q.get("stem", ""),
                    "options": [{"key": o["k"], "text": o["t"]} for o in q.get("options", [])],
                    "answer": q.get("correct", ""),
                }
                for q in mcq
            ],
        })

    summary = data.get("summary")
    if summary:
        groups.append({
            "id": "summary",
            "type": "summary",
            "from": summary["items"][0]["no"],
            "to": summary["items"][-1]["no"],
            "instruction": desc[1] if len(desc) > 1 else "",
            "title": summary.get("title", ""),
            "text": summary.get("text", ""),
            "options": [{"key": o["k"], "text": o["t"]} for o in summary.get("options", [])],
            "items": [{"no": it["no"], "answer": it.get("correct", "")}
                      for it in summary.get("items", [])],
        })

    yn = data.get("yn", [])
    if yn:
        groups.append({
            "id": "ynng",
            "type": "ynng",
            "from": yn[0]["no"],
            "to": yn[-1]["no"],
            "instruction": desc[2] if len(desc) > 2 else "",
            "items": [{"no": q["no"], "stem": q.get("stem", ""),
                       "answer": q.get("correct", "")} for q in yn],
        })

    return Pack(
        id=pack_id,
        kind="reading",
        origin=origin,
        meta=PackMeta(
            book=meta.get("book", ""),
            test=meta.get("test", ""),
            passage=meta.get("passage", ""),
            title=meta.get("title", ""),
            durationSec=parse_duration(meta.get("duration", "")),
            source=meta.get("source", ""),
        ),
        paragraphs=paragraphs,
        questionGroups=groups,
        lexicon=dict_words,
    )


def collect_answers(data: dict) -> dict:
    answers = {}
    for q in data.get("mcq", []):
        answers[str(q["no"])] = q.get("mine", "")
    for it in (data.get("summary") or {}).get("items", []):
        answers[str(it["no"])] = it.get("mine", "")
    for q in data.get("yn", []):
        answers[str(q["no"])] = q.get("mine", "")
    return answers


def tidy(doc: dict, pack: Pack) -> dict:
    """去掉空字段，词表还原成「v. 想象」这样的单行字符串，便于人读和 diff。"""
    doc["meta"] = {k: v for k, v in doc.get("meta", {}).items() if v not in ("", 0, None)}
    doc["lexicon"] = {k: (v.raw or v.gloss) for k, v in pack.lexicon.items()}
    for key in ("items",):
        if not doc.get(key):
            doc.pop(key, None)
    for g in doc.get("questionGroups", []):
        for key in ("title", "text", "options", "instruction"):
            if not g.get(key):
                g.pop(key, None)
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--id", default="", help="内容包 id，缺省按书名自动生成")
    ap.add_argument("--origin", default="builtin", choices=["builtin", "custom"])
    ap.add_argument("--history", action="store_true", help="同时导出旧作答记录")
    ap.add_argument("--post", default="", metavar="http://127.0.0.1:8000",
                    help="导入后把历史记录 POST 到运行中的服务")
    args = ap.parse_args()

    html = Path(args.html)
    src = html.read_text(encoding="utf-8")
    data = grab_js_object(src, "DATA")
    try:
        dict_words = grab_js_object(src, "DICT")
    except SystemExit:
        dict_words = {}

    meta = data.get("meta", {})
    pack_id = args.id or derive_id(meta)
    pack = build_pack(data, dict_words, pack_id, args.origin)

    out_dir = SERVER / "content" / "packs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pack_id}.json"
    out_path.write_text(
        json.dumps(tidy(pack.model_dump(by_alias=True, exclude_none=True), pack),
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"内容包：{out_path.relative_to(ROOT)}")
    print(f"  {pack.meta.label} · {pack.meta.title}")
    print(f"  段落 {len(pack.paragraphs)} / 句子 {pack.sentence_count} / "
          f"题 {pack.question_count} / 词表 {len(pack.lexicon)}")

    if not (args.history or args.post):
        return

    history = {
        "packId": pack_id,
        "answers": collect_answers(data),
        "durationMs": pack.meta.durationSec * 1000,
    }
    if not any(history["answers"].values()):
        print("旧页面没有作答记录，跳过 history")
        return

    hist_dir = SERVER / "content" / "imports"
    hist_dir.mkdir(parents=True, exist_ok=True)
    hist_path = hist_dir / f"{pack_id}-history.json"
    hist_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"历史作答：{hist_path.relative_to(ROOT)}")

    if args.post:
        import urllib.error
        import urllib.request
        req = urllib.request.Request(
            args.post.rstrip("/") + "/api/reading/history",
            data=json.dumps(history, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                print("已导入历史成绩：", resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            print("导入失败：", exc.code, exc.read().decode("utf-8", "replace"))
            print("确认服务已启动，且该内容包已加载（POST /api/packs/reload）")
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
