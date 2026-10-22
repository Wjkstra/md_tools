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
from uuid import uuid4
from .html_service import local_image_path

import nh3

from .markdown_engine import markdown_engine
from ..editor.block_model import build_model

# Surface sanitizer: same baseline nh3 rules, plus task checkboxes.
_SURFACE_TAGS = set(nh3.ALLOWED_TAGS) | {"input", "mark", "sup", "sub"}
_SURFACE_ATTRIBUTES = dict(nh3.ALLOWED_ATTRIBUTES)
_SURFACE_ATTRIBUTES["input"] = {"class", "checked", "disabled"}
_SURFACE_ATTRIBUTES["span"] = set(_SURFACE_ATTRIBUTES.get("span", set())) | {"class"}
for _tag in ("a", "img"):
    _SURFACE_ATTRIBUTES[_tag] = set(_SURFACE_ATTRIBUTES.get(_tag, set())) | {"title"}
# Structural attributes we add ourselves; safe because this is our own surface.
_EXTRA_GLOBAL_ATTRS = {"contenteditable", "data-md", "data-lang", "data-md-attr-id"}
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
    return _clean(markdown_engine().render(raw, surface=True))


def _render_editable_batch(blocks) -> dict[int, str]:
    """Parse/sanitize bounded batches instead of resetting both per paragraph.

    A trusted HTML separator prevents adjacent lists from being merged. Its
    random token is absent from the input and is removed before page delivery.
    """
    result = {}
    for start in range(0, len(blocks), 128):
        batch = blocks[start:start + 128]
        token = uuid4().hex
        while any(token in block.raw for _, block in batch):
            token = uuid4().hex
        separator = f'<hr data-md="{token}">'
        raw = ("\n\n" + separator + "\n\n").join(block.raw for _, block in batch)
        rendered = _render_editable(raw).split(separator)
        if len(rendered) != len(batch):
            # An extension may consume HTML separators; fall back losslessly.
            rendered = [_render_editable(block.raw) for _, block in batch]
        result.update((index, html.strip()) for (index, _), html in zip(batch, rendered))
    return result


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


def _is_fenced(raw: str) -> bool:
    return re.match(r"^\s{0,3}(?:\x60{3,}|~{3,})", raw.split("\n", 1)[0]) is not None


def indented_body(raw: str) -> str:
    """Drop the four-space (or one-tab) indented-code indentation per line."""
    return "\n".join(re.sub(r"^(?:    |\t)", "", line) for line in raw.split("\n"))


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
    if _is_fenced(block.raw):
        body = fenced_body(block.raw)
    else:
        # Indented code block: the editor shows its de-indented body while
        # data-md keeps the verbatim authored text (4-space indent, any
        # embedded fences) so an untouched save round-trips exactly.
        body = indented_body(block.raw)
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
        # Plain-text mirror: Pygments highlighting is applied lazily by the
        # page only for code blocks near the viewport, avoiding full-document
        # syntax highlighting on every (re)render of long documents.
        f'<code>{_html.escape(body)}</code></pre>'
        '<pre class="md-code-area" contenteditable="true" '
        'spellcheck="false" role="textbox" aria-label="代码正文" aria-multiline="true">'
        f'<code>{_html.escape(body) or "<br>"}</code></pre></div></div></div>'
    )


def _definition_block(block) -> str | None:
    """Render cross-block reference/footnote/abbreviation definitions as atoms.

    Reference links (``[id]: url "title"``) and footnotes (``[^id]: body``)
    only resolve when the whole document is parsed together; per-block
    rendering would drop them on save. Abbreviations (``*[HTML]: ...``) work
    the same way. Keep them verbatim so a round trip never loses the
    definition or its URL/title.
    """
    if block.type != "paragraph":
        return None
    raw = block.raw.strip()
    is_reference = re.match(r"^\[[^\]\n]+\]:\s*\S+", raw) is not None
    is_footnote = re.match(r"^\[\^[^\]\n]+\]:\s*", raw) is not None
    is_abbreviation = re.match(r"^\*\[[^\]\n]+\]:\s*\S", raw) is not None
    if is_reference or is_footnote:
        kind = "atom-footnote-def" if is_footnote else "atom-reference-def"
        label = "脚注定义" if is_footnote else "引用定义"
    elif is_abbreviation:
        kind, label = "atom-abbr-def", "缩写定义"
    else:
        return None
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

    def replace(match: "re.Match") -> str:
        prefix, quote, src, suffix = match.groups()
        source = _html.unescape(src)
        try:
            candidate = local_image_path(src, doc_base)
            if candidate is None or not candidate.is_file():
                return match.group(0)
            uri = candidate.as_uri()
        except (OSError, ValueError):
            return match.group(0)
        esc = _html.escape(source, quote=True)
        return (f'{prefix}{quote}{uri}{quote}{suffix} '
                f'data-md-src="{esc}"')

    pattern = re.compile(r'(<img\b[^>]*?\ssrc=)(["\'])([^"\']+)\2([^>]*)', re.I)
    return pattern.sub(replace, html)


