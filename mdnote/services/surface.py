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
    return _clean(markdown_engine().render(raw))


def _code_atom(block) -> str:
    # Code is a non-editable atom; clicking it opens a plaintext source editor.
    code_lines = block.raw.split("\n")[1:-1]
    code_text = _html.escape("\n".join(code_lines))
    label = block.lang or ""
    inner = (f'<div class="atom-label">{_html.escape(label) or "Code"}</div>'
             f'<pre class="surface-code-view"><code>{code_text}</code></pre>')
    return _atom("atom-code", block.raw, inner)


def _render_block(block) -> str:
    btype = block.type

    if btype == "frontmatter":
        display = _html.escape(block.raw)
        return _atom("atom-frontmatter", block.raw,
                     '<div class="atom-label">Front Matter</div>'
                     f'<pre>{display}</pre>')

    if btype == "code":
        if block.lang and block.lang.lower() == "mermaid":
            source = _html.escape("\n".join(block.raw.split("\n")[1:-1]))
            return _atom("atom-diagram", block.raw,
                         f'<pre class="mermaid">{source}</pre>')
        return _code_atom(block)

    if btype == "math":
        display = _html.escape(block.raw)
        return _atom("atom-math", block.raw,
                     f'<div class="math-source">{display}</div>')

    return _render_editable(block.raw)


def surface_html(text: str, doc_base: str | None = None) -> str:
    """Render the whole document as flat HTML for the continuous surface."""
    model = build_model(text)
    parts: list[str] = []
    for block in model.blocks:
        if block.trailing:
            # An editable trailing line: lets the caret sit at document end.
            parts.append('<p class="surface-end"><br></p>')
            continue
        parts.append(_render_block(block))
    return "".join(parts)
