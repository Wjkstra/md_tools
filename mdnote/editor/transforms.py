"""编辑期结构变换：回车拆分、退格合并、列表缩进、空格触发。纯函数。

对齐 Electron 版 src/renderer/src/editor/transforms.ts。
"""

from dataclasses import dataclass
import re
from typing import List


@dataclass
class TransformResult:
    text: str
    caret: int


def _locate(raw: str, offset: int):
    lines = raw.split("\n")
    line_index = 0
    acc = 0
    for i, ln in enumerate(lines):
        end = acc + len(ln)
        if offset <= end:
            line_index = i
            break
        acc = end + 1
        line_index = i
    line_start = sum(len(l) + 1 for l in lines[:line_index])
    col = max(0, offset - line_start)
    return lines, line_index, col


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


def split_at(raw: str, btype: str, offset: int) -> TransformResult:
    lines, line_index, col = _locate(raw, offset)
    line = lines[line_index]
    line_start = offset - col  # 当前行在 raw 中的全局起始偏移

    def finish(new_line: str, inserted: str | None, caret_col: int) -> TransformResult:
        lines[line_index] = new_line
        if inserted is not None:
            lines.insert(line_index + 1, inserted)
            caret = line_start + len(new_line) + 1 + caret_col
        else:
            caret = line_start + caret_col
        return TransformResult(text="\n".join(lines), caret=caret)

    if btype == "list":
        m = re.match(r"^(\s*)([-+*]|\d{1,9}[.)])(\s+|$)(.*)$", line)
        if m:
            indent, marker0, sep, content = m.groups()
            prefix_len = len(indent) + len(marker0) + len(sep)
            # 空项：回车取消格式
            if content == "":
                return finish("", None, 0)
            cc = _clamp(col - prefix_len, 0, len(content))
            first, second = content[:cc], content[cc:]
            # 续行标记（有序列表自动递增）
            next_marker = marker0
            num = re.match(r"^\d+", marker0)
            if num:
                tail = "." if "." in marker0 else ")"
                next_marker = f"{int(num.group(0)) + 1}{tail}"
            sp = sep or " "
            new_prefix = f"{indent}{next_marker}{sp}"
            return finish(
                f"{indent}{marker0}{sp}{first}",
                f"{new_prefix}{second}",
                len(new_prefix),
            )

    if btype == "blockquote":
        m = re.match(r"^(\s*)>([ \t]?)(.*)$", line)
        if m:
            indent, sp, content = m.groups()
            # 空引用：回车取消格式
            if content == "":
                return finish("", None, 0)
            prefix_len = len(indent) + 1 + len(sp)
            cc = _clamp(col - prefix_len, 0, len(content))
            first, second = content[:cc], content[cc:]
            use_sp = sp or " "
            new_prefix = f"{indent}> "
            return finish(
                f"{indent}>{use_sp}{first}",
                f"{new_prefix}{second}",
                len(new_prefix),
            )

    if btype == "heading":
        m = re.match(r"^(\s{0,3})(#{1,6})([ \t]+|$)(.*)$", line)
        if m:
            indent, hashes, sep, content = m.groups()
            prefix_len = len(indent) + len(hashes) + len(sep)
            cc = _clamp(col - prefix_len, 0, len(content))
            # 标题末尾（无后半段）：新建空普通段落
            if content == "" or cc >= len(content):
                return finish(line, "", 0)
            use_sep = sep or " "
            # 后半段去掉标题标记，成为普通段落（下一行）
            return finish(
                f"{indent}{hashes}{use_sep}{content[:cc]}",
                content[cc:],
                0,
            )

    before = raw[:offset]
    after = raw[offset:]
    return TransformResult(text=f"{before}\n{after}", caret=offset + 1)


def merge_with(prev_raw: str, raw: str) -> TransformResult:
    return TransformResult(text=f"{prev_raw}\n{raw}", caret=len(prev_raw) + 1)


def indent_line(raw: str, offset: int, tab_size: int, outdent: bool) -> TransformResult:
    lines, line_index, _ = _locate(raw, offset)
    line = lines[line_index]
    if outdent:
        lines[line_index] = re.sub(r"^ {1,4}|\t", "", line)
    else:
        lines[line_index] = " " * tab_size + line
    text = "\n".join(lines)
    line_start = sum(len(l) + 1 for l in lines[:line_index])
    return TransformResult(text=text, caret=line_start + len(lines[line_index]))


def _trigger_code_fence(line: str):
    m = re.match(r"^(\s{0,3})```\s*([\w+-]*)$", line)
    if not m:
        return None
    return TransformResult(text=f"{line}\n\n{m.group(1)}```", caret=len(line) + 1)


_TRIGGERS = [
    (re.compile(r"^\s{0,3}#{1,6} $"), lambda l: TransformResult(l, len(l))),
    (re.compile(r"^\s{0,3}>\s$"), lambda l: TransformResult(l, len(l))),
    (re.compile(r"^\s{0,3}[-+*] $"), lambda l: TransformResult(l, len(l))),
    (re.compile(r"^\s{0,3}\d{1,9}[.)] $"), lambda l: TransformResult(l, len(l))),
    (re.compile(r"^\s{0,3}[-+*]\s\[[ xX]\] $"), lambda l: TransformResult(l, len(l))),
    (re.compile(r"^(\s{0,3})```\s*([\w+-]*)$"), _trigger_code_fence),
    (re.compile(r"^\s{0,3}~~\s*$"), lambda l: TransformResult("$$\n\n$$", 3)),
]


def detect_space_trigger(raw: str, offset: int) -> TransformResult | None:
    lines, line_index, _ = _locate(raw, offset)
    line = lines[line_index]
    for rx, build in _TRIGGERS:
        if rx.match(line):
            r = build(line)
            if not r:
                continue
            lines[line_index] = r.text
            prefix_text = "\n".join(lines[:line_index])
            prefix_len = 0 if line_index == 0 else len(prefix_text) + 1
            return TransformResult(text="\n".join(lines), caret=prefix_len + r.caret)
    return None


def wrap_selection(
    raw: str, sel_start: int, sel_end: int, marker: str, placeholder: str = ""
):
    selected = raw[sel_start:sel_end]
    if selected:
        text = f"{raw[:sel_start]}{marker}{selected}{marker}{raw[sel_end:]}"
        return (
            TransformResult(text=text, caret=sel_end + len(marker) * 2),
            sel_start + len(marker),
            sel_end + len(marker),
        )
    inner = placeholder
    text = f"{raw[:sel_start]}{marker}{inner}{marker}{raw[sel_end:]}"
    return (
        TransformResult(
            text=text, caret=sel_start + len(marker) + len(inner)
        ),
        sel_start + len(marker),
        sel_start + len(marker) + len(inner),
    )


def insert_at(raw: str, offset: int, insertion: str) -> TransformResult:
    return TransformResult(
        text=f"{raw[:offset]}{insertion}{raw[offset:]}",
        caret=offset + len(insertion),
    )
