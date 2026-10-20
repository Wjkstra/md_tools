"""Render pipeline for the continuous (Typora-style) editing surface.

Live mode renders the whole document into ONE contenteditable element (see
app.js). Blocks are laid out flat and contiguously so the native selection/caret
can cross them:

- editable blocks (headings, paragraphs, lists, quotes, tables, normal code)
  render to their usual HTML and stay editable,
- complex blocks (front matter, Mermaid diagrams, block math) are non-editable
  "atoms" carrying their original Markdown in ``data-md``; the page fills in
  their rendered form (diagram/formula) and the user can switch the atom to
  source editing.

Normal code is a plain editable ``<pre data-lang>`` so the reverse serializer
can restore its language (Pygments would otherwise drop it).
"""

import html as _html
import re
from pathlib import Path

import nh3

from .markdown_engine import markdown_engine
from ..editor.block_model import build_model

# Surface sanitizer: same baseline nh3 rules, plus task checkboxes.
_SURFACE_TAGS = set(nh3.ALLOWED_TAGS) | {"input"}
_SURFACE_ATTRIBUTES = dict(nh3.ALLOWED_ATTRIBUTES)
_SURFACE_ATTRIBUTES["input"] = {"class", "checked", "disabled"}
# Structural attributes we add ourselves; safe because this is our own surface.
_EXTRA_GLOBAL_ATTRS = {"contenteditable", "data-md", "data-lang"}
_SURFACE_ATTRIBUTES["*"] = (
    set(_SURFACE_ATTRIBUTES.get("*", set())) | _EXTRA_GLOBAL_ATTRS)
# Table cells keep text-align (alignment marker); the style-property whitelist
# below strips everything else from style.
for _cell_tag in ("th", "td"):
    _SURFACE_ATTRIBUTES[_cell_tag] = set(
        _SURFACE_ATTRIBUTES.get(_cell_tag, set())) | {"style"}
_TAG_ATTRIBUTE_VALUES = {"input": {"type": {"checkbox"}}}
_ALLOWED_STYLE_PROPERTIES = {"text-align"}


def _clean(rendered: str) -> str:
    return nh3.clean(
        rendered,
        tags=_SURFACE_TAGS,
        attributes=_SURFACE_ATTRIBUTES,
        tag_attribute_values=_TAG_ATTRIBUTE_VALUES,
        filter_style_properties=_ALLOWED_STYLE_PROPERTIES,
    )


def _atom(atom_class: str, source_md: str, inner: str) -> str:
    data_md = _html.escape(source_md, quote=True)
    return (f'<div class="md-atom {atom_class}" contenteditable="false" '
            f'data-md="{data_md}">{inner}</div>')


def _render_editable(raw: str) -> str:
    # Preserve backslash escapes across the render round trip: swap
    # "\X" for private-use placeholders before markdown, then turn the
    # surviving placeholders into md-literal spans that html_to_md restores.
    kept: list[str] = []

    def keep(match: "re.Match") -> str:
        kept.append(match.group(1))
        return f"{len(kept) - 1}"

    tokened = re.sub(r"\\([\\`*_{}\[\]()#+\-.!<>~|$])", keep, raw)
    html = _clean(markdown_engine().render(tokened))

    def restore(match: "re.Match") -> str:
        index = int(match.group(1))
        char = kept[index]
        return (f'<span class="md-literal" data-md="\\{_html.escape(char, quote=True)}">'
                f"{_html.escape(char)}</span>")

    return re.sub(r"(\d+)", restore, html)


def fenced_body(raw: str) -> str:
    """Remove only actual fence lines; keep the last line of unfinished code."""
    lines = raw.split("\n")
    opener = re.match(r"^\s{0,3}(\x60{3,}|~{3,})", lines[0])
    body = lines[1:]
    if opener and body:
        fence = opener.group(1)
        if re.fullmatch(r"\s{0,3}" + re.escape(fence[0]) +
                        "{" + str(len(fence)) + r",}\s*", body[-1]):
            body.pop()
    return "\n".join(body)


def highlight_code(source: str, language: str) -> str:
    """Trusted, escaped highlighting HTML, without changing source whitespace."""
    from pygments import lex
    from pygments.lexers import get_lexer_by_name, TextLexer
    from pygments.token import STANDARD_TYPES
    from pygments.util import ClassNotFound
    try:
        lexer = get_lexer_by_name(language or "text", stripnl=False, ensurenl=False)
    except ClassNotFound:
        lexer = TextLexer(stripnl=False, ensurenl=False)
    # Avoid doing expensive lexing on huge pasted blocks.
    if len(source) > 100_000:
        return _html.escape(source)
    def token_class(token):
        while token not in STANDARD_TYPES:
            token = token.parent
        return STANDARD_TYPES[token]
    return "".join(
        f'<span class="{token_class(token)}">{_html.escape(value)}</span>'
        for token, value in lex(source, lexer)
    )


