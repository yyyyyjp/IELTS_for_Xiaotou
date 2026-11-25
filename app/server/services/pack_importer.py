"""内容包与 AI 复盘导入服务：供 Web 接口与 CLI 共用。

支持两类核心操作：
1. 从 ielts-practice-export 的单篇 JSONL 行（passage / attempt / questions / groups）
   + 可选 AI 复盘文本（analysis.json 或带 Markdown 围栏的 AI 回复）直接构建或更新内容包，
   并幂等写入练习历史（sessions + attempts），不重复计分。
2. 对站内已有阅读内容包单独注入或更新 AI 复盘（review / guide / lexicon），
   返回引文越界、题号缺失等非阻断校验告警（warnings），以及生成发给 AI 的复盘提示词。
"""
from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime
from typing import Any

import content.loader as loader
import db
import services.grading as grading
from content.loader import LexEntry, Pack, PackMeta, Paragraph, QuestionGroup, Sentence

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

TYPE_LABELS = {
    "mcq": "选择题",
    "mcq_single": "选择题",
    "mcq_multi": "多选题",
    "summary": "摘要填空",
    "completion_summary": "摘要填空",
    "ynng": "判断题",
    "tfng": "判断题",
    "gap": "填空题",
    "matching": "匹配题",
    "matching_heading": "标题匹配",
    "matching_paragraph": "段落匹配",
    "matching_feature": "特征匹配",
    "matching_sentence_ending": "句子匹配",
}

LEGACY_LABELS = {
    "为什么对": "why-right",
    "错在哪": "why-wrong",
    "为什么错": "why-wrong",
}

TAG_RE = re.compile(r"<[^>]+>")
FENCE_RE = re.compile(r"```(?:json|jsonc)?\s*\n(.*?)```", re.S | re.I)


# ── 1. 文本清洗与 AI JSON 容错提取 ──────────────────────────────────────


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


def _num(text: str) -> str:
    m = re.search(r"\d+", text or "")
    return m.group(0) if m else ""


def derive_id(book: str, test: str, part: str, fallback: str = "") -> str:
    b, t, p = _num(book), _num(test), _num(part)
    if b and t and p:
        return f"cam{b}-t{t}-p{p}"
    if fallback:
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", fallback).strip("-")
        if safe:
            return f"reading-{safe}"
    raise ValueError("无法从书名/Test/Passage 推导内容包 ID，请手动填写 ID")


def iso_ts(text: Any) -> int:
    raw = str(text or "").strip()
    if not raw:
        return 0
    try:
        return int(datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def extract_json_object(raw_text: str) -> dict:
    """从 AI 回复文本中容错提取 JSON 对象（剥离 Markdown 代码块及首尾解释文字）。"""
    text = (raw_text or "").strip()
    if not text:
        return {}

    candidates: list[str] = []
    for m in FENCE_RE.finditer(text):
        block = m.group(1).strip()
        if block:
            candidates.append(block)
    candidates.append(text)

    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if 0 <= first_brace < last_brace:
        sliced = text[first_brace : last_brace + 1]
        if sliced not in candidates:
            candidates.append(sliced)

    last_err: Exception | None = None
    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict):
                # 兼容直接粘贴 review 顶层对象的情况
                if "review" not in parsed and "guide" not in parsed and (
                    "sections" in parsed or "diagnoses" in parsed
                ):
                    return {"review": parsed}
                return parsed
        except json.JSONDecodeError as exc:
            last_err = exc

    if last_err is not None:
        raise ValueError(
            f"AI 复盘 JSON 解析失败（第 {last_err.lineno} 行第 {last_err.colno} 列：{last_err.msg}）"
        ) from last_err
    raise ValueError("AI 复盘内容必须是一个 JSON 对象")


# ── 2. 复盘结构归一化与校验 ──────────────────────────────────────────────


def clean_cites(raw: Any) -> list[dict]:
    """统一引文格式：保留 {p,b}，支持把 'p3s5' 转为 {p:3, b:[4]}。"""
    out: list[dict] = []
    if not raw:
        return out
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, str):
            m = re.fullmatch(r"p(\d+)s(\d+)", item.strip(), re.I)
            if m:
                out.append({"p": int(m.group(1)), "b": [int(m.group(2)) - 1]})
            continue
        if not isinstance(item, dict):
            continue
        p = item.get("p") or item.get("para") or item.get("paragraph")
        try:
            p = int(p)
        except (TypeError, ValueError):
            continue
        b = item.get("b", item.get("sentences", []))
        if isinstance(b, int):
            b = [b]
        nums: list[int] = []
        for x in b or []:
            try:
                nums.append(int(x))
            except (TypeError, ValueError):
                continue
        if not nums and item.get("s") is not None:
            try:
                nums = [int(item["s"]) - 1]
            except (TypeError, ValueError):
                pass
        out.append({"p": p, "b": nums})
    return out


