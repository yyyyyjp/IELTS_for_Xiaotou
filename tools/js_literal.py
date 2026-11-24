"""从单文件页面里取 `const NAME = {...}`，并容错解析 JS 对象字面量。

精读页里的 DATA / REV 是标准 JSON，但 MEANS、SUMWORK 这类手写对象常带
单引号、无引号键、尾逗号、注释。标准库 json 解不了，这里写一个小解析器，
只覆盖「纯数据」子集：对象、数组、字符串、数字、true/false/null。

不支持函数、正则、模板插值——遇到就报错，而不是猜。
"""
from __future__ import annotations

import re
from typing import Any

MARK = re.compile(r"const\s+([A-Za-z_$][\w$]*)\s*=")


class JsLiteralError(ValueError):
    pass


def grab(src: str, name: str) -> Any:
    """找到 `const name = <literal>;` 并解析成 Python 对象。"""
    literal = grab_text(src, name)
    return loads(literal)


def grab_text(src: str, name: str) -> str:
    for m in MARK.finditer(src):
        if m.group(1) != name:
            continue
        start = m.end()
        while start < len(src) and src[start].isspace():
            start += 1
        end = _scan_end(src, start)
        return src[start:end]
    raise JsLiteralError(f"没有找到 const {name} = ...")


def _scan_end(src: str, start: int) -> int:
    """从字面量起点扫到配平的结尾；跳过字符串与注释。"""
    depth = 0
    i = start
    n = len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            i = _skip_string(src, i)
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            i = src.find("\n", i)
            if i < 0:
                break
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            end = src.find("*/", i + 2)
            if end < 0:
                break
            i = end + 2
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
        elif depth == 0 and c in ";,":
            return i
        i += 1
    raise JsLiteralError("字面量没有闭合")


def _skip_string(src: str, i: int) -> int:
    quote = src[i]
    i += 1
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == quote:
            return i + 1
        i += 1
    raise JsLiteralError("字符串没有闭合")


class _Parser:
    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.n = len(text)

    def parse(self) -> Any:
        value = self.value()
        self.ws()
        if self.i != self.n:
            raise JsLiteralError(f"多余内容：{self.s[self.i:self.i + 30]!r}")
        return value

    def ws(self) -> None:
        while self.i < self.n:
            c = self.s[self.i]
            if c.isspace():
                self.i += 1
            elif self.s.startswith("//", self.i):
                nl = self.s.find("\n", self.i)
                self.i = self.n if nl < 0 else nl + 1
            elif self.s.startswith("/*", self.i):
                end = self.s.find("*/", self.i + 2)
                if end < 0:
                    raise JsLiteralError("注释没有闭合")
                self.i = end + 2
            else:
                return

    def peek(self) -> str:
        return self.s[self.i] if self.i < self.n else ""

    def expect(self, ch: str) -> None:
        self.ws()
        if self.peek() != ch:
            raise JsLiteralError(f"期望 {ch!r}，实际 {self.peek()!r}（位置 {self.i}）")
        self.i += 1

    def value(self) -> Any:
        self.ws()
        c = self.peek()
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c in "\"'`":
            return self.string()
        if c == "-" or c.isdigit():
            return self.number()
        if c.isalpha() or c in "_$":
            word = self.ident()
            if word == "true":
                return True
            if word == "false":
                return False
            if word in ("null", "undefined"):
                return None
            raise JsLiteralError(f"不支持的值：{word!r}")
        raise JsLiteralError(f"不认识的值：{c!r}（位置 {self.i}）")

    def obj(self) -> dict:
        self.expect("{")
        out: dict[str, Any] = {}
        self.ws()
        if self.peek() == "}":
            self.i += 1
            return out
        while True:
            self.ws()
            if self.peek() in "\"'`":
                key = self.string()
            elif self.peek().isdigit():
                key = str(self.number())
            else:
                key = self.ident()
            self.expect(":")
            out[key] = self.value()
            self.ws()
            c = self.peek()
            if c == ",":
                self.i += 1
                self.ws()
                if self.peek() == "}":
                    self.i += 1
                    return out
                continue
            if c == "}":
                self.i += 1
                return out
            raise JsLiteralError(f"对象里期望 , 或 }}，实际 {c!r}（位置 {self.i}）")

    def arr(self) -> list:
        self.expect("[")
        out: list[Any] = []
        self.ws()
        if self.peek() == "]":
            self.i += 1
            return out
        while True:
            out.append(self.value())
            self.ws()
            c = self.peek()
            if c == ",":
                self.i += 1
                self.ws()
                if self.peek() == "]":
                    self.i += 1
                    return out
                continue
            if c == "]":
                self.i += 1
                return out
            raise JsLiteralError(f"数组里期望 , 或 ]，实际 {c!r}（位置 {self.i}）")

    def string(self) -> str:
        quote = self.peek()
        self.i += 1
        buf: list[str] = []
        while self.i < self.n:
            c = self.s[self.i]
            if c == "\\":
                self.i += 1
                if self.i >= self.n:
                    break
                e = self.s[self.i]
                mapping = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v"}
                if e in mapping:
                    buf.append(mapping[e])
                    self.i += 1
                elif e == "u":
                    hexs = self.s[self.i + 1:self.i + 5]
                    if len(hexs) < 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", hexs):
                        raise JsLiteralError(f"坏的 \\u 转义：{hexs!r}")
                    buf.append(chr(int(hexs, 16)))
                    self.i += 5
                elif e == "\n":
                    self.i += 1
                else:
                    buf.append(e)
                    self.i += 1
                continue
            if c == quote:
                self.i += 1
                return "".join(buf)
            if c == "\n" and quote != "`":
                raise JsLiteralError("单行字符串里出现换行")
            buf.append(c)
            self.i += 1
        raise JsLiteralError("字符串没有闭合")

    def ident(self) -> str:
        self.ws()
        start = self.i
        while self.i < self.n and (self.s[self.i].isalnum() or self.s[self.i] in "_$"):
            self.i += 1
        if start == self.i:
            raise JsLiteralError(f"期望标识符，实际 {self.peek()!r}（位置 {self.i}）")
        return self.s[start:self.i]

    def number(self) -> int | float:
        m = re.match(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", self.s[self.i:])
        if not m:
            raise JsLiteralError(f"坏数字（位置 {self.i}）")
        text = m.group(0)
        self.i += len(text)
        return float(text) if any(ch in text for ch in ".eE") else int(text)


def loads(text: str) -> Any:
    return _Parser(text).parse()