def _code_block(block) -> str:
    body = fenced_body(block.raw)
    esc = lambda value: _html.escape(value, quote=True)
    lang = block.lang or ""
    return (
        '<div class="md-code" contenteditable="false" '
        f'data-lang="{esc(lang)}" data-source="{esc(body)}" '
        f'data-original-lang="{esc(lang)}" data-md="{esc(block.raw)}">'
        f'<span class="md-code-lang" hidden>{esc(lang or "text")}</span>'
        '<div class="md-code-tools"></div>'
        '<div class="md-code-scroll"><div class="md-code-body">'
        '<pre class="md-code-highlight" aria-hidden="true" inert>'
        f'<code>{highlight_code(body, lang)}</code></pre>'
        '<pre class="md-code-area" contenteditable="true" '
        'spellcheck="false" role="textbox" aria-label="代码正文" aria-multiline="true">'
        f'<code>{_html.escape(body) or "<br>"}</code></pre></div></div></div>'
    )


def _definition_block(block) -> str | None:
    """Render cross-block reference/footnote definitions as preserved atoms.

    Reference links (``[id]: url "title"``) and footnotes (``[^id]: body``)
    only resolve when the whole document is parsed together; per-block
    rendering would drop them on save. Keep them verbatim so a round trip
    never loses the definition or its URL/title.
    """
    if block.type != "paragraph":
        return None
    raw = block.raw.strip()
    is_reference = re.match(r"^\[[^\]\n]+\]:\s*\S+", raw) is not None
    is_footnote = re.match(r"^\[\^[^\]\n]+\]:\s*", raw) is not None
    if not (is_reference or is_footnote):
        return None
    kind = "atom-footnote-def" if is_footnote else "atom-reference-def"
    label = "脚注定义" if is_footnote else "引用定义"
    return _atom(kind, block.raw,
                 f'<div class="atom-label">{label}</div>'
                 f'<pre>{_html.escape(raw)}</pre>')


def _render_block(block) -> str:
    btype = block.type

    if btype == "frontmatter":
        display = _html.escape(block.raw)
        return _atom("atom-frontmatter", block.raw,
                     '<div class="atom-label">Front Matter</div>'
                     f'<pre>{display}</pre>')

    if btype == "code":
        if block.lang and block.lang.lower() == "mermaid":
            source = _html.escape(fenced_body(block.raw))
            return _atom("atom-diagram", block.raw,
                         f'<pre class="mermaid">{source}</pre>')
        return _code_block(block)

    if btype == "math":
        display = _html.escape(block.raw)
        # Source stays in data-md (round-trip) / hidden node for editing;
        # the empty render node is filled with KaTeX by postProcess.
        return _atom("atom-math", block.raw,
                     '<div class="math-source" hidden>' + display + "</div>"
                     '<div class="math-render"></div>')

    definition = _definition_block(block)
    if definition is not None:
        return definition

    return _render_editable(block.raw)


def _resolve_relative_images(html: str, doc_base: str | None) -> str:
    """Rewrite relative image sources to file:// URLs for the live preview.

    The live surface is loaded from mdnote/editor/web/, so a relative
    ``src="assets/x.png"`` would otherwise resolve against that directory
    instead of the document's folder. The original reference is kept in
    ``data-md-src`` so saving still writes a document-relative path.
    """
    if not doc_base:
        return html

    def _to_file_uri(path: "Path") -> str:
        from urllib.parse import quote
        return Path(path).resolve().as_uri()

    def replace(match: "re.Match") -> str:
        prefix, quote, src, suffix = match.groups()
        lowered = src.lower()
        if (lowered.startswith(("http://", "https://", "file://", "data:"))
                or src.startswith(("#", "/"))):
            return match.group(0)
        candidate = Path(doc_base) / src
        if not candidate.exists():
            return match.group(0)
        uri = Path(candidate).resolve().as_uri()
        esc = _html.escape(src, quote=True)
        return (f'{prefix}{quote}{uri}{quote}{suffix} '
                f'data-md-src="{esc}"')

    pattern = re.compile(r'(<img\b[^>]*?\ssrc=)(["\'])([^"\']+)\2([^>]*)', re.I)
    return pattern.sub(replace, html)


def surface_html(text: str, doc_base: str | None = None) -> str:
    """Render the whole document as flat HTML for the continuous surface.

    Inter-block blank lines beyond the standard single paragraph break are
    emitted as empty editable paragraphs so they survive a surface -> Markdown
    round trip (otherwise switching modes would collapse them).
    """
    model = build_model(text)
    parts: list[str] = []
    blocks = model.blocks
    gap_blank = '<p><br></p>'
    for i, block in enumerate(blocks):
        if block.trailing:
            # Preserve any blank lines between the last content and the end.
            gap = model.gaps[i - 1] if i > 0 else 0
            extra = max(0, gap - 2)
            parts.append(gap_blank * extra)
            parts.append('<p class="surface-end"><br></p>')
            continue
        parts.append(_tag_model_index(_render_block(block), i))
        # Blank paragraphs between this block and the next.
        if i + 1 < len(blocks):
            gap = model.gaps[i]
            if not blocks[i + 1].trailing:
                parts.append(gap_blank * max(0, gap - 2))
    return _resolve_relative_images("".join(parts), doc_base)


def _tag_model_index(html: str, index: int) -> str:
    """Tag a rendered block's root element with its model block index.

    Blank-line placeholder paragraphs are intentionally untagged so outline
    navigation targets the real block even when blank lines shift the raw
    child-element position.
    """
    return re.sub(
        r"^(<[a-zA-Z][\w-]*)",
        lambda m: f'{m.group(1)} data-model-index="{index}"',
        html,
        count=1,
    )