# ATX heading carrying an authored id:  "# Title {#custom}" / "{: #custom}".
_HEADING_ATTR_ID_RE = re.compile(
    r"^[ \t]{0,3}#{1,6}[ \t]+.*?\{:?[ \t]*#([A-Za-z0-9_-]+)[^}]*\}[ \t]*$"
)


def _heading_attr_id(raw: str) -> str | None:
    match = _HEADING_ATTR_ID_RE.match(raw.rstrip())
    return match.group(1) if match else None


def _with_heading_attr_id(markup: str, attr_id: str) -> str:
    safe = _html.escape(attr_id, quote=True)
    return re.sub(r"^(<h[1-6]\b)",
                  lambda m: f'{m.group(1)} data-md-attr-id="{safe}"',
                  markup, count=1)


def surface_html(text: str, doc_base: str | None = None) -> str:
    """Render the whole document as flat HTML for the continuous surface.

    Inter-block blank lines beyond the standard single paragraph break are
    emitted as empty editable paragraphs so they survive a surface -> Markdown
    round trip (otherwise switching modes would collapse them).
    """
    model = build_model(text)
    parts: list[str] = []
    blocks = model.blocks
    definitions = "\n\n".join(block.raw for block in blocks
                                  if _definition_block(block) is not None)
    rendered_special = {}
    toc = None
    heading_ids = []
    if any(block.type == "toc" for block in blocks):
        # All headings share one parser context, including duplicate slugs.
        engine = markdown_engine()
        engine.render("\n\n".join(block.raw for block in blocks if block.type == "heading"))
        toc = _clean(engine._md.toc)

        def collect(tokens):
            for token in tokens:
                heading_ids.append(token["id"])
                collect(token["children"])
        collect(engine._md.toc_tokens)
    ordinary = []
    for i, block in enumerate(blocks):
        if block.trailing or block.type in {"frontmatter", "code", "math"}:
            continue
        if _definition_block(block) is not None:
            continue
        if block.type == "toc":
            rendered_special[i] = _atom("atom-toc", block.raw, toc or "")
        elif block.type == "html" or re.search(r"^\s*:\s+", block.raw, re.M):
            # These HTML structures have no complete reverse serializer yet.
            rendered_special[i] = _atom("atom-structure", block.raw, _render_editable(block.raw))
        elif definitions and re.search(r"\[[^\]\n]+\]", block.raw):
            rendered_special[i] = _atom("atom-reference", block.raw,
                                         _render_editable(block.raw + "\n\n" + definitions))
        else:
            ordinary.append((i, block))
    rendered = _render_editable_batch(ordinary)
    heading_index = 0
    gap_blank = '<p><br></p>'
    for i, block in enumerate(blocks):
        if block.trailing:
            # Preserve any blank lines between the last content and the end.
            gap = model.gaps[i - 1] if i > 0 else 0
            extra = max(0, gap - 2)
            parts.append(gap_blank * extra)
            parts.append('<p class="surface-end"><br></p>')
            continue
        markup = rendered_special.get(i, rendered.get(i))
        if markup is None:
            markup = _render_block(block)
        if block.type == "heading" and toc is not None:
            # TOC mode reassigns every heading id from one parser context;
            # authored ids cannot be distinguished there, so drop them.
            markup = re.sub(r'\s+data-md-attr-id="[^"]*"', "", markup, count=1)
            if heading_index < len(heading_ids):
                markup = re.sub(r'\s+id="[^"]*"', "", markup, count=1)
                markup = re.sub(r"^(<h[1-6])", lambda m: m.group(1) +
                                f' id="{_html.escape(heading_ids[heading_index], quote=True)}"', markup)
            heading_index += 1
        elif block.type == "heading":
            attr_id = _heading_attr_id(block.raw)
            if attr_id and "data-md-attr-id=" not in markup:
                markup = _with_heading_attr_id(markup, attr_id)
        parts.append(_tag_model_index(markup, i))
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
