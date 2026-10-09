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
    return quote(Path(os.path.relpath(target, base)).as_posix(), safe="/:")


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


# Preserve titles/alt text while replacing only the image destination token.
_INLINE_IMAGE_RE = re.compile(r'(!\[(?:\\.|[^\]\\])*\]\(\s*)(<[^>\n]*>|(?:\\.|[^\s)])+)', re.MULTILINE)
_IMAGE_REF_RE = re.compile(r'!\[([^\]\n]*)\](?:\[([^\]\n]*)\])?')
_REF_DEFINITION_RE = re.compile(r'^(\s{0,3}\[([^\]\n]+)\]:\s*)(<[^>\n]*>|\S+)', re.MULTILINE)
_HTML_IMAGE_RE = re.compile(r'(<img\b[^>]*?\bsrc=)(["\'])(.*?)\2', re.IGNORECASE)



def _prose_segments(text: str) -> list[tuple[bool, str]]:
    """Protect fenced/inline code examples from image-path rewriting."""
    protected = []
    offset = 0
    fence_start = None
    fence_character = ""
    fence_length = 0
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(" + chr(96) + r"{3,}|~{3,})(.*)", line.rstrip("\r\n"))
        if marker:
            token, rest = marker.groups()
            if fence_start is None:
                fence_start, fence_character, fence_length = offset, token[0], len(token)
            elif token[0] == fence_character and len(token) >= fence_length and not rest.strip():
                protected.append((fence_start, offset + len(line)))
                fence_start = None
        offset += len(line)
    if fence_start is not None:
        protected.append((fence_start, len(text)))
    for match in re.finditer("(" + chr(96) + r"+)([\s\S]*?)\1", text):
        protected.append((match.start(), match.end()))
    merged = []
    for start, end in sorted(protected):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    segments = []
    offset = 0
    for start, end in merged:
        if start > offset:
            segments.append((True, text[offset:start]))
        segments.append((False, text[start:end]))
        offset = end
    if offset < len(text):
        segments.append((True, text[offset:]))
    return segments


def prepare_images_for_save(text: str, old_base: str | None, target_path: str,
                            folder: str = "assets") -> PreparedImageSave:
    """Stage local relative images on first save/Save As; caller commits or rolls back.

    No existing image is overwritten. A failed document write can roll back every
    new copied file. Inline Markdown, image reference definitions and HTML images
    are supported. Remote and absolute image references retain their semantics.
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

    try:
        segments = _prose_segments(text)
        prose = "\n".join(segment for editable, segment in segments if editable)
        labels = {(" ".join((m.group(2) or m.group(1)).split())).casefold()
                  for m in _IMAGE_REF_RE.finditer(prose)}
        rewritten = []
        for editable, segment in segments:
            if editable:
                segment = _INLINE_IMAGE_RE.sub(lambda m: m.group(1) + relocate(m.group(2)), segment)
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
