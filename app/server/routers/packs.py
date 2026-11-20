"""内容包：列表、详情、热加载、导入自定义词表。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import content.loader as loader
import db
import parser
from content.loader import DeckItem, Pack, PackMeta

router = APIRouter(tags=["packs"])


def _progress() -> dict[str, dict]:
    rows = db.query(
        "SELECT pack_id,"
        " SUM(CASE WHEN kind LIKE 'dictation_%' THEN 1 ELSE 0 END) AS d_n,"
        " SUM(CASE WHEN kind LIKE 'dictation_%' AND correct=1 THEN 1 ELSE 0 END) AS d_c,"
        " SUM(CASE WHEN kind='reading_question' THEN 1 ELSE 0 END) AS r_n,"
        " SUM(CASE WHEN kind='reading_question' AND correct=1 THEN 1 ELSE 0 END) AS r_c,"
        " MAX(created_at) AS last"
        " FROM attempts WHERE pack_id<>'' GROUP BY pack_id"
    )
    return {
        r["pack_id"]: {
            "dictation": {"attempts": r["d_n"] or 0, "correct": r["d_c"] or 0},
            "reading": {"answered": r["r_n"] or 0, "correct": r["r_c"] or 0},
            "lastAt": r["last"],
        }
        for r in rows
    }


EMPTY_PROGRESS = {"dictation": {"attempts": 0, "correct": 0},
                  "reading": {"answered": 0, "correct": 0}, "lastAt": None}


@router.get("/packs")
def list_packs():
    prog = _progress()
    items = []
    for p in loader.all_packs().values():
        s = p.summary()
        s["progress"] = prog.get(p.id, EMPTY_PROGRESS)
        items.append(s)
    items.sort(key=lambda x: (
        x["meta"].get("order") or 999,
        x["meta"].get("book", ""),
        x["meta"].get("test", ""),
        x["meta"].get("passage", ""),
    ))
    return {"items": items, "errors": loader.errors()}


@router.get("/packs/{pack_id}")
def get_pack(pack_id: str, answers: bool = Query(default=False, description="带答案（复盘用）")):
    pack = loader.get(pack_id)
    if not pack:
        raise HTTPException(404, "内容包不存在")
    data = pack.public(with_answers=answers)
    data["progress"] = _progress().get(pack_id, EMPTY_PROGRESS)
    return data


@router.post("/packs/reload")
def reload_packs():
    packs = loader.load_all(force=True)
    return {"loaded": len(packs), "ids": sorted(packs), "errors": loader.errors()}


class ImportText(BaseModel):
    name: str = ""
    text: str = Field(min_length=1, max_length=200_000)
    book: str = "自定义"


@router.post("/packs/import")
def import_text(req: ImportText):
    """把粘贴的词表/例句文本变成 deck 内容包，落盘为 JSON。"""
    rows = parser.parse_text(req.text)
    if not rows:
        raise HTTPException(400, "没有解析出任何条目，检查每行是否有英文句子")

    items = [
        DeckItem(
            word=(r["answers"][0] if r["answers"] else ""),
            sentence=r["text"],
            translation=r["translation"],
            meaning=r["meaning"],
            answers=r["answers"],
        )
        for r in rows
    ]
    pack_id = loader.next_custom_id("deck")
    name = req.name.strip() or f"导入 {pack_id}"
    doc = Pack(
        id=pack_id,
        kind="deck",
        origin="custom",
        meta=PackMeta(book=req.book, title=name, note="由文本导入生成"),
        items=items,
    )
    path = loader.save(doc)
    return {"id": pack_id, "name": name, "count": len(items), "file": path.name}


@router.delete("/packs/{pack_id}")
def delete_pack(pack_id: str):
    pack = loader.get(pack_id)
    if not pack:
        raise HTTPException(404, "内容包不存在")
    if pack.doc.origin != "custom":
        raise HTTPException(400, "内置内容包不能删除，请直接改 content/packs 下的文件")
    pack.path.unlink(missing_ok=True)
    loader.load_all(force=True)
    return {"ok": True}
