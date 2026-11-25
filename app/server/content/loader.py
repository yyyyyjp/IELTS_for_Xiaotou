"""内容包：一篇精读 / 一个词表 = 一个 JSON 文件。

内容与学习记录分离，是为了两件事：
1. 加一篇新剑雅，只加一个 JSON，不用改代码、不用数据库迁移；
2. 记录表的改版不会碰教材，教材的改版也不会碰记录。

文件位置：server/content/packs/*.json（可用 XIAOTOU_CONTENT_DIR 覆盖）。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

import config

log = logging.getLogger("packs")

POS_RE = re.compile(r"^((?:[a-z]+\.)(?:\s*/\s*[a-z]+\.)*)\s*(.+)$", re.I)


class Option(BaseModel):
    key: str
    text: str


class Question(BaseModel):
    model_config = ConfigDict(extra="allow")

    no: int
    stem: str = ""
    options: list[Option] = Field(default_factory=list)
    answer: str | list[str] = ""
    mine: str = ""                     # 我在 idictation 上的作答；空 = 未作答
    correct: bool | None = None        # 站点判定；None = 无记录

    def answer_list(self) -> list[str]:
        a = self.answer
        if isinstance(a, list):
            return [str(x).strip() for x in a if str(x).strip()]
        a = str(a).strip()
        return [a] if a else []


class QuestionGroup(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = ""
    type: str = "mcq"           # mcq | summary | ynng | tfng | gap | matching
    first: int | None = Field(default=None, alias="from")
    last: int | None = Field(default=None, alias="to")
    instruction: str = ""
    title: str = ""
    text: str = ""               # summary 类题干的 {{31}} 占位文本
    options: list[Option] = Field(default_factory=list)  # 组内共用选项
    items: list[Question] = Field(default_factory=list)

    def numbers(self) -> list[int]:
        return [q.no for q in self.items]


class Sentence(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = ""
    en: str
    zh: str = ""


class Paragraph(BaseModel):
    no: int
    sentences: list[Sentence]


class PackMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    book: str = ""
    test: str = ""
    passage: str = ""
    title: str = ""
    durationSec: int = 0
    score: str = ""            # 旧版页面上手记的成绩，仅作展示
    source: str = ""
    note: str = ""
    order: int = 0

    @property
    def label(self) -> str:
        parts = [self.book, self.test, self.passage]
        return " · ".join([p for p in parts if p]) or self.title


class Attempt(BaseModel):
    """一次站外作答（目前来自 idictation 导出）的元信息。"""

    model_config = ConfigDict(extra="allow")

    source: str = "idictation"
    submittedAt: str = ""
    durationSec: int = 0
    score: int = 0
    total: int = 0
    answered: int = 0
    blank: int = 0
    wrong: int = 0
    accuracy: float = 0.0
    byType: list[dict] = Field(default_factory=list)


class LexEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    pos: str = ""
    gloss: str = ""
    phonetic: str = ""
    note: str = ""
    raw: str = ""

    @model_validator(mode="before")
    @classmethod
    def _from_string(cls, v):
        """允许 lexicon 简写成 {"word": "v. 想象；设想"}。"""
        if isinstance(v, str):
            raw = v.strip()
            m = POS_RE.match(raw)
            if m:
                return {"pos": m.group(1).strip(), "gloss": m.group(2).strip(), "raw": raw}
            return {"gloss": raw, "raw": raw}
        return v


class DeckItem(BaseModel):
    """kind=deck 时的扁平听写条目（用于导入自定义词表）。"""

    model_config = ConfigDict(extra="allow")

    word: str = ""
    sentence: str = ""
    translation: str = ""
    meaning: str = ""
    pos: str = ""
    phonetic: str = ""
    image: str = ""
    audio: str = ""              # 外部现成录音直链，优先于 TTS
    answers: list[str] = Field(default_factory=list)  # 多空时按出现顺序


class Pack(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    schemaVersion: int = 1
    id: str
    kind: Literal["reading", "deck"] = "reading"
    origin: Literal["builtin", "custom"] = "custom"
    meta: PackMeta = Field(default_factory=PackMeta)
    attempt: Attempt | None = None          # 站外作答（idictation）
    paragraphs: list[Paragraph] = Field(default_factory=list)
    questionGroups: list[QuestionGroup] = Field(default_factory=list)
    lexicon: dict[str, LexEntry] = Field(default_factory=dict)
    items: list[DeckItem] = Field(default_factory=list)
    review: dict | None = None              # 逐题复盘（AI 生成）
    guide: dict | None = None               # 读懂这篇（AI 生成）

    @field_validator("id")
    @classmethod
    def _clean_id(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", v):
            raise ValueError("id 只能用字母数字和 . _ -")
        return v

    @model_validator(mode="after")
    def _fill_ids(self):
        for p in self.paragraphs:
            for i, s in enumerate(p.sentences, start=1):
                if not s.id:
                    s.id = f"p{p.no}s{i}"
        for gi, g in enumerate(self.questionGroups, start=1):
            if not g.id:
                g.id = f"g{gi}"
            if g.first is None and g.items:
                g.first = g.items[0].no
            if g.last is None and g.items:
                g.last = g.items[-1].no
            g.items.sort(key=lambda q: q.no)
        self.questionGroups.sort(key=lambda g: g.first or 0)

        seen: set[int] = set()
        for g in self.questionGroups:
            for q in g.items:
                if q.no in seen:
                    raise ValueError(f"题号重复：{q.no}")
                seen.add(q.no)
        return self

    @property
    def sentence_count(self) -> int:
        return sum(len(p.sentences) for p in self.paragraphs)

    @property
    def question_count(self) -> int:
        return sum(len(g.items) for g in self.questionGroups)


@dataclass
class LoadedPack:
    doc: Pack
    path: Path
    mtime: float

    @property
    def id(self) -> str:
        return self.doc.id

    def sentences(self) -> list[tuple[Paragraph, Sentence]]:
        return [(p, s) for p in self.doc.paragraphs for s in p.sentences]

    def question_index(self) -> dict[int, tuple[QuestionGroup, Question]]:
        return {q.no: (g, q) for g in self.doc.questionGroups for q in g.items}

    def public(self, with_answers: bool = False) -> dict:
        groups: list[dict] = []
        for g in self.doc.questionGroups:
            gd = g.model_dump(by_alias=True)
            if not with_answers:
                for it in gd.get("items", []):
                    it.pop("answer", None)
            groups.append(gd)
        return {
            "id": self.doc.id,
            "kind": self.doc.kind,
            "origin": self.doc.origin,
            "meta": self.doc.meta.model_dump(),
            "counts": {
                "sentences": self.doc.sentence_count,
                "questions": self.doc.question_count,
                "words": len(self.doc.lexicon),
                "items": len(self.doc.items),
            },
            "paragraphs": [p.model_dump() for p in self.doc.paragraphs],
            "questionGroups": groups,
            "lexicon": {k: v.model_dump() for k, v in self.doc.lexicon.items()},
            "items": [i.model_dump() for i in self.doc.items],
            "attempt": self.doc.attempt.model_dump() if self.doc.attempt else None,
            "hasReview": bool(self.doc.review),
            "hasGuide": bool(self.doc.guide),
            "review": self.doc.review if with_answers else None,
            "guide": self.doc.guide if with_answers else None,
        }

    def summary(self) -> dict:
        return {
            "id": self.doc.id,
            "kind": self.doc.kind,
            "origin": self.doc.origin,
            "meta": self.doc.meta.model_dump(),
            "counts": {
                "sentences": self.doc.sentence_count,
                "questions": self.doc.question_count,
                "words": len(self.doc.lexicon),
                "items": len(self.doc.items),
            },
            "attempt": self.doc.attempt.model_dump() if self.doc.attempt else None,
            "hasReview": bool(self.doc.review),
            "hasGuide": bool(self.doc.guide),
        }


_cache: dict[str, LoadedPack] = {}
_errors: dict[str, str] = {}


def _iter_files() -> list[Path]:
    return sorted(config.PACK_DIR.glob("*.json"))


def load_all(force: bool = False) -> dict[str, LoadedPack]:
    """扫描内容目录。单个文件出错只记录并跳过，不影响整站。"""
    global _cache
    files = _iter_files()
    seen_paths = {str(p) for p in files}
    for stale in [k for k in _cache if k not in seen_paths]:
        _cache.pop(stale, None)

    fresh: dict[str, LoadedPack] = {}
    errors: dict[str, str] = {}
    for path in files:
        try:
            mtime = path.stat().st_mtime
            cached = _cache.get(str(path))
            if cached and not force and cached.mtime == mtime:
                pack = cached
            else:
                raw = json.loads(path.read_text(encoding="utf-8"))
                doc = Pack.model_validate(raw)
                pack = LoadedPack(doc=doc, path=path, mtime=mtime)
                _cache[str(path)] = pack
            if pack.id in fresh:
                errors[path.name] = f"内容包 id 重复：{pack.id}（已被 {fresh[pack.id].path.name} 占用）"
                continue
            fresh[pack.id] = pack
        except Exception as exc:  # 坏文件不该拖垮服务
            errors[path.name] = f"{type(exc).__name__}: {exc}"
            log.warning("内容包加载失败 %s: %s", path.name, exc)
    _errors.clear()
    _errors.update(errors)
    return fresh


def all_packs() -> dict[str, LoadedPack]:
    return load_all()


def get(pack_id: str) -> LoadedPack | None:
    return load_all().get(pack_id)


def errors() -> dict[str, str]:
    return dict(_errors)


def save(doc: Pack) -> Path:
    """写回内容包文件（目前只有导入自定义词表用它）。"""
    path = config.PACK_DIR / f"{doc.id}.json"
    data = doc.model_dump(by_alias=True, exclude_none=True)
    data["meta"] = {k: v for k, v in data.get("meta", {}).items() if v not in ("", 0, None)}
    for key in ("paragraphs", "questionGroups", "lexicon", "items"):
        if not data.get(key):
            data.pop(key, None)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    load_all(force=True)
    return path


def next_custom_id(prefix: str = "deck") -> str:
    used = set(all_packs())
    n = 1
    while f"{prefix}-{n:03d}" in used:
        n += 1
    return f"{prefix}-{n:03d}"
