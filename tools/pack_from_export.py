#!/usr/bin/env python
"""idictation 导出数据集 + AI 复盘 → 内容包 v2。

这是「阅读复盘」的主路径：先跑 ielts-practice-export 拿到 JSONL，再让 AI
产出 analysis.json（骨架见 docs/AI.md「写作提示词」第 4 节），最后由本脚本合并成站内内容包。

    python tools/pack_from_export.py --export ./ielts-data \
        --book 剑雅18 --test "Test 4" --part "Passage 1" \
        --analysis ./analysis/cam18-t4-p1.json

只依赖标准库 + 后端已装的 pydantic。
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "app" / "server"
TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(TOOLS))

import review_pack  # noqa: E402
from content.loader import Pack, PackMeta, Paragraph, QuestionGroup, Sentence  # noqa: E402

TYPE_MAP = {
    "mcq_single": "mcq",
    "mcq_multi": "mcq",
    "ynng": "ynng",
    "tfng": "tfng",
    "completion_summary": "summary",
    "matching_heading": "matching",
    "matching_paragraph": "matching",
    "matching_feature": "matching",
    "matching_sentence_ending": "matching",
    "matching_other": "matching",
}

TAG_RE = re.compile(r"<[^>]+>")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"缺少文件：{path}")
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def iso_ts(text: Any) -> int:
    raw = str(text or "").strip()
    if not raw:
        return 0
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def plain(text: Any) -> str:
    if text is None:
        return ""
    s = str(text)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n\n", s, flags=re.I)
    s = TAG_RE.sub("", s)
    return html_lib.unescape(s).strip()


def clean_instruction(text: str) -> str:
    text = (text or "").strip()
    return re.sub(r"^Questions?\s+\d+(?:\s*[–-]\s*\d+)?\s*\n+", "", text, flags=re.I).strip()


def label_key(label: Any) -> str:
    return re.sub(r"^(paragraph|para\.?)\s*", "", str(label or "").strip(), flags=re.I)


def normalize_book(book: str) -> str:
    book = (book or "").strip()
    m = re.fullmatch(r"剑雅\s*(\d+)", book)
    return f"剑桥雅思 {m.group(1)}" if m else book


def num(text: str) -> str:
    m = re.search(r"\d+", text or "")
    return m.group(0) if m else ""


def derive_id(book: str, test: str, part: str, fallback: str = "") -> str:
    b, t, p = num(book), num(test), num(part)
    if b and t and p:
        return f"cam{b}-t{t}-p{p}"
    if fallback:
        return f"reading-{fallback}"
    raise SystemExit("无法从 book/test/part 推出 id，请显式传 --id")


def pick_passage(rows: list[dict], args) -> dict:
    for row in rows:
        if args.part_id and str(row.get("part_id")) == str(args.part_id):
            return row
        if args.book and args.test and args.part:
            if (row.get("book") == args.book and row.get("test") == args.test
                    and row.get("part") == args.part):
                return row
        if args.book and args.test and args.part_index:
            if (row.get("book") == args.book and row.get("test") == args.test
                    and str(row.get("part_index")) == str(args.part_index)):
                return row
    raise SystemExit(
        "没有匹配到篇目。用 --part-id，或同时给 --book/--test/--part。\n"
        f"可选篇目示例：{[(r.get('book'), r.get('test'), r.get('part')) for r in rows[:5]]}"
    )


def pick_attempt(rows: list[dict], passage_id: str, attempt_id: str = "") -> dict | None:
    if attempt_id:
        for row in rows:
            if row.get("attempt_id") == attempt_id:
                return row
        raise SystemExit(f"没有找到 attempt：{attempt_id}")
    matched = [r for r in rows if str(r.get("passage_id")) == str(passage_id)]
    if not matched:
        return None
    matched.sort(key=lambda r: r.get("submitted_at") or "")
    return matched[-1]


def build_paragraphs(passage: dict) -> list[Paragraph]:
    raw_sentences = sorted(passage.get("sentences") or [], key=lambda s: s.get("i", 0))
    declared = [label_key(p.get("label")) for p in (passage.get("paragraphs") or []) if p.get("label")]

    paragraphs: list[Paragraph] = []
    if raw_sentences:
        by_label: dict[str, list[dict]] = {}
        for s in raw_sentences:
            by_label.setdefault(label_key(s.get("paragraph")), []).append(s)
        order = declared + [k for k in by_label if k not in declared]
        for no, label in enumerate([k for k in order if by_label.get(k)], start=1):
            sentences = [
                Sentence(id=f"p{no}s{i}", en=plain(s.get("text")), zh=plain(s.get("translation")))
                for i, s in enumerate(by_label[label], start=1)
            ]
            paragraphs.append(Paragraph(no=no, sentences=sentences))
        return paragraphs

    # 没有逐句，只能按段落文本兜底：一段一句，译文留空。
    for no, p in enumerate(passage.get("paragraphs") or [], start=1):
        text = plain(p.get("text"))
        if not text:
            continue
        paragraphs.append(Paragraph(no=no, sentences=[Sentence(id=f"p{no}s1", en=text, zh="")]))
    return paragraphs


def option_list(raw: Any) -> list[dict]:
    out = []
    for o in raw or []:
        if not isinstance(o, dict):
            continue
        key = o.get("key", o.get("k", ""))
        text = o.get("text", o.get("t", ""))
        if key:
            out.append({"key": str(key), "text": plain(text)})
    return out


def build_groups(questions: list[dict], groups: dict[str, dict]) -> list[QuestionGroup]:
    by_group: dict[str, list[dict]] = {}
    for q in questions:
        gid = q.get("group_id") or f"g{q.get('q_number')}"
        by_group.setdefault(gid, []).append(q)

    result: list[QuestionGroup] = []
    for gid, items in by_group.items():
        meta = groups.get(gid, {})
        qtype = meta.get("question_type") or items[0].get("question_type") or "other"
        ptype = TYPE_MAP.get(qtype, "gap")

        body = plain(meta.get("body"))
        text = re.sub(r"\$(\d+)\$", r"{{\1}}", body)
        if ptype == "summary" and "{{" not in text:
            # 没有正文就别硬装成摘要；退回卡片式，题干仍能读。
            ptype = "gap"
            text = ""

        q_items = []
        for q in sorted(items, key=lambda x: (x.get("q_number") or 0)):
            no = q.get("q_number")
            if no is None:
                continue
            no = int(no)
            answer: str | list[str] = str(q.get("correct_answer") or "").strip()
            if q.get("question_type") == "mcq_multi" and "," in answer:
                answer = [part.strip() for part in answer.split(",") if part.strip()]
            q_items.append({
                "no": no,
                "stem": plain(q.get("stem")),
                "options": option_list(q.get("options")),
                "answer": answer,
                "mine": str(q.get("yours") or "").strip(),
                "correct": q.get("is_correct"),
            })
        if not q_items:
            continue
        nos = [it["no"] for it in q_items]
        result.append(QuestionGroup(
            id=gid,
            type=ptype,
            first=min(nos),
            last=max(nos),
            instruction=clean_instruction(plain(meta.get("instruction"))),
            title=plain(meta.get("title")),
            text=text,
            options=option_list(meta.get("options")),
            items=q_items,
        ))
    result.sort(key=lambda g: g.first or 0)
    return result


def build_attempt(attempt: dict | None, groups: list[QuestionGroup]) -> dict | None:
    items = [
        {"no": q.no, "mine": q.mine, "correct": q.correct}
        for g in groups for q in g.items
    ]
    if not items or not attempt:
        return None
    counts = review_pack.attempt_from_items(
        items,
        int(attempt.get("duration_sec") or 0),
        str(attempt.get("submitted_at") or ""),
    )
    by_type = []
    for row in attempt.get("by_type") or []:
        by_type.append({
            "label": row.get("question_type_zh") or row.get("question_type") or "",
            "correct": row.get("correct"),
            "total": row.get("total"),
            "accuracy": row.get("accuracy"),
        })
    counts["byType"] = by_type
    if counts["total"] and not counts["answered"]:
        return None
    return counts


def load_lexicon(args, analysis: dict) -> dict:
    merged: dict[str, str] = {}
    out_path = SERVER / "content" / "packs" / f"{args.id}.json"
    if out_path.exists() and not args.no_keep_lexicon:
        try:
            old = json.loads(out_path.read_text(encoding="utf-8"))
            merged.update(old.get("lexicon") or {})
            print(f"  沿用已有词表 {len(merged)} 条：{out_path.name}")
        except Exception:
            pass
    if args.lexicon:
        raw = json.loads(Path(args.lexicon).read_text(encoding="utf-8"))
        lex = raw.get("lexicon", raw)
        if isinstance(lex, dict):
            merged.update({k: v for k, v in lex.items() if isinstance(v, (str, dict))})
    lex = analysis.get("lexicon")
    if isinstance(lex, dict):
        merged.update({k: v for k, v in lex.items() if isinstance(v, (str, dict))})
    return merged


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", required=True, help="ielts-practice-export 的输出目录")
    ap.add_argument("--id", default="")
    ap.add_argument("--part-id", default="", help="导出里的 part_id（阅读=篇）")
    ap.add_argument("--book", default="")
    ap.add_argument("--test", default="")
    ap.add_argument("--part", default="")
    ap.add_argument("--part-index", default="")
    ap.add_argument("--attempt-id", default="", help="默认取该篇最新一次提交")
    ap.add_argument("--analysis", default="", help="AI 复盘 JSON（review/guide）")
    ap.add_argument("--lexicon", default="", help="额外词表 JSON；也可在 analysis.lexicon 里给")
    ap.add_argument("--no-keep-lexicon", action="store_true", help="不沿用同 id 旧包的词表")
    ap.add_argument("--origin", default="custom", choices=["builtin", "custom"])
    ap.add_argument("--post", default="", metavar="http://127.0.0.1:8000")
    args = ap.parse_args()

    export = Path(args.export)
    passages = read_jsonl(export / "passages.jsonl")
    attempts = read_jsonl(export / "attempts.jsonl")
    questions_all = read_jsonl(export / "questions.jsonl")
    groups_all = read_jsonl(export / "groups.jsonl")

    passage = pick_passage(passages, args)
    attempt = pick_attempt(attempts, passage.get("passage_id"), args.attempt_id)
    attempt_id = (attempt or {}).get("attempt_id")

    questions = [
        q for q in questions_all
        if attempt_id and q.get("attempt_id") == attempt_id
    ]
    if not questions:
        raise SystemExit(
            "这篇在导出里没有作答记录。先确认 idictation 上已完成并提交，"
            "或检查 --attempt-id；当前脚本只建「有作答」的复盘包。"
        )
    groups = {g.get("group_id"): g for g in groups_all
              if g.get("attempt_id") == attempt_id}

    paragraphs = build_paragraphs(passage)
    if not paragraphs:
        raise SystemExit("这篇没有原文段落，检查 passages.jsonl 是否完整")

    question_groups = build_groups(questions, groups)
    if not question_groups:
        raise SystemExit("没有匹配到题目，检查 attempt_id / questions.jsonl")

    analysis: dict = {}
    if args.analysis:
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    review, guide = review_pack.normalize_analysis(analysis)

    book = passage.get("book") or (attempt or {}).get("book") or ""
    test = passage.get("test") or (attempt or {}).get("test") or ""
    part = passage.get("part") or (attempt or {}).get("part") or ""
    pack_id = args.id or derive_id(book, test, part, str(passage.get("part_id") or ""))
    args.id = pack_id

    lexicon = load_lexicon(args, analysis)
    counts = build_attempt(attempt, question_groups)

    meta = PackMeta(
        book=normalize_book(book),
        test=test,
        passage=part,
        title=plain(passage.get("title")),
        durationSec=(counts or {}).get("durationSec", 0),
        score=(f"{counts['score']} / {counts['total']}" if counts else ""),
        source="idictation",
    )
    pack = Pack(
        schemaVersion=2,
        id=pack_id,
        kind="reading",
        origin=args.origin,
        meta=meta,
        attempt=counts,
        paragraphs=paragraphs,
        questionGroups=question_groups,
        lexicon=lexicon,
        review=review,
        guide=guide,
    )

    out_dir = SERVER / "content" / "packs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pack_id}.json"
    out_path.write_text(
        json.dumps(review_pack.tidy_pack(pack.model_dump(by_alias=True, exclude_none=True), pack),
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
    print(f"  复盘 {'有' if pack.review else '无'} / 读懂 {'有' if pack.guide else '无'}")
    if not pack.review:
        print("  提示：没有复盘也能导入，页面会退化成纯精读；补 analysis.json 后重跑即可。")
    else:
        warnings = review_pack.review_warnings(
            pack.review, pack.paragraphs, {q.no for g in pack.questionGroups for q in g.items}
        )
        for msg in warnings:
            print(f"  警告：{msg}")

    if args.post and pack.attempt:
        answers = {str(q.no): q.mine for g in pack.questionGroups for q in g.items if q.mine}
        if answers:
            import urllib.error
            import urllib.request
            payload = {
                "packId": pack_id,
                "answers": answers,
                "durationMs": pack.meta.durationSec * 1000,
            }
            finished = iso_ts((attempt or {}).get("submitted_at"))
            if finished:
                payload["finishedAt"] = finished
            req = urllib.request.Request(
                args.post.rstrip("/") + "/api/reading/history",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    print("已补录成绩：", resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                print("补录失败：", exc.code, exc.read().decode("utf-8", "replace"))


if __name__ == "__main__":
    main()
