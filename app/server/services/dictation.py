"""单词 / 句子听写题目的生成。

题目是「算出来的」而不是存起来的：同一篇原文，可以生成单词听写、听词填句、
整句听写三种题；以后加新题型只改这里，不用动数据库。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote

import config
import tts_service

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*")

STOP = set(
    """a an the of to in on at for and or but is are was were be been being it its this that these those
    with by as from i you he she we they my your his her our their me him them us do does did have has had
    will would can could should may might must not no so if than then there here what which who when where
    how very too also just about into over after before more most some any all one two three
    can't don't doesn't didn't isn't aren't wasn't weren't won't wouldn't couldn't shouldn't
    it's he's she's that's there's i'm i've you're we're they're hasn't haven't""".split()
)

MODES = ("word", "word_in_context", "sentence")
MAX_BLANKS = 2


@dataclass
class Span:
    start: int
    end: int
    word: str


@dataclass
class Item:
    id: str
    pack_id: str
    type: str
    audio_text: str
    masked_text: str = ""
    answers: list[str] = field(default_factory=list)
    hint: dict = field(default_factory=dict)
    source: str = ""
    external_audio: str = ""

    def _audio(self, voice: str) -> tuple[str, bool]:
        if self.external_audio:
            return self.external_audio, True
        name = tts_service.cache_name(self.audio_text, voice)
        if (config.AUDIO_DIR / name).exists():
            return f"/api/audio/{name}", True
        q = f"text={quote(self.audio_text)}&voice={quote(voice)}"
        return f"/api/tts/audio?{q}", False

    def public(self, voice: str = config.DEFAULT_VOICE) -> dict:
        url, cached = self._audio(voice)
        # 占位符里原本含着答案，下发前抹掉，只留词长给前端定输入框宽度
        masked = re.sub(r"\{\{[^}]*\}\}", "{{}}", self.masked_text)
        hint = dict(self.hint)
        if hint.get("context"):
            hint["context"] = re.sub(r"\{\{[^}]*\}\}", "{{}}", hint["context"])
        return {
            "id": self.id,
            "packId": self.pack_id,
            "type": self.type,
            "audioText": self.audio_text,
            "audioUrl": url,
            "audioCached": cached,
            "text": masked,
            "blankCount": len(self.answers),
            "blankLengths": [len(a) for a in self.answers],
            "hint": hint,
            "source": self.source,
        }

    def stored(self) -> dict:
        return {
            "id": self.id,
            "packId": self.pack_id,
            "type": self.type,
            "audioText": self.audio_text,
            "masked_text": self.masked_text,
            "answers": self.answers,
            "hint": self.hint,
            "source": self.source,
            "external_audio": self.external_audio,
        }

    @staticmethod
    def from_stored(d: dict) -> "Item":
        return Item(
            id=d["id"],
            pack_id=d.get("packId", ""),
            type=d.get("type", "word"),
            audio_text=d.get("audioText", ""),
            masked_text=d.get("masked_text", ""),
            answers=list(d.get("answers") or []),
            hint=d.get("hint") or {},
            source=d.get("source", ""),
            external_audio=d.get("external_audio", ""),
        )


def word_spans(sentence: str) -> list[Span]:
    return [Span(m.start(), m.end(), m.group()) for m in WORD_RE.finditer(sentence or "")]


def _is_lemma_match(word: str, lemma: str) -> bool:
    w, l = word.lower(), lemma.lower()
    if w == l:
        return True
    if not w.startswith(l):
        return False
    suffix = w[len(l):]
    return suffix in ("s", "es", "ed", "d", "ing", "ies")


def pick_blanks(sentence: str, focus: set[str] | None = None, limit: int = 1) -> list[Span]:
    """挑要挖空的词：优先生词本里的词，其次最长的实词。"""
    spans = word_spans(sentence)
    if not spans:
        return []
    focus = focus or set()
    picked: list[Span] = []
    seen: set[str] = set()

    if focus:
        for s in spans:
            if any(_is_lemma_match(s.word, f) for f in focus) and s.word.lower() not in seen:
                picked.append(s)
                seen.add(s.word.lower())
                if len(picked) >= limit:
                    break
    if not picked:
        def ok(s: Span) -> bool:
            return (len(s.word) >= 4
                    and s.word.lower() not in STOP
                    and s.word.lower() not in seen
                    and not any(ch.isdigit() for ch in s.word))

        # 句中人名/地名/术语通常首字母大写，听写时不公平，先排除；
        # 全句都是大写时再退回来
        cands = [s for s in spans if ok(s) and not s.word[0].isupper()]
        if not cands:
            cands = [s for s in spans if ok(s)]
        cands.sort(key=lambda s: (len(s.word), s.start))
        if cands:
            picked = [cands[-1]]
    return picked[:MAX_BLANKS]


def mask(sentence: str, spans: list[Span]) -> str:
    out = sentence
    for s in sorted(spans, key=lambda x: x.start, reverse=True):
        out = out[: s.start] + "{{" + s.word + "}}" + out[s.end:]
    return out


def _audio_text_for_sentence(sentence: str) -> str:
    return re.sub(r"\s+", " ", sentence).strip()


def sentence_item(pack_id: str, sentence_id: str, sentence: str, zh: str,
                  focus: set[str]) -> Item | None:
    limit = 2 if len(word_spans(sentence)) >= 14 else 1
    spans = pick_blanks(sentence, focus, limit=limit)
    if not spans:
        return None
    return Item(
        id=f"{pack_id}:s:{sentence_id}",
        pack_id=pack_id,
        type="sentence",
        audio_text=_audio_text_for_sentence(sentence),
        masked_text=mask(sentence, spans),
        answers=[s.word for s in spans],
        hint={"zh": zh},
        source="pack",
    )


def vocab_word_item(pack_id: str, row, mode: str,
                    sentence: str = "", zh: str = "") -> Item:
    """row 是 vocab 表的一行；mode=word 只听词，word_in_context 听词填句。"""
    word = (row["word"] or row["lemma"]).strip()
    lemma = (row["lemma"] or word).strip()
    spans = pick_blanks(sentence, {lemma}, limit=1) if sentence else []
    masked = mask(sentence, spans) if spans else ""
    if mode == "word_in_context" and spans:
        word = spans[0].word
    return Item(
        id=f"{pack_id}:w:{lemma}",
        pack_id=pack_id,
        type=mode,
        audio_text=word,
        masked_text=masked if mode == "word_in_context" else "",
        answers=[word],
        hint={
            "gloss": row["gloss"],
            "pos": row["pos"],
            "phonetic": row["phonetic"],
            # 提示里也不给完整例句，否则等于把答案印在题面上
            "context": masked,
            "contextZh": zh,
        },
        source="vocab",
    )


def lexicon_word_item(pack_id: str, word: str, entry: dict, mode: str,
                      sentence: str = "", zh: str = "") -> Item:
    spans = pick_blanks(sentence, {word}, limit=1) if sentence else []
    masked = mask(sentence, spans) if spans else ""
    answer = spans[0].word if spans else word
    return Item(
        id=f"{pack_id}:w:{word.lower()}",
        pack_id=pack_id,
        type=mode,
        audio_text=answer,
        masked_text=masked if mode == "word_in_context" else "",
        answers=[answer],
        hint={
            "gloss": entry.get("gloss", ""),
            "pos": entry.get("pos", ""),
            "phonetic": entry.get("phonetic", ""),
            "context": masked,
            "contextZh": zh,
        },
        source="pack",
    )


def deck_item(pack, index: int, row, mode: str) -> Item | None:
    """自定义词表：一行一个词 + 例句。"""
    answers = list(row.get("answers") or [])
    word = answers[0] if answers else (row.get("word") or "").strip()
    sentence = row.get("sentence") or ""
    if not word:
        return None

    if mode == "sentence" and sentence:
        spans = pick_blanks(sentence, {word}, limit=max(1, len(answers) or 1))
        if spans:
            return Item(
                id=f"{pack.id}:d:{index}",
                pack_id=pack.id,
                type="sentence",
                audio_text=_audio_text_for_sentence(sentence),
                masked_text=mask(sentence, spans),
                answers=[s.word for s in spans],
                hint={"zh": row.get("translation", ""), "gloss": row.get("meaning", "")},
                source="deck",
                external_audio=row.get("audio") or "",
            )
        mode = "word"

    ctx_spans = pick_blanks(sentence, {word}, limit=1) if sentence else []
    ctx_masked = mask(sentence, ctx_spans) if ctx_spans else ""
    return Item(
        id=f"{pack.id}:d:{index}",
        pack_id=pack.id,
        type=mode,
        audio_text=word,
        answers=[word],
        hint={
            "gloss": row.get("meaning", ""),
            "pos": row.get("pos", ""),
            "phonetic": row.get("phonetic", ""),
            "context": ctx_masked,
            "contextZh": row.get("translation", ""),
            "image": row.get("image", ""),
        },
        source="deck",
        # 外部录音通常念的是整句，只听单词时不要拿它冒充
        external_audio="",
    )


def resolve_context(row, pack_id: str) -> tuple[str, str]:
    """取生词在某个篇目里的例句；没有该篇目就取第一条。"""
    try:
        contexts = json.loads(row["contexts"] or "[]")
    except (ValueError, TypeError):
        contexts = []
    if not contexts:
        return "", ""
    for ctx in contexts:
        if not pack_id or ctx.get("packId") == pack_id:
            return ctx.get("en", ""), ctx.get("zh", "")
    return contexts[0].get("en", ""), contexts[0].get("zh", "")
