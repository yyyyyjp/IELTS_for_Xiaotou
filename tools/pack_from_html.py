#!/usr/bin/env python
"""把单文件精读页转成内容包 v2（原文 + 题目 + 我的作答 + 复盘 + 读懂）。

用法：
    python tools/pack_from_html.py "剑雅18-Test3-Passage3-精读与生词本.html" --id cam18-t3-p3

产出：
    app/server/content/packs/<id>.json          内容包（含 attempt / review / guide）
    app/server/content/imports/<id>-history.json 可选，旧页面上已作答的记录

页面上如果带 `const REV` / `const MEANS`，会自动归一成内容包的 review / guide；
也可以 `--analysis analysis.json` 用外部文件覆盖（AI 复盘产出的格式）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "app" / "server"
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(TOOLS))

import js_literal  # noqa: E402
import review_pack  # noqa: E402
from content.loader import Pack, PackMeta, Paragraph, Sentence  # noqa: E402


def grab_js_object(src: str, name: str) -> dict:
    """兼容旧调用：从 `const NAME = {...}` 里取对象。"""
    return js_literal.grab(src, name)


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


def clean_instruction(text: str) -> str:
    """组指令里常带一行 "Questions 27–30"，标题已经写了题号，去掉这段。"""
    text = (text or "").strip()
    text = re.sub(r"^Questions?\s+\d+(?:\s*[–-]\s*\d+)?\s*\n+", "", text, flags=re.I)
    return text.strip()


def graded(mine: str, correct: str) -> bool:
    mine = (mine or "").strip()
    correct = (correct or "").strip()
    return bool(mine) and bool(correct) and mine == correct


def build_pack(data: dict, dict_words: dict, pack_id: str, origin: str,
               review: dict | None, guide: dict | None) -> Pack:
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
    questions: list[dict] = []

    def push(no: int, mine: str, correct: str) -> None:
        questions.append({
            "no": no,
            "mine": (mine or "").strip(),
            "correct": graded(mine, correct),
        })

    mcq = data.get("mcq", [])
    if mcq:
        groups.append({
            "id": "mcq",
            "type": "mcq",
            "from": mcq[0]["no"],
            "to": mcq[-1]["no"],
            "instruction": clean_instruction(desc[0]) if len(desc) > 0 else "",
            "items": [
                {
                    "no": q["no"],
                    "stem": q.get("stem", ""),
                    "options": [{"key": o["k"], "text": o["t"]} for o in q.get("options", [])],
                    "answer": q.get("correct", ""),
                    "mine": (q.get("mine") or "").strip(),
                    "correct": graded(q.get("mine", ""), q.get("correct", "")),
                }
                for q in mcq
            ],
        })
        for q in mcq:
            push(q["no"], q.get("mine", ""), q.get("correct", ""))

    summary = data.get("summary")
    if summary:
        groups.append({
            "id": "summary",
            "type": "summary",
            "from": summary["items"][0]["no"],
            "to": summary["items"][-1]["no"],
            "instruction": clean_instruction(desc[1]) if len(desc) > 1 else "",
            "title": summary.get("title", ""),
            "text": summary.get("text", ""),
            "options": [{"key": o["k"], "text": o["t"]} for o in summary.get("options", [])],
            "items": [
                {
                    "no": it["no"],
                    "answer": it.get("correct", ""),
                    "mine": (it.get("mine") or "").strip(),
                    "correct": graded(it.get("mine", ""), it.get("correct", "")),
                }
                for it in summary.get("items", [])
            ],
        })
        for it in summary.get("items", []):
            push(it["no"], it.get("mine", ""), it.get("correct", ""))

    yn = data.get("yn", [])
    if yn:
        groups.append({
            "id": "ynng",
            "type": "ynng",
            "from": yn[0]["no"],
            "to": yn[-1]["no"],
            "instruction": clean_instruction(desc[2]) if len(desc) > 2 else "",
            "items": [
                {
                    "no": q["no"],
                    "stem": q.get("stem", ""),
                    "answer": q.get("correct", ""),
                    "mine": (q.get("mine") or "").strip(),
                    "correct": graded(q.get("mine", ""), q.get("correct", "")),
                }
                for q in yn
            ],
        })
        for q in yn:
            push(q["no"], q.get("mine", ""), q.get("correct", ""))

    attempt = review_pack.attempt_from_items(questions, parse_duration(meta.get("duration", "")))
    by_type = []
    for group in groups:
        total = len(group["items"])
        correct = sum(1 for item in group["items"] if item.get("correct"))
        by_type.append({
            "label": review_pack.TYPE_LABELS.get(group["type"], group["type"]),
            "correct": correct,
            "total": total,
            "accuracy": round(correct / total, 4) if total else 0,
        })
    attempt["byType"] = by_type
    if not attempt["answered"]:
        attempt = None

    return Pack(
        schemaVersion=2,
        id=pack_id,
        kind="reading",
        origin=origin,
        meta=PackMeta(
            book=meta.get("book", ""),
            test=meta.get("test", ""),
            passage=meta.get("passage", ""),
            title=meta.get("title", ""),
            durationSec=parse_duration(meta.get("duration", "")),
            score=meta.get("score", ""),
            source=meta.get("source", ""),
        ),
        attempt=attempt,
        paragraphs=paragraphs,
        questionGroups=groups,
        lexicon=dict_words,
        review=review,
        guide=guide,
    )


def tidy(doc: dict, pack: Pack) -> dict:
    """兼容旧调用。"""
    return review_pack.tidy_pack(doc, pack)


def collect_answers(pack: Pack) -> dict:
    return {
        str(q.no): q.mine
        for g in pack.questionGroups
        for q in g.items
        if q.mine
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--id", default="", help="内容包 id，缺省按书名自动生成")
    ap.add_argument("--origin", default="builtin", choices=["builtin", "custom"])
    ap.add_argument("--analysis", default="", help="外部 analysis.json（review/guide），覆盖页面内嵌内容")
    ap.add_argument("--dump-analysis", default="", help="把归一后的复盘另存为 analysis.json")
    ap.add_argument("--history", action="store_true", help="同时导出旧作答记录")
    ap.add_argument("--post", default="", metavar="http://127.0.0.1:8000",
                    help="导入后把历史记录 POST 到运行中的服务")
    args = ap.parse_args()

    html = Path(args.html)
    src = html.read_text(encoding="utf-8")
    data = js_literal.grab(src, "DATA")
    try:
        dict_words = js_literal.grab(src, "DICT")
    except js_literal.JsLiteralError:
        dict_words = {}

    meta = data.get("meta", {})
    pack_id = args.id or derive_id(meta)

    review = guide = None
    try:
        rev = js_literal.grab(src, "REV")
        means = js_literal.grab(src, "MEANS")
    except js_literal.JsLiteralError:
        rev = means = None
    if rev:
        try:
            sumnote = js_literal.grab(src, "SUMNOTE")
        except js_literal.JsLiteralError:
            sumnote = {}
        try:
            yncite = js_literal.grab(src, "YNCITE")
        except js_literal.JsLiteralError:
            yncite = {}
        review = review_pack.legacy_review(data, rev, sumnote, yncite)
    if means:
        guide = review_pack.legacy_guide(means)

    if args.analysis:
        raw = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
        review, guide = review_pack.normalize_analysis(raw)

    pack = build_pack(data, dict_words, pack_id, args.origin, review, guide)

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
    if pack.attempt:
        print(f"  作答 {pack.attempt.score}/{pack.attempt.total} · "
              f"{pack.attempt.durationSec}s · 错 {pack.attempt.wrong}")
    if pack.review:
        print(f"  复盘 {len(pack.review.get('sections', []))} 组 · "
              f"病灶 {len(pack.review.get('diagnoses', []))} 个")
    if pack.guide:
        print(f"  读懂 {len(pack.guide.get('band', []))} 段结构")
    for msg in review_pack.review_warnings(
        pack.review, pack.paragraphs, {q.no for g in pack.questionGroups for q in g.items}
    ):
        print(f"  警告：{msg}")

    if args.dump_analysis:
        dump_path = Path(args.dump_analysis)
        dump_path.parent.mkdir(parents=True, exist_ok=True)
        dump_path.write_text(
            json.dumps({"packId": pack_id, "review": review, "guide": guide},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"复盘 JSON：{dump_path}")

    if not (args.history or args.post):
        return

    answers = collect_answers(pack)
    history = {
        "packId": pack_id,
        "answers": answers,
        "durationMs": pack.meta.durationSec * 1000,
    }
    if not answers:
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
