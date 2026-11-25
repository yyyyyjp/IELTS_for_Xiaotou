"""把「复盘」内容归一成内容包 v2 的 review / guide 结构。

数据来源有两类：
1. 旧版单文件精读页（const DATA + const REV + const MEANS），字段是作者手写的；
2. AI 直接产出的 analysis.json（推荐路径，骨架见 docs/AI.md「analysis.json 格式」）。

归一后的结构是渲染层唯一的输入，两边必须对齐。字段设计原则：
- 题干、选项、对错留在 questionGroups，复盘只存「分析」；
- 引用写成 {p: 段落号(1 起), b: [段内句序(0 起)]}，也接受 "p3s5" 字符串；
- 任何字段都可以缺，前端逐块降级，不允许因为少一个字段整页白屏。
"""
from __future__ import annotations

import re
from typing import Any

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


def clean_cites(raw: Any) -> list[dict]:
    """统一引文格式：保留 {p,b}，把 "p3s5" 拆成 p=3,b=[4]。"""
    out: list[dict] = []
    if not raw:
        return out
    for item in raw if isinstance(raw, list) else [raw]:
        if isinstance(item, str):
            m = re.fullmatch(r"p(\d+)s(\d+)", item.strip())
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


def attempt_from_items(items: list[dict], duration_sec: int = 0,
                       submitted_at: str = "", by_type: list[dict] | None = None) -> dict:
    total = len(items)
    answered = sum(1 for it in items if str(it.get("mine") or "").strip())
    correct = sum(1 for it in items if it.get("correct") is True)
    blank = total - answered
    wrong = answered - correct
    return {
        "source": "idictation",
        "submittedAt": submitted_at,
        "durationSec": int(duration_sec or 0),
        "score": correct,
        "total": total,
        "answered": answered,
        "blank": blank,
        "wrong": wrong,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "byType": by_type or [],
    }


def _section(kind: str, items: list[dict], title: str = "") -> dict:
    nos = [it["no"] for it in items if isinstance(it.get("no"), int)]
    if not title:
        label = TYPE_LABELS.get(kind, kind)
        if nos:
            a, b = min(nos), max(nos)
            title = f"{label} {a}" if a == b else f"{label} {a}–{b}"
        else:
            title = label
    return {
        "id": kind,
        "kind": kind,
        "title": title,
        "from": min(nos) if nos else None,
        "to": max(nos) if nos else None,
        "items": items,
    }


def legacy_review(data: dict, rev: dict, sumnote: dict | None = None,
                  yncite: dict | None = None) -> dict:
    """旧版精读页的 REV → 统一 review。"""
    sumnote = sumnote or {}
    yncite = yncite or {}
    sections: list[dict] = []

    mcq = data.get("mcq") or []
    if mcq or rev.get("mcq"):
        items: list[dict] = []
        for q in rev.get("mcq") or []:
            items.append({
                "no": int(q["no"]),
                "label": "why-wrong",
                "tag": q.get("tag", ""),
                "diag": q.get("diag", ""),
                "chain": q.get("chain", ""),
                "cites": clean_cites(q.get("cites")),
            })
        # 28 这类「答对了也值得讲」的题，原文单独放在 mcq_note
        if rev.get("mcq_note"):
            have = {it["no"] for it in items}
            no28 = next((q["no"] for q in mcq if q["no"] not in have), None)
            if no28 is not None:
                items.append({
                    "no": int(no28),
                    "label": "why-right",
                    "tag": "选择题",
                    "diag": rev["mcq_note"],
                    "chain": "",
                    "cites": [{"p": 3, "b": [3]}],
                })
        items.sort(key=lambda x: x["no"])
        if items:
            sec = _section("mcq", items)
            sec["diag"] = ""
            sections.append(sec)

    if data.get("summary"):
        rows: list[dict] = []
        for r in rev.get("sum_rows") or []:
            no = int(r["no"])
            rows.append({
                "no": no,
                "minePhrase": r.get("mine_p", ""),
                "corPhrase": r.get("cor_p", ""),
                "src": r.get("src", ""),
                "diag": sumnote.get(no) or sumnote.get(str(no)) or "",
                "cites": [] if r.get("ok", True) else clean_cites(rev.get("sum_cites")),
            })
        if rows:
            sec = _section("summary", [], "摘要填空 " + _range(data["summary"].get("items", [])))
            sec["rows"] = rows
            nos = [int(it["no"]) for it in data["summary"].get("items", []) if "no" in it]
            if nos:
                sec["from"], sec["to"] = min(nos), max(nos)
            sec["diag"] = rev.get("sum_diag", "")
            sec["note"] = rev.get("sum_note", "")
            sec["cites"] = clean_cites(rev.get("sum_cites"))
            sections.append(sec)

    if data.get("yn"):
        items = []
        for r in rev.get("yn_rows") or []:
            no = int(r["no"])
            items.append({
                "no": no,
                "label": "why-right" if r.get("ok") else "why-wrong",
                "tag": "判断题",
                "diag": r.get("j", ""),
                "chain": "",
                "cites": clean_cites(yncite.get(no) or yncite.get(str(no))),
            })
        if items:
            sec = _section("ynng", items)
            sec["diag"] = rev.get("yn_diag", "")
            sections.append(sec)

    return {
        "kicker": rev.get("kicker", ""),
        "title": rev.get("title", ""),
        "lede": rev.get("lede", ""),
        "stats": rev.get("stats") or [],
        "bars": rev.get("bars") or [],
        "sections": sections,
        "diagnoses": rev.get("bad") or [],
        "actions": rev.get("acts") or [],
        "end": rev.get("end", ""),
    }