def _label(value: str) -> str:
    value = (value or "").strip()
    return LEGACY_LABELS.get(value, value)


def _normalize_review(rev: dict) -> dict:
    out = dict(rev)
    sections = []
    for i, sec in enumerate(rev.get("sections") or [], start=1):
        if not isinstance(sec, dict):
            continue
        s = dict(sec)
        s.setdefault("id", str(i))
        s.setdefault("kind", s.get("type", "gap"))
        s.setdefault("title", TYPE_LABELS.get(s["kind"], s["kind"]))
        s["cites"] = clean_cites(s.get("cites"))
        if s.get("rows"):
            s["rows"] = [
                {
                    **row,
                    "no": int(row["no"]) if str(row.get("no", "")).isdigit() else row.get("no"),
                    "diag": row.get("diag", ""),
                    "cites": clean_cites(row.get("cites")),
                }
                for row in s["rows"]
                if isinstance(row, dict)
            ]
        items = []
        for item in s.get("items") or []:
            if not isinstance(item, dict):
                continue
            it = dict(item)
            if it.get("no") is not None:
                try:
                    it["no"] = int(it["no"])
                except (TypeError, ValueError):
                    pass
            it["label"] = _label(str(it.get("label", "")))
            it["cites"] = clean_cites(it.get("cites"))
            items.append(it)
        s["items"] = items
        sections.append(s)
    out["sections"] = sections
    out.setdefault("diagnoses", [])
    out.setdefault("actions", [])
    return out


def _normalize_guide(guide: dict) -> dict:
    out = dict(guide)
    arg = dict(out.get("argument") or {}) if isinstance(out.get("argument"), dict) else {}
    arg.setdefault("negative", [])
    arg.setdefault("positive", [])
    arg.setdefault("punch", "")
    out["argument"] = arg
    out.setdefault("band", [])
    out.setdefault("legend", [])
    out.setdefault("rows", [])
    out.setdefault("terms", [])
    out.setdefault("why", [])
    echo = dict(out.get("echo") or {}) if isinstance(out.get("echo"), dict) else {}
    echo.setdefault("neg", "")
    echo.setdefault("pos", "")
    echo.setdefault("note", "")
    out["echo"] = echo
    return out


def normalize_analysis(raw: dict) -> tuple[dict | None, dict | None]:
    if not isinstance(raw, dict):
        return None, None
    review = raw.get("review")
    guide = raw.get("guide")
    if review is not None and not isinstance(review, dict):
        review = None
    if guide is not None and not isinstance(guide, dict):
        guide = None
    if review:
        review = _normalize_review(review)
    if guide:
        guide = _normalize_guide(guide)
    return review, guide


def validate_analysis(
    review: dict | None,
    guide: dict | None,
    paragraphs: list[Paragraph],
    question_nos: set[int],
) -> list[str]:
    """检查题号不存在、引文段落或段内句序越界、导读段落号越界等潜在问题。"""
    limits = {p.no: len(p.sentences) for p in paragraphs}
    out: list[str] = []

    def check_cites(cites: Any, where: str) -> None:
        for cite in cites or []:
            p, b = cite.get("p"), cite.get("b") or []
            if p not in limits:
                out.append(f"{where}：引文段落 p={p} 不存在（共 {len(limits)} 段）")
                continue
            bad = [i for i in b if not (0 <= int(i) < limits[p])]
            if bad:
                out.append(f"{where}：第 {p} 段没有句序 {bad}（本段句序范围 0–{limits[p] - 1}）")

    if review:
        if not str(review.get("title") or "").strip():
            out.append("review 缺少顶层 title（复盘一句话标题）")
        for sec in review.get("sections") or []:
            title = sec.get("title") or sec.get("kind") or "section"
            check_cites(sec.get("cites"), title)
            for item in sec.get("items") or []:
                if question_nos and item.get("no") not in question_nos:
                    out.append(f"{title}：题号 {item.get('no')} 不在本篇题号范围内")
                check_cites(item.get("cites"), f"{title} 第 {item.get('no')} 题")
            for row in sec.get("rows") or []:
                if question_nos and row.get("no") not in question_nos:
                    out.append(f"{title}：题号 {row.get('no')} 不在本篇题号范围内")
                check_cites(row.get("cites"), f"{title} 第 {row.get('no')} 空")

    if guide and limits:
        for cell in guide.get("band") or []:
            if isinstance(cell, dict) and cell.get("n") not in limits:
                out.append(f"guide.band：段落号 n={cell.get('n')} 超出原文段落范围")
        for row in guide.get("rows") or []:
            if isinstance(row, dict) and row.get("n") not in limits:
                out.append(f"guide.rows：段落号 n={row.get('n')} 超出原文段落范围")

    return out


