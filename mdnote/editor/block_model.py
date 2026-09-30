"""文档块模型：将整篇 Markdown 切分为独立块，供按块编辑使用。

规范文本 = 各块 raw 按 gaps（块间换行数）拼接，保证编辑可逆。
对齐 Electron 版 src/renderer/src/editor/block-model.ts。
"""

from dataclasses import dataclass, field
import re
from typing import List, Optional

BLOCK_TYPES = (
    "frontmatter",
    "code",
    "math",
    "heading",
    "blockquote",
    "list",
    "table",
    "hr",
    "toc",
    "html",
    "paragraph",
)


@dataclass
class Block:
    id: str
    type: str
    start: int  # 内容起始偏移（含）
    end: int  # 内容结束偏移（不含换行）
    raw: str
    lang: Optional[str] = None
    level: Optional[int] = None
    trailing: bool = False  # 文末挂尾空段落


@dataclass
class HeadingInfo:
    level: int
    text: str
    id: str
    block_index: int


@dataclass
class DocModel:
    text: str
    blocks: List[Block] = field(default_factory=list)
    gaps: List[int] = field(default_factory=list)


FENCE_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})\s*([^\n]*)$")
MATH_LINE_RE = re.compile(r"^\s*\$\$\s*$")
MATH_INLINE_LINE_RE = re.compile(r"^\$\$\s*.+\s*\$\$\s*$")
HR_RE = re.compile(r"^\s{0,3}(?:(?:-\s+){2,}-|(?:\*\s+){2}\*|(?:_\s+){2}_)[ \t]*$")
HR_SINGLE_RE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})[ \t]*$")
TOC_RE = re.compile(r"^\s*\[toc\]\s*$", re.IGNORECASE)
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})(?:[ \t]+(.*))?$")
QUOTE_RE = re.compile(r"^\s{0,3}>")
LIST_RE = re.compile(r"^(\s{0,3})(?:[-+*]|\d{1,9}[.)])(?:[ \t]+|$)")
TABLE_DELIM_RE = re.compile(
    r"^\s*\|?\s*:?-{1,}:?\s*(?:\|\s*:?-{1,}:?\s*)*\|?\s*$"
)
HTML_START_RE = re.compile(
    r"^\s*<(?:!--|!DOCTYPE|\?|/?[A-Za-z][\w:-]*(?:\s|/?>))", re.IGNORECASE
)


def _fnv1a(s: str) -> str:
    h = 0x811C9DC5
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return _to_base36(h)


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out


def block_hash(btype: str, raw: str, lang: Optional[str] = None) -> str:
    return _fnv1a(f"{btype}|{lang or ''}|{raw}")