def _range(items: list[dict]) -> str:
    nos = [int(i["no"]) for i in items if isinstance(i, dict) and "no" in i]
    if not nos:
        return ""
    a, b = min(nos), max(nos)
    return str(a) if a == b else f"{a}–{b}"


def legacy_guide(means: dict) -> dict:
    """旧版精读页的 MEANS → 统一 guide。"""
    band = means.get("band") or []
    counts = {"t": 0, "a": 0, "g": 0}
    for cell in band:
        key = cell.get("s", "")
        if key in counts:
            counts[key] += 1
    legend = means.get("legend")
    if not legend:
        legend = []
        if counts["t"]:
            legend.append({"s": "t", "text": f"作者本人在说话（{counts['t']} 段）"})
        if counts["a"]:
            legend.append({"s": "a", "text": f"反方，或替反方做的假设推演（{counts['a']} 段）"})
        if counts["g"]:
            legend.append({"s": "g", "text": f"中立定义（{counts['g']} 段）"})

    return {
        "kicker": means.get("kicker", ""),
        "title": means.get("title", ""),
        "lede": means.get("lede", ""),
        "thesis": means.get("thesis", ""),
        "structureTitle": means.get("structureTitle", ""),
        "band": band,
        "legend": legend,
        "argument": {
            "negativeTitle": means.get("negativeTitle", "反方在前半篇说的话"),
            "negative": means.get("neg") or [],
            "positiveTitle": means.get("positiveTitle", "作者怎么拆"),
            "positive": means.get("pos") or [],
            "punch": means.get("punch", ""),
        },
        "rows": means.get("rows") or [],
        "terms": means.get("terms") or [],
        "echo": {
            "neg": means.get("echoNeg", ""),
            "pos": means.get("echoPos", ""),
            "note": means.get("echoNote", ""),
        },
        "why": means.get("why") or [],
        "side": means.get("side", ""),
        "end": means.get("end", ""),
    }


def normalize_analysis(raw: dict) -> tuple[dict | None, dict | None]:
    """接受 {review, guide} 或只给其中一个；原样透传但不认识的字段也保留。"""
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


def _normalize_review(rev: dict) -> dict:
    out = dict(rev)
    sections = []
    for i, sec in enumerate(rev.get("sections") or [], start=1):
        s = dict(sec)
        s.setdefault("id", str(i))
        s.setdefault("kind", s.get("type", "gap"))
        s.setdefault("title", TYPE_LABELS.get(s["kind"], s["kind"]))
        for key in ("cites",):
            s[key] = clean_cites(s.get(key))
        if s.get("rows"):
            s["rows"] = [
                {
                    **row,
                    "no": int(row["no"]) if str(row.get("no", "")).isdigit() else row.get("no"),
                    "diag": row.get("diag", ""),
                    "cites": clean_cites(row.get("cites")),
                }
                for row in s["rows"]
            ]
        items = []
        for item in s.get("items") or []:
            it = dict(item)
            if it.get("no") is not None:
                try:
                    it["no"] = int(it["no"])
                except (TypeError, ValueError):
                    pass
            it["label"] = _label(it.get("label", ""))
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
    if "argument" not in out:
        out["argument"] = {}
    arg = dict(out["argument"])
    arg.setdefault("negative", [])
    arg.setdefault("positive", [])
    arg.setdefault("punch", "")
    out["argument"] = arg
    out.setdefault("band", [])
    out.setdefault("legend", [])
    out.setdefault("rows", [])
    out.setdefault("terms", [])
    out.setdefault("why", [])
    if "echo" not in out:
        out["echo"] = {}
    echo = dict(out["echo"])
    echo.setdefault("neg", "")
    echo.setdefault("pos", "")
    echo.setdefault("note", "")
    out["echo"] = echo
    return out


def review_warnings(review: dict | None, paragraphs: list, question_nos: set[int]) -> list[str]:
    """复盘最常见的两类错：题号不存在、引文越界。只告警，不阻断导入。"""
    if not review:
        return []
    limits = {getattr(p, "no", None): len(getattr(p, "sentences", [])) for p in paragraphs}
    out: list[str] = []

    def check_cites(cites, where: str) -> None:
        for cite in cites or []:
            p, b = cite.get("p"), cite.get("b") or []
            if p not in limits:
                out.append(f"{where}: 引文段落 p={p} 不存在")
                continue
            bad = [i for i in b if not (0 <= int(i) < limits[p])]
            if bad:
                out.append(f"{where}: 第 {p} 段没有句序 {bad}（本段 {limits[p]} 句）")

    for sec in review.get("sections", []):
        title = sec.get("title") or sec.get("kind") or "section"
        check_cites(sec.get("cites"), title)
        for item in sec.get("items", []):
            if item.get("no") not in question_nos:
                out.append(f"{title}: 题号 {item.get('no')} 不在本包里")
            check_cites(item.get("cites"), f"{title} 第 {item.get('no')} 题")
        for row in sec.get("rows", []):
            if row.get("no") not in question_nos:
                out.append(f"{title}: 题号 {row.get('no')} 不在本包里")
    return out


def tidy_pack(doc: dict, pack: Any) -> dict:
    """去掉空字段；词表还原成「v. 想象」单行，方便人读与 diff。"""
    doc["meta"] = {k: v for k, v in doc.get("meta", {}).items() if v not in ("", 0, None)}
    doc["lexicon"] = {k: (v.raw or v.gloss) for k, v in pack.lexicon.items()}
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