def summarize_analysis(review: dict | None, guide: dict | None, lexicon_added: int = 0) -> dict:
    covered_nos: set[int] = set()
    section_count = 0
    if review:
        sections = review.get("sections") or []
        section_count = len(sections)
        for sec in sections:
            for it in sec.get("items") or []:
                if isinstance(it.get("no"), int):
                    covered_nos.add(it["no"])
            for row in sec.get("rows") or []:
                if isinstance(row.get("no"), int):
                    covered_nos.add(row["no"])
    return {
        "hasReview": bool(review),
        "reviewTitle": (review or {}).get("title") or "",
        "sectionCount": section_count,
        "coveredQuestions": len(covered_nos),
        "diagnosisCount": len((review or {}).get("diagnoses") or []),
        "hasGuide": bool(guide),
        "guideTitle": (guide or {}).get("title") or "",
        "bandCount": len((guide or {}).get("band") or []),
        "lexiconCount": lexicon_added,
    }


def tidy_pack_dict(doc: dict, pack: Pack) -> dict:
    """精简落盘 JSON，保持与 CLI 生成产物一致。"""
    doc["meta"] = {k: v for k, v in doc.get("meta", {}).items() if v not in ("", 0, None)}
    doc["lexicon"] = {k: (v.raw or (f"{v.pos} {v.gloss}".strip() if v.pos else v.gloss))
                      for k, v in pack.lexicon.items()}
    if not doc.get("lexicon"):
        doc.pop("lexicon", None)
    if not doc.get("items"):
        doc.pop("items", None)
    for key in ("attempt", "review", "guide"):
        if not doc.get(key):
            doc.pop(key, None)
    for g in doc.get("questionGroups", []):
        for key in ("title", "text", "options", "instruction"):
            if not g.get(key):
                g.pop(key, None)
        for it in g.get("items", []):
            for key in ("stem", "options"):
                if not it.get(key):
                    it.pop(key, None)
            if it.get("mine") == "":
                it.pop("mine", None)
    return doc


def write_pack_file(pack: Pack) -> None:
    path = loader.config.PACK_DIR / f"{pack.id}.json"
    raw = pack.model_dump(by_alias=True, exclude_none=True)
    tidied = tidy_pack_dict(raw, pack)
    path.write_text(json.dumps(tidied, ensure_ascii=False, indent=2), encoding="utf-8")
    loader.load_all(force=True)


# ── 3. 从 idictation 导出构建内容包 ──────────────────────────────────────


def build_paragraphs(passage: dict) -> list[Paragraph]:
    raw_sentences = sorted(passage.get("sentences") or [], key=lambda s: s.get("i", 0))
    declared = [label_key(p.get("label")) for p in (passage.get("paragraphs") or []) if p.get("label")]

    paragraphs: list[Paragraph] = []
    if raw_sentences:
        by_label: dict[str, list[dict]] = {}
        for s in raw_sentences:
            by_label.setdefault(label_key(s.get("paragraph")), []).append(s)
        order = declared + [k for k in by_label if k not in declared]
        seen: set[str] = set()
        ordered_unique = []
        for k in order:
            if k not in seen and by_label.get(k):
                seen.add(k)
                ordered_unique.append(k)
        for no, label in enumerate(ordered_unique, start=1):
            sentences = [
                Sentence(id=f"p{no}s{i}", en=plain(s.get("text")), zh=plain(s.get("translation")))
                for i, s in enumerate(by_label[label], start=1)
            ]
            paragraphs.append(Paragraph(no=no, sentences=sentences))
        return paragraphs

    for no, p in enumerate(passage.get("paragraphs") or [], start=1):
        text = plain(p.get("text"))
        if not text:
            continue
        paragraphs.append(Paragraph(no=no, sentences=[Sentence(id=f"p{no}s1", en=text, zh="")]))
    return paragraphs


