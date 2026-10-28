"""Shared sanitization and local image resolution for previews and exports."""

import base64
import mimetypes
import re
from html import escape, unescape
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

import nh3

_ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "col", "colgroup", "dd",
    "del", "div", "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "input", "ins", "kbd", "li", "mark", "nav", "ol", "p",
    "pre", "q", "s", "samp", "small", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul", "var",
}
_ALLOWED_ATTRS = {
    "*": {"class", "id", "title", "style"}, "a": {"href", "title", "data-toc-id"},
    "img": {"src", "alt", "title", "width", "height"},
    "input": {"type", "checked", "disabled"},
    "td": {"colspan", "rowspan", "align"}, "th": {"colspan", "rowspan", "align"},
    "col": {"span"},
    "ol": {"start"}, "li": {"value"},
}
_URL_SCHEMES = {"http", "https", "mailto", "tel", "file", "data"}
_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=)(["\'])(.*?)\2', re.IGNORECASE)


def local_image_path(source: str, base: str | None = None) -> Path | None:
    """Resolve a local image URL without treating remote URLs as filenames."""
    source = unescape(source).strip()
    if re.match(r"^[A-Za-z]:[\\/]", source):
        return Path(unquote(source)).resolve()
    parsed = urlsplit(source)
    if parsed.scheme == "file":
        filename = url2pathname(parsed.path)
        if parsed.netloc:
            filename = "//" + parsed.netloc + filename
        return Path(filename).resolve()
    if parsed.scheme or source.startswith("//"):
        return None
    target = Path(unquote(parsed.path))
    if not target.is_absolute():
        if not base:
            return None
        target = Path(base) / target
    return target.resolve()


def rewrite_relative_images(markup: str, base: str | None = None,
                            *, embed_images: bool = False) -> str:
    def replace(match: re.Match) -> str:
        try:
            target = local_image_path(match.group(3), base)
            if target is None:
                return match.group(0)
            if embed_images and target.is_file():
                mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                reference = "data:" + mime + ";base64," + base64.b64encode(target.read_bytes()).decode("ascii")
            else:
                reference = target.as_uri()
        except (OSError, ValueError):
            return match.group(0)
        quote = match.group(2)
        return match.group(1) + quote + escape(reference, quote=True) + quote
    return _IMG_SRC_RE.sub(replace, markup)


def safe_html(markup: str, base: str | None = None, *, embed_images: bool = False) -> str:
    """Sanitize authored HTML, then resolve image references consistently."""
    cleaned = nh3.clean(markup, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRS,
                        url_schemes=_URL_SCHEMES)
    return rewrite_relative_images(cleaned, base, embed_images=embed_images)
