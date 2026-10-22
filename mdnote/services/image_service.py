"""Import images and stage image references transactionally for document saves."""

import base64
import binascii
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from shutil import copyfileobj
from urllib.parse import quote, unquote

from .html_service import local_image_path


def _unique_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    n = 1
    while True:
        candidate = target.with_name(f"{stem}-{n}{suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _normalize_ext(ext: str) -> str:
    ext = ext.lower().lstrip(".")
    if ext in ("jpeg", "jpg"):
        return ".jpg"
    return {"svg+xml": ".svg"}.get(ext, "." + ext)


def _reference(target: Path, base: Path, path_type: str = "relative") -> str:
    if path_type == "absolute":
        return target.as_uri()
    # Balanced parentheses are legal (and common) in Markdown destinations;
    # quoting them would turn "a(b).png" into "a%28b%29.png".
    return quote(Path(os.path.relpath(target, base)).as_posix(), safe="/:()")


def _write_unique(target: Path, payload: bytes | None = None, source: Path | None = None) -> Path:
    """Exclusive creation avoids overwriting assets, including concurrent imports."""
    while True:
        chosen = _unique_path(target)
        try:
            output = chosen.open("xb")
        except FileExistsError:
            continue
        try:
            with output:
                if source is not None:
                    with source.open("rb") as stream:
                        copyfileobj(stream, output)
                else:
                    output.write(payload or b"")
        except Exception:
            chosen.unlink(missing_ok=True)
            raise
        return chosen


def import_image(*, src_path: str | None = None, data_url: str | None = None,
                 file_name: str | None = None, doc_path: str | None = None,
                 folder: str = "assets", path_type: str = "relative") -> str:
    """Import and return a Markdown image. Shared folders such as ../images work."""
    doc_dir = Path(doc_path).resolve().parent if doc_path else Path.cwd().resolve()
    target_dir = (doc_dir / folder).resolve()
    source = None
    if src_path:
        source = Path(src_path)
        stem, ext = source.stem, _normalize_ext(source.suffix or ".png")
        payload = None
    elif data_url:
        match = re.fullmatch(r"data:image/([\w+.-]+);base64,(.*)", data_url, re.DOTALL)
        if data_url.startswith("data:") and not match:
            raise ValueError("图片数据 URL 无效")
        ext = _normalize_ext(match.group(1) if match else "png")
        try:
            payload = base64.b64decode(match.group(2) if match else data_url, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("图片 base64 数据无效") from exc
        # Browser-supplied filenames must not escape the selected image folder.
        stem = Path((file_name or "").replace("\\", "/")).stem or f"image-{time.strftime('%Y%m%d%H%M%S')}"
    else:
        raise ValueError("import_image 需要 src_path 或 data_url")
    # Expressing the reference must succeed before creating anything; on Windows
    # relpath fails across drives, and a failure here must leave no folders behind.
    if path_type != "absolute":
        os.path.relpath(target_dir, doc_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = _write_unique(target_dir / f"{stem}{ext}", payload, source)
    try:
        reference = _reference(target, doc_dir, path_type)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return f"![](<{reference}>)"


@dataclass
class PreparedImageSave:
    text: str
    created_paths: list[Path] = field(default_factory=list)

    def commit(self) -> None:
        """Document write succeeded; newly copied images now belong to it."""
        self.created_paths.clear()

    def rollback(self) -> None:
        """Remove only files created by this preparation, preserving all old assets."""
        for path in self.created_paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        self.created_paths.clear()


_IMAGE_REF_RE = re.compile(r"!\[([^\]\n]*)\](?:\[([^\]\n]*)\])?")
_REF_DEFINITION_RE = re.compile(r"^(\s{0,3}\[([^\]\n]+)\]:\s*)(<[^>\n]*>|\S+)", re.MULTILINE)
_HTML_IMAGE_RE = re.compile(r'(<img\b[^>]*?\bsrc=)(["\'])(.*?)\2', re.IGNORECASE)

_FENCE_LINE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_INDENTED_LINE_RE = re.compile(r"^(?: {4}|\t)")
_LIST_MARKER_LINE_RE = re.compile(r"^\s{0,3}(?:[-+*]|\d{1,9}[.)])(?:\s|$)")
_INLINE_CODE_RE = re.compile(r"(`+)([\s\S]*?)\1")


def _merge_regions(regions):
    merged = []
    for start, end in sorted(regions):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _line_is_blank(line: str) -> bool:
    return line.strip(" \t\r\n") == ""


def _line_indent(line: str) -> int:
    stripped = line.lstrip(" ")
    return len(line) - len(stripped)


def _code_indent_threshold(lines, i) -> int:
    """Indentation a code line needs at this position.

    Four spaces at document level; inside a list item an indented code block
    needs a blank line and eight (or deeper) spaces, otherwise the line is
    just lazy list continuation prose.
    """
    j = i - 1
    while j >= 0 and _line_is_blank(lines[j]):
        j -= 1
    marker = lines[j] if j >= 0 else ""
    match = _LIST_MARKER_LINE_RE.match(marker)
    if match:
        return (max(0, _line_indent(marker)) // 4) * 4 + 8
    return 4


def _code_regions(text: str) -> list[tuple[int, int]]:
    """Character spans of fenced, indented and inline code.

    Indented code starts after a blank line (document start counts) at the
    indentation required for the current list context, and keeps interior
    blank lines only when another indented line follows. Over-detection only
    skips path rewriting, so erring towards protection is safe.
    """
    regions: list[tuple[int, int]] = []
    fence_start = None
    fence_character = ""
    fence_length = 0
    indented_start = None
    indent_threshold = 4
    offset = 0
    prev_blank = True
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        marker = _FENCE_LINE_RE.match(body)
        if marker:
            token, rest = marker.group(1), marker.group(2)
            if fence_start is None:
                fence_start = offset
                fence_character, fence_length = token[0], len(token)
            elif token[0] == fence_character and len(token) >= fence_length and not rest.strip():
                regions.append((fence_start, offset + len(line)))
                fence_start = None
        elif fence_start is None:
            indented = bool(_INDENTED_LINE_RE.match(line)) and not _line_is_blank(line)
            if indented and indented_start is not None:
                if _line_indent(line) < indent_threshold:
                    regions.append((indented_start, offset))
                    indented_start = None
            elif indented and prev_blank:
                indent_threshold = _code_indent_threshold(lines, i)
                if _line_indent(line) >= indent_threshold:
                    indented_start = offset
            elif indented_start is not None:
                if _line_is_blank(line):
                    k = i + 1
                    while k < len(lines) and _line_is_blank(lines[k]):
                        k += 1
                    follows = (k < len(lines)
                               and bool(_INDENTED_LINE_RE.match(lines[k]))
                               and _line_indent(lines[k]) >= indent_threshold
                               and not _line_is_blank(lines[k]))
                    if not follows:
                        regions.append((indented_start, offset))
                        indented_start = None
                else:
                    regions.append((indented_start, offset))
                    indented_start = None
        offset += len(line)
        prev_blank = _line_is_blank(line)
    if fence_start is not None:
        regions.append((fence_start, len(text)))
    if indented_start is not None:
        regions.append((indented_start, len(text)))
    for match in _INLINE_CODE_RE.finditer(text):
        regions.append((match.start(), match.end()))
    return _merge_regions(regions)


def _prose_segments(text: str) -> list[tuple[bool, str]]:
    """Protect fenced/indented/inline code examples from image-path rewriting."""
    protected = _code_regions(text)
    segments = []
    offset = 0
    for start, end in protected:
        if start > offset:
            segments.append((True, text[offset:start]))
        segments.append((False, text[start:end]))
        offset = end
    if offset < len(text):
        segments.append((True, text[offset:]))
    return segments


def _unescaped_at(text: str, pos: int) -> bool:
    """True when the character at pos is not escaped by a backslash run."""
    slashes = 0
    p = pos - 1
    while p >= 0 and text[p] == "\\":
        slashes += 1
        p -= 1
    return slashes % 2 == 0


def _scan_bracket(text: str, open_pos: int, open_ch: str, close_ch: str):
    """Return the index just after the matching close bracket, or None."""
    depth = 0
    p = open_pos
    while p < len(text):
        ch = text[p]
        if ch == "\\":
            p += 2
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return p + 1
        p += 1
    return None


def _bare_destination(text: str, p: int):
    """Parse an image/link destination starting at p (right after '(').

    Angle brackets, backslash escapes and balanced parentheses are honoured,
    so a path such as ``a(b).png`` is read in full instead of stopping at the
    first ``)``. Returns ``(start, end_exclusive)`` or None.
    """
    if p >= len(text):
        return None
    if text[p] == "<":
        q = p + 1
        while q < len(text):
            ch = text[q]
            if ch == "\\":
                q += 2
                continue
            if ch in "\n\r":
                return None
            if ch == ">":
                return p, q + 1
            q += 1
        return None
    depth = 0
    q = p
    while q < len(text):
        ch = text[q]
        if ch == "\\":
            q += 2
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            if depth == 0:
                break
            depth -= 1
        elif ch in " \t\n\r":
            break
        elif ch in "<>":
            return None
        q += 1
    return (p, q) if q > p else None


def _inline_image_destinations(text: str):
    """Yield (start, end) spans of each inline image destination token."""
    p = 0
    while True:
        k = text.find("![", p)
        if k < 0:
            return
        p = k + 2
        if k > 0 and not _unescaped_at(text, k):
            continue
        alt_end = _scan_bracket(text, k + 1, "[", "]")
        if alt_end is None or alt_end >= len(text) or text[alt_end] != "(":
            continue
        q = alt_end + 1
        while q < len(text) and text[q] in " \t":
            q += 1
        if q < len(text) and text[q] in "\n\r":
            q += 1
            while q < len(text) and text[q] in " \t":
                q += 1
        dest = _bare_destination(text, q)
        if dest is None:
            continue
        ds, de = dest
        # Skip an optional title and require the enclosing closing paren so
        # scanning continues after the complete (possibly parenthesised) image.
        r = de
        newlines = 0
        while r < len(text) and text[r] in " \t\n\r":
            if text[r] in "\n\r":
                newlines += 1
                if newlines > 1:
                    break
            r += 1
        if r < len(text) and text[r] in "'\"":
            quote = text[r]
            r += 1
            while r < len(text) and text[r] != quote:
                if text[r] == "\\":
                    r += 2
                    continue
                r += 1
            if r < len(text) and text[r] == quote:
                r += 1
                while r < len(text) and text[r] in " \t\n\r":
                    r += 1
        if r < len(text) and text[r] == ")":
            yield ds, de
            p = r + 1


def prepare_images_for_save(text: str, old_base: str | None, target_path: str,
                            folder: str = "assets") -> PreparedImageSave:
    """Stage local relative images on first save/Save As; caller commits or rolls back.

    No existing image is overwritten. A failed document write can roll back every
    new copied file. Inline Markdown, image reference definitions and HTML images
    are supported; destinations are parsed with full bracket/paren awareness.
    Remote and absolute image references retain their semantics.
    """
    staged = PreparedImageSave(text)
    if not old_base:
        return staged
    source_base = Path(old_base).resolve()
    new_base = Path(target_path).resolve().parent
    if source_base == new_base:
        return staged
    target_dir = (new_base / folder).resolve()
    references: dict[str, str] = {}

    def relocate(token: str) -> str:
        angled = token.startswith("<") and token.endswith(">")
        original = token[1:-1] if angled else token
        try:
            local = local_image_path(original, str(source_base))
        except (OSError, ValueError):
            return token
        # Only relative authored references need moving to the new document base.
        decoded = unquote(original)
        if local is None or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", original) or Path(decoded).is_absolute():
            return token
        if original not in references:
            if local.is_file():
                target_dir.mkdir(parents=True, exist_ok=True)
                target = _write_unique(target_dir / local.name, source=local)
                staged.created_paths.append(target)
            else:
                target = local
            references[original] = _reference(target, new_base)
        reference = references[original]
        return "<" + reference + ">" if angled else reference

    def relocate_inline(segment: str) -> str:
        pieces = []
        last = 0
        for ds, de in _inline_image_destinations(segment):
            pieces.append(segment[last:ds])
            pieces.append(relocate(segment[ds:de]))
            last = de
        pieces.append(segment[last:])
        return "".join(pieces)

    try:
        segments = _prose_segments(text)
        prose = "\n".join(segment for editable, segment in segments if editable)
        labels = {(" ".join((m.group(2) or m.group(1)).split())).casefold()
                  for m in _IMAGE_REF_RE.finditer(prose)}
        rewritten = []
        for editable, segment in segments:
            if editable:
                segment = relocate_inline(segment)
                segment = _REF_DEFINITION_RE.sub(
                    lambda m: m.group(1) + relocate(m.group(3))
                    if " ".join(m.group(2).split()).casefold() in labels else m.group(0), segment)
                segment = _HTML_IMAGE_RE.sub(
                    lambda m: m.group(1) + m.group(2) + relocate(m.group(3)) + m.group(2), segment)
            rewritten.append(segment)
        staged.text = "".join(rewritten)
    except Exception:
        staged.rollback()
        raise
    return staged