def _option_list(raw: Any) -> list[dict]:
    out = []
    for o in raw or []:
        if not isinstance(o, dict):
            continue
        key = o.get("key", o.get("k", ""))
        text = o.get("text", o.get("t", ""))
        if key:
            out.append({"key": str(key), "text": plain(text)})
    return out


def build_groups(questions: list[dict], groups_list: list[dict]) -> list[QuestionGroup]:
    groups = {g.get("group_id"): g for g in groups_list if isinstance(g, dict) and g.get("group_id")}
    by_group: dict[str, list[dict]] = {}
    for q in questions:
        if not isinstance(q, dict):
            continue
        gid = q.get("group_id") or f"g{q.get('q_number')}"
        by_group.setdefault(gid, []).append(q)

    result: list[QuestionGroup] = []
    for gid, items in by_group.items():
        meta = groups.get(gid, {})
        qtype = meta.get("question_type") or items[0].get("question_type") or "other"
        ptype = TYPE_MAP.get(qtype, "gap")

        sorted_qs = sorted(
            [q for q in items if q.get("q_number") is not None],
            key=lambda x: float(x["q_number"]),
        )
        qid_to_no: dict[str, int] = {}
        valid_nos: set[int] = set()
        for q in sorted_qs:
            qno = int(float(q["q_number"]))
            valid_nos.add(qno)
            qid_tail = str(q.get("question_id") or "").rsplit(":", 1)[-1]
            if qid_tail.isdigit():
                qid_to_no[qid_tail] = qno

        def _replace_blank(m: re.Match[str]) -> str:
            raw_n = m.group(1)
            if raw_n in qid_to_no:
                resolved = qid_to_no[raw_n]
            elif int(raw_n) in valid_nos:
                resolved = int(raw_n)
            elif 1 <= int(raw_n) <= len(sorted_qs):
                resolved = int(float(sorted_qs[int(raw_n) - 1]["q_number"]))
            else:
                resolved = int(raw_n)
            return f"{{{{{resolved}}}}}"

        body = plain(meta.get("body"))
        text = re.sub(r"\$(\d+)\$", _replace_blank, body)
        text = re.sub(r"([A-Za-z0-9])(\{\{\d+\}\})", r"\1 \2", text)
        text = re.sub(r"(\{\{\d+\}\})([A-Za-z0-9])", r"\1 \2", text)
        if ptype == "summary" and "{{" not in text:
            ptype = "gap"
            text = ""

        q_items = []
        seen_nos: set[int] = set()
        for q in sorted_qs:
            no = int(float(q["q_number"]))
            if no in seen_nos:
                continue
            seen_nos.add(no)
            answer: str | list[str] = str(q.get("correct_answer") or "").strip()
            if q.get("question_type") == "mcq_multi" and "," in answer:
                answer = [part.strip() for part in answer.split(",") if part.strip()]
            q_items.append({
                "no": no,
                "stem": plain(q.get("stem")) if ptype != "summary" else "",
                "options": _option_list(q.get("options")) if ptype == "mcq" else [],
                "answer": answer,
                "mine": str(q.get("yours") or "").strip(),
                "correct": q.get("is_correct"),
            })
        if not q_items:
            continue
        nos = [it["no"] for it in q_items]
        result.append(QuestionGroup(
            id=str(gid),
            type=ptype,
            first=min(nos),
            last=max(nos),
            instruction=clean_instruction(plain(meta.get("instruction"))),
            title=plain(meta.get("title")),
            text=text,
            options=_option_list(meta.get("options")),
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
    total = len(items)
    answered = sum(1 for it in items if str(it.get("mine") or "").strip())
    correct = sum(1 for it in items if it.get("correct") is True)
    if total and not answered:
        return None
    by_type = []
    for row in attempt.get("by_type") or []:
        if not isinstance(row, dict):
            continue
        by_type.append({
            "label": row.get("question_type_zh") or row.get("question_type") or "",
            "correct": row.get("correct"),
            "total": row.get("total"),
            "accuracy": row.get("accuracy"),
        })
    return {
        "source": "idictation",
        "submittedAt": str(attempt.get("submitted_at") or ""),
        "durationSec": int(attempt.get("duration_sec") or 0),
        "score": correct,
        "total": total,
        "answered": answered,
        "blank": total - answered,
        "wrong": answered - correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "byType": by_type,
    }


def _merge_lexicon(existing: dict[str, LexEntry] | None, incoming: Any, keep: bool) -> tuple[dict[str, Any], int]:
    merged: dict[str, Any] = {}
    if keep and existing:
        for k, v in existing.items():
            merged[k] = v.model_dump()
    added = 0
    if isinstance(incoming, dict):
        for k, v in incoming.items():
            if isinstance(v, (str, dict)) and str(k).strip():
                key = str(k).strip()
                if key not in merged:
                    added += 1
                merged[key] = v
    return merged, added


def import_from_export(
    passage: dict,
    questions: list[dict],
    groups: list[dict],
    attempt: dict | None = None,
    analysis_text: str = "",
    pack_id_override: str = "",
    keep_lexicon: bool = True,
    record_history: bool = True,
    dry_run: bool = False,
) -> dict:
    if not isinstance(passage, dict) or not passage:
        raise ValueError("缺少原文数据（passage）")
    paragraphs = build_paragraphs(passage)
    if not paragraphs:
        raise ValueError("这篇没有原文段落，请检查 passages.jsonl 是否完整")

    question_groups = build_groups(questions, groups)
    if not question_groups:
        raise ValueError("没有匹配到题目数据，请检查 questions.jsonl 与 attempt_id 是否匹配")

    analysis_raw = extract_json_object(analysis_text) if (analysis_text or "").strip() else {}
    review, guide = normalize_analysis(analysis_raw)

    book = str(passage.get("book") or (attempt or {}).get("book") or "")
    test = str(passage.get("test") or (attempt or {}).get("test") or "")
    part = str(passage.get("part") or (attempt or {}).get("part") or "")
    pack_id = (
        pack_id_override.strip()
        or str(analysis_raw.get("packId") or "").strip()
        or derive_id(book, test, part, str(passage.get("part_id") or passage.get("passage_id") or ""))
    )

    existing = loader.get(pack_id)
    origin = existing.doc.origin if existing else "custom"
    lexicon, lex_added = _merge_lexicon(
        existing.doc.lexicon if existing else None,
        analysis_raw.get("lexicon"),
        keep=keep_lexicon,
    )

    # 若重新导入时未填 review/guide，而旧包已有，默认保留旧包的复盘以免误冲掉
    final_review = review if review is not None else (existing.doc.review if existing else None)
    final_guide = guide if guide is not None else (existing.doc.guide if existing else None)

    counts = build_attempt(attempt, question_groups)
    if counts is None and existing and existing.doc.attempt:
        counts = existing.doc.attempt.model_dump()

    meta = PackMeta(
        book=normalize_book(book) or (existing.doc.meta.book if existing else ""),
        test=test or (existing.doc.meta.test if existing else ""),
        passage=part or (existing.doc.meta.passage if existing else ""),
        title=plain(passage.get("title")) or (existing.doc.meta.title if existing else pack_id),
        durationSec=(counts or {}).get("durationSec", 0),
        score=(f"{counts['score']} / {counts['total']}" if counts else ""),
        source="idictation",
        order=existing.doc.meta.order if existing else 0,
    )

    pack = Pack(
        schemaVersion=2,
        id=pack_id,
        kind="reading",
        origin=origin,
        meta=meta,
        attempt=counts,
        paragraphs=paragraphs,
        questionGroups=question_groups,
        lexicon=lexicon,
        review=final_review,
        guide=final_guide,
    )

    q_nos = {q.no for g in pack.questionGroups for q in g.items}
    warnings = validate_analysis(review, guide, pack.paragraphs, q_nos)
    analysis_summary = summarize_analysis(final_review, final_guide, lex_added)

    history_recorded = False
    if not dry_run:
        write_pack_file(pack)
        if record_history and pack.attempt:
            submitted_iso = str((attempt or {}).get("submitted_at") or pack.attempt.submittedAt or "")
            history_recorded = record_attempt_history(pack, submitted_iso)

    return {
        "id": pack.id,
        "exists": existing is not None,
        "created": existing is None and not dry_run,
        "dryRun": dry_run,
        "meta": pack.meta.model_dump(),
        "counts": {
            "paragraphs": len(pack.paragraphs),
            "sentences": pack.sentence_count,
            "questions": pack.question_count,
            "words": len(pack.lexicon),
        },
        "attempt": pack.attempt.model_dump() if pack.attempt else None,
        "analysis": analysis_summary,
        "warnings": warnings,
        "historyRecorded": history_recorded,
    }


def apply_analysis_to_pack(
    pack_id: str,
    analysis_text: str,
    keep_lexicon: bool = True,
    dry_run: bool = False,
) -> dict:
    loaded = loader.get(pack_id)
    if not loaded:
        raise LookupError(f"内容包不存在：{pack_id}")
    if loaded.doc.kind != "reading":
        raise ValueError("只有精读篇目支持导入 AI 复盘")

    raw = extract_json_object(analysis_text)
    if not raw:
        raise ValueError("请粘贴 AI 输出的复盘 JSON 内容")

    review, guide = normalize_analysis(raw)
    incoming_lex = raw.get("lexicon")
    if review is None and guide is None and not isinstance(incoming_lex, dict):
        raise ValueError("JSON 中未识别到 review、guide 或 lexicon 字段")

    lexicon, lex_added = _merge_lexicon(loaded.doc.lexicon, incoming_lex, keep=keep_lexicon)
    doc_data = loaded.doc.model_dump(by_alias=True)
    doc_data["lexicon"] = lexicon
    if review is not None:
        doc_data["review"] = review
    if guide is not None:
        doc_data["guide"] = guide

    updated = Pack.model_validate(doc_data)
    q_nos = {q.no for g in updated.questionGroups for q in g.items}
    warnings = validate_analysis(review, guide, updated.paragraphs, q_nos)

    if not dry_run:
        write_pack_file(updated)

    return {
        "id": updated.id,
        "exists": True,
        "dryRun": dry_run,
        "meta": updated.meta.model_dump(),
        "analysis": summarize_analysis(updated.review, updated.guide, lex_added),
        "warnings": warnings,
    }


def record_attempt_history(pack: Pack, submitted_at_iso: str = "") -> bool:
    """幂等补录阅读历史成绩：同 pack_id + 同完卷时间戳已存在时跳过，避免重复统计。"""
    answers = {str(q.no): q.mine for g in pack.questionGroups for q in g.items if q.mine}
    if not answers:
        return False

    finished = iso_ts(submitted_at_iso) or db.now()
    if submitted_at_iso:
        dup = db.one(
            "SELECT id FROM sessions WHERE kind='reading' AND mode='history' AND pack_id=? AND ended_at=?",
            (pack.id, finished),
        )
        if dup:
            return False

    duration_ms = int((pack.attempt.durationSec if pack.attempt else pack.meta.durationSec) or 0) * 1000
    started = finished - int(duration_ms / 1000)
    loaded = loader.get(pack.id)
    index = loaded.question_index() if loaded else {
        q.no: (g, q) for g in pack.questionGroups for q in g.items
    }
    nos = sorted(index)
    sid = db.new_id("rs")

    now = db.now()
    db.execute(
        "INSERT INTO sessions(id,kind,pack_id,mode,planned,answered,correct,meta,started_at,ended_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            sid,
            "reading",
            pack.id,
            "history",
            len(nos),
            0,
            0,
            json.dumps({"nos": nos, "imported": True, "submittedAt": submitted_at_iso}, ensure_ascii=False),
            started,
            finished,
            now,
        ),
    )

    correct_count = 0
    for no in nos:
        group, q = index[no]
        expected = q.answer_list()
        user = answers.get(str(no), "")
        res = grading.compare(expected, user)
        if res["ok"]:
            correct_count += 1
        db.insert_attempt(
            kind="reading_question",
            ref=str(no),
            pack_id=pack.id,
            session_id=sid,
            input=str(user),
            expected="|".join(expected),
            correct=1 if res["ok"] else 0,
            meta=json.dumps({"group": group.id, "type": group.type}, ensure_ascii=False),
            created_at=finished,
        )

    db.execute(
        "UPDATE sessions SET answered=?, correct=?, meta=?, updated_at=? WHERE id=?",
        (
            len(nos),
            correct_count,
            json.dumps(
                {
                    "nos": nos,
                    "imported": True,
                    "submittedAt": submitted_at_iso,
                    "answers": answers,
                    "durationMs": duration_ms,
                },
                ensure_ascii=False,
            ),
            now,
            sid,
        ),
    )
    return True


# ── 4. 生成给 AI 的标准复盘提示词 ─────────────────────────────────────────


SCHEMA_SPEC = """请严格只输出一个合法 JSON 对象（不要用 Markdown 代码块包裹，不要前后解释文字），结构如下：
{
  "review": {
    "kicker": "复盘 · 书名 · Test · Passage",
    "title": "一句话点破本篇核心失分症结",
    "lede": "总述段落（可用 <b> 加粗、<em> 标原文词句）。",
    "sections": [
      {
        "kind": "mcq | summary | ynng | tfng | gap | matching（严格按题组类型选一）",
        "title": "题组标题，如 选择题 27–30",
        "from": 27,
        "to": 30,
        "diag": "本组共性诊断",
        "items": [
          {
            "no": 27,
            "label": "why-wrong 或 why-right",
            "tag": "错因短标签或题型名",
            "diag": "为什么错 / 为什么对（结合我的作答与高亮定位分析）",
            "chain": "正确同义替换链条",
            "cites": [{"p": 1, "b": [2, 3]}]
          }
        ],
        "rows": [
          {
            "no": 31,
            "minePhrase": "我填的词/对应选项短语（仅 kind=summary 时使用 rows，其余题型全部用 items）",
            "corPhrase": "正确答案词/选项短语",
            "src": "原文依据短语",
            "diag": "逐空诊断",
            "cites": [{"p": 7, "b": [1]}]
          }
        ]
      }
    ],
    "diagnoses": [{"n": "病灶 01", "t": "四字或短标题", "p": "跨题共性归因……"}],
    "actions": ["下一篇可直接执行的动作 1……", "动作 2……"],
    "end": "收尾总结一句话。"
  },
  "guide": {
    "kicker": "读懂 · 书名 · Test · Passage",
    "title": "一句话讲清这篇文章在干什么",
    "lede": "全文导读总述。",
    "thesis": "作者核心主旨句。",
    "structureTitle": "段落推进结构标题",
    "band": [{"n": 1, "f": "4-6字段落功能", "s": "t（作者观点）| a（反方/靶子/受限假设）| g（背景/中立陈述）"}],
    "legend": [{"s": "t", "text": "图例说明"}],
    "argument": {
      "negativeTitle": "反方 / 靶子观点",
      "negative": [{"t": "要点标题", "p": "（第 X 段）具体展开……"}],
      "positiveTitle": "作者立场 / 拆解",
      "positive": [{"t": "要点标题", "p": "（第 Y 段）具体展开……"}],
      "punch": "论证最终落点。"
    },
    "rows": [{"n": 1, "w": "说话人/角色", "s": "t|a|g", "d": "这一段在全文论证里干什么。"}],
    "terms": [{"k": "核心概念中文或缩写", "en": "English term", "d": "在本文语境下的含义与作用。"}],
    "echo": {"neg": "前文铺垫/设问", "pos": "后文回应/反转", "note": "首尾呼应点拨"},
    "why": [{"t": "第 X 段为什么难读", "p": "长难句或修辞障碍拆解……"}],
    "end": "导读收尾。"
  },
  "lexicon": {
    "word_or_phrase": "n. 本文语境下的精准中文释义（挑 15-30 个本篇高频学术词/同义替换词）"
  }
}

硬性约束：
1. cites 里的 p 从 1 开始（对应下方 [p1]），b 是「段内句序」从 0 开始（严格对应下方每句标好的 b=0, b=1...，切勿用全文句序）！
2. 题型 kind 只能取 mcq / summary / ynng / tfng / gap / matching 之一；只有 kind="summary" 时用 rows[]，其他题型一律用 items[]，且每道题的 no 必须与下方题号完全一致（答对但值得讲同义替换的题也可放入，label 填 "why-right"）。
3. band[].s 和 rows[].s 只能取 "t"、"a"、"g" 之一；band 和 rows 的 n 必须是真实存在的段落号。"""


def _format_marks_section(attempt: dict | None) -> list[str]:
    if not isinstance(attempt, dict):
        return []
    marks = attempt.get("marks")
    if not isinstance(marks, dict):
        return []
    highlights = marks.get("highlights") or []
    notes = marks.get("notes") or []
    if not highlights and not notes:
        return []

    out: list[str] = ["\n## 二（附）、我在做题时留下的高亮与笔记轨迹（可用于辅助诊断定位偏差）"]
    art_by_p: dict[str, list[str]] = {}
    q_by_no: dict[str, list[str]] = {}
    for h in highlights:
        if not isinstance(h, dict):
            continue
        txt = plain(h.get("text"))
        if not txt or len(txt) < 2:
            continue
        if h.get("scope") == "question" or h.get("question_number") is not None:
            key = f"Q{h.get('question_number')}" if h.get("question_number") is not None else "题干区"
            if txt not in q_by_no.setdefault(key, []):
                q_by_no[key].append(txt)
        else:
            key = f"段落 {h.get('paragraph') or '?'}"
            if txt not in art_by_p.setdefault(key, []):
                art_by_p[key].append(txt)

    if art_by_p:
        out.append("- 原文高亮：")
        for k, items in art_by_p.items():
            out.append(f"  - {k}：{' / '.join(items[:20])}")
    if q_by_no:
        out.append("- 题干高亮：")
        for k, items in q_by_no.items():
            out.append(f"  - {k}：{' / '.join(items[:15])}")
    if notes:
        note_texts = [plain(n.get("content")) for n in notes if isinstance(n, dict) and plain(n.get("content"))]
        if note_texts:
            out.append(f"- 随手笔记：{' / '.join(note_texts[:20])}")
    return out


def build_prompt_for_pack(pack: Pack, raw_attempt: dict | None = None) -> str:
    lines: list[str] = []
    label = pack.meta.label
    lines.append("请为我的雅思阅读练习生成深度复盘与文章结构导读 JSON。")
    lines.append(f"篇目：{label} · {pack.meta.title}")
    if pack.attempt:
        mins = pack.attempt.durationSec // 60
        secs = pack.attempt.durationSec % 60
        lines.append(
            f"成绩：{pack.attempt.score} / {pack.attempt.total}（错 {pack.attempt.wrong}，空 {pack.attempt.blank}），用时 {mins}:{secs:02d}"
        )
    lines.append("")
    lines.append("## 一、原文（已按 [p段号, b=段内0起句序] 标号，写 cites 时请直接引用）")
    for p in pack.paragraphs:
        lines.append(f"\n### 第 {p.no} 段")
        for idx, s in enumerate(p.sentences):
            lines.append(f"[p{p.no}, b={idx}] {s.en}")

    lines.append("\n## 二、题目与我的作答")
    for g in pack.questionGroups:
        lines.append(f"\n### 题组 {g.first}–{g.last}（kind={g.type}）")
        if g.instruction:
            lines.append(f"指令：{g.instruction}")
        if g.title:
            lines.append(f"标题：{g.title}")
        if g.text:
            lines.append(f"摘要正文：{g.text}")
        if g.options:
            opts = " | ".join(f"{o.key}: {o.text}" for o in g.options)
            lines.append(f"共用选项池：{opts}")
        for q in g.items:
            ans = "/".join(q.answer_list())
            status = "✓正确" if q.correct is True else ("✗错误" if q.mine else "○未答")
            line = f"- Q{q.no} [{status}] 我的作答={q.mine or '(空)'} | 正确答案={ans}"
            if q.stem:
                line += f" | 题干：{q.stem}"
            lines.append(line)
            if q.options:
                for o in q.options:
                    lines.append(f"    {o.key}. {o.text}")

    lines.extend(_format_marks_section(raw_attempt))

    lines.append("\n## 三、输出 JSON 格式要求")
    lines.append(SCHEMA_SPEC)
    return "\n".join(lines)


def build_prompt_from_export(
    passage: dict,
    questions: list[dict],
    groups: list[dict],
    attempt: dict | None = None,
) -> dict:
    paragraphs = build_paragraphs(passage)
    if not paragraphs:
        raise ValueError("这篇没有原文段落")
    question_groups = build_groups(questions, groups)
    if not question_groups:
        raise ValueError("没有匹配到题目数据")
    book = str(passage.get("book") or (attempt or {}).get("book") or "")
    test = str(passage.get("test") or (attempt or {}).get("test") or "")
    part = str(passage.get("part") or (attempt or {}).get("part") or "")
    pack_id = derive_id(book, test, part, str(passage.get("part_id") or passage.get("passage_id") or "tmp"))
    counts = build_attempt(attempt, question_groups)
    pack = Pack(
        schemaVersion=2,
        id=pack_id,
        kind="reading",
        origin="custom",
        meta=PackMeta(
            book=normalize_book(book),
            test=test,
            passage=part,
            title=plain(passage.get("title")) or pack_id,
            durationSec=(counts or {}).get("durationSec", 0),
        ),
        attempt=counts,
        paragraphs=paragraphs,
        questionGroups=question_groups,
    )
    return {
        "id": pack.id,
        "title": pack.meta.title,
        "label": pack.meta.label,
        "prompt": build_prompt_for_pack(pack, raw_attempt=attempt),
    }