def build_model(text: str) -> DocModel:
    # 切行：记录每行起始偏移；去掉行尾 \r
    line_starts: List[int] = []
    line_texts: List[str] = []
    pos = 0
    while pos <= len(text):
        line_starts.append(pos)
        nl = text.find("\n", pos)
        if nl == -1:
            nl = len(text)
        line = text[pos:nl]
        if line.endswith("\r"):
            line = line[:-1]
        line_texts.append(line)
        if nl == len(text):
            break
        pos = nl + 1
    n = len(line_texts)

    # (a, b, type, lang, level)
    ranges: list[tuple[int, int, str, Optional[str], Optional[int]]] = []
    cursor = 0

    # 1. YAML front matter
    if line_texts and line_texts[0] == "---":
        close = -1
        for j in range(1, n):
            if line_texts[j] in ("---", "..."):
                close = j
                break
            if line_texts[j] == "":
                break
        if close > 0:
            ranges.append((0, close + 1, "frontmatter", None, None))
            cursor = close + 1

    def is_blank(i: int) -> bool:
        return line_texts[i] == "" or bool(re.match(r"^\s+$", line_texts[i]))

    def next_non_blank(i: int) -> int:
        k = i
        while k < n and is_blank(k):
            k += 1
        return k

    while cursor < n:
        if is_blank(cursor):
            cursor += 1
            continue
        line = line_texts[cursor]

        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group(2)[0]
            length = len(fence.group(2))
            close = cursor + 1
            while close < n:
                m = re.match(r"^(\s{0,3})(`{3,}|~{3,})\s*$", line_texts[close])
                if m and m.group(2)[0] == marker and len(m.group(2)) >= length:
                    close += 1
                    break
                close += 1
            lang = (fence.group(3) or "").strip()
            lang = re.split(r"\s+", lang)[0] if lang else ""
            ranges.append((cursor, close, "code", lang or None, None))
            cursor = close
            continue

        if MATH_INLINE_LINE_RE.match(line):
            ranges.append((cursor, cursor + 1, "math", None, None))
            cursor += 1
            continue
        if MATH_LINE_RE.match(line):
            close = cursor + 1
            while close < n and not re.match(r"^\s*\$\$\s*$", line_texts[close]):
                close += 1
            close = min(close + 1, n)
            ranges.append((cursor, close, "math", None, None))
            cursor = close
            continue

        if HR_RE.match(line) or HR_SINGLE_RE.match(line):
            ranges.append((cursor, cursor + 1, "hr", None, None))
            cursor += 1
            continue

        if TOC_RE.match(line):
            ranges.append((cursor, cursor + 1, "toc", None, None))
            cursor += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            ranges.append((cursor, cursor + 1, "heading", None, len(heading.group(1))))
            cursor += 1
            continue

        if QUOTE_RE.match(line):
            j = cursor + 1
            while j < n:
                if QUOTE_RE.match(line_texts[j]):
                    j += 1
                elif is_blank(j):
                    k = next_non_blank(j)
                    if k < n and QUOTE_RE.match(line_texts[k]):
                        j += 1
                    else:
                        break
                else:
                    break
            ranges.append((cursor, j, "blockquote", None, None))
            cursor = j
            continue

        if LIST_RE.match(line):
            j = cursor + 1
            while j < n:
                if LIST_RE.match(line_texts[j]):
                    j += 1
                    continue
                if re.match(r"^\s+\S", line_texts[j]):
                    j += 1
                    continue
                if is_blank(j):
                    k = next_non_blank(j)
                    if k < n and (
                        LIST_RE.match(line_texts[k])
                        or re.match(r"^\s+\S", line_texts[k])
                    ):
                        j += 1
                        continue
                    break
                break
            ranges.append((cursor, j, "list", None, None))
            cursor = j
            continue

        if "|" in line and cursor + 1 < n and TABLE_DELIM_RE.match(line_texts[cursor + 1]):
            j = cursor + 2
            while j < n and not is_blank(j) and "|" in line_texts[j]:
                j += 1
            ranges.append((cursor, j, "table", None, None))
            cursor = j
            continue

        if HTML_START_RE.match(line):
            j = cursor + 1
            while j < n and not is_blank(j):
                j += 1
            ranges.append((cursor, j, "html", None, None))
            cursor = j
            continue

        # 段落
        j = cursor + 1
        while j < n and not is_blank(j):
            l = line_texts[j]
            if (
                FENCE_RE.match(l)
                or MATH_LINE_RE.match(l)
                or MATH_INLINE_LINE_RE.match(l)
                or HR_RE.match(l)
                or HR_SINGLE_RE.match(l)
                or TOC_RE.match(l)
                or HEADING_RE.match(l)
                or QUOTE_RE.match(l)
                or LIST_RE.match(l)
                or HTML_START_RE.match(l)
            ):
                break
            if "|" in l and j + 1 < n and TABLE_DELIM_RE.match(line_texts[j + 1]):
                break
            j += 1
        ranges.append((cursor, j, "paragraph", None, None))
        cursor = j

    blocks: List[Block] = []
    if not ranges:
        return DocModel(
            text=text,
            blocks=[
                Block(id=block_hash("paragraph", ""), type="paragraph", start=len(text), end=len(text), raw="", trailing=True)
            ],
            gaps=[0],
        )

    for a, b, btype, lang, level in ranges:
        start = line_starts[a]
        last_line = line_texts[b - 1]
        end = line_starts[b - 1] + len(last_line)
        raw = text[start:end]
        blocks.append(
            Block(
                id=block_hash(btype, raw, lang),
                type=btype,
                start=start,
                end=end,
                raw=raw,
                lang=lang,
                level=level,
            )
        )

    # 文末挂尾空段落
    blocks.append(
        Block(
            id=block_hash("paragraph", ""),
            type="paragraph",
            start=len(text),
            end=len(text),
            raw="",
            trailing=True,
        )
    )

    gaps: List[int] = []
    for i, blk in enumerate(blocks):
        frm = blk.end
        to = blocks[i + 1].start if i + 1 < len(blocks) else len(text)
        gaps.append(text[frm:to].count("\n"))

    return DocModel(text=text, blocks=blocks, gaps=gaps)


def serialize(model: DocModel) -> str:
    out = ""
    for i, blk in enumerate(model.blocks):
        out += blk.raw
        out += "\n" * (model.gaps[i] if i < len(model.gaps) else 0)
    return out


def find_block_index(model: DocModel, offset: int) -> int:
    lo, hi = 0, len(model.blocks) - 1
    while lo < hi:
        mid = (lo + hi + 1) >> 1
        if model.blocks[mid].start <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lo


def extract_headings(model: DocModel) -> List[HeadingInfo]:
    result: List[HeadingInfo] = []
    used: set[str] = set()
    for idx, b in enumerate(model.blocks):
        if b.type != "heading" or not b.level:
            continue
        text = re.sub(r"^\s*#{1,6}\s+", "", b.raw)
        text = re.sub(r"\s+#+\s*$", "", text)
        text = re.sub(r"[*_`~]", "", text).strip()
        hid = slugify(text)
        n = 1
        while hid in used:
            n += 1
            hid = f"{slugify(text)}-{n}"
        used.add(hid)
        result.append(HeadingInfo(level=b.level, text=text, id=hid, block_index=idx))
    return result


def slugify(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r"[&<>\"'`/\\|!?.,:;()\[\]{}]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    s = re.sub(r"^-|-$", "", s)
    return s or "section"
