"""Markdown 渲染引擎：Python-Markdown + 代码高亮 + GFM 任务列表。"""

import html
import re
from pathlib import Path

from pygments.formatters import HtmlFormatter
import markdown
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor

from .plugin_loader import load_enabled_named

_TASK_RE = re.compile(
    r"<li(?P<attr>[^>]*)>(?P<lead><p>)?"
    r"\s*\[(?P<check>[ xX])\]\s?",
)
_FENCE_RE = re.compile(r"^ {0,3}(" + chr(96) + r"{3,}|~{3,})(.*)$")


class _MermaidPreprocessor(Preprocessor):
    """Keep Mermaid source out of Pygments so the renderer can recognize it."""

    def run(self, lines):
        result = []
        index = 0
        while index < len(lines):
            match = _FENCE_RE.match(lines[index])
            if not match:
                result.append(lines[index])
                index += 1
                continue
            fence, info = match.groups()
            close = re.compile(r"^ {0,3}" + re.escape(fence[0]) +
                               "{" + str(len(fence)) + r",}[ \t]*$")
            end = index + 1
            while end < len(lines) and not close.fullmatch(lines[end]):
                end += 1
            if end == len(lines):
                result.extend(lines[index:])
                break
            if info.strip() in ("mermaid", "{.mermaid}"):
                source = html.escape("\n".join(lines[index + 1:end]), quote=False)
                markup = f'<pre><code class="language-mermaid">{source}\n</code></pre>'
                result.extend(["", self.md.htmlStash.store(markup), ""])
            else:
                # Skip the entire surrounding fence; nested Mermaid-looking text is code.
                result.extend(lines[index:end + 1])
            index = end + 1
        return result


class _MermaidExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(_MermaidPreprocessor(md), "mdnote_mermaid", 26)


def _replace_task(match: re.Match) -> str:
    checked = "checked" if match.group("check").lower() == "x" else ""
    return (f'<li class="task-list-item"{match.group("attr")}>'
            f'<input class="task-checkbox" type="checkbox" disabled {checked}/>'
            f'{match.group("lead") or ""}')


def pygments_css() -> str:
    return HtmlFormatter(style="default").get_style_defs(".codehilite")


BASE_EXTENSIONS = ["extra", "nl2br", "sane_lists", "toc", "codehilite"]


class MarkdownEngine:
    def __init__(self, plugin_extensions: list | None = None) -> None:
        self._md = markdown.Markdown(
            extensions=BASE_EXTENSIONS + [_MermaidExtension()] + list(plugin_extensions or []),
            extension_configs={
                "codehilite": {"guess_language": False, "use_pygments": True},
                "toc": {"permalink": False},
            },
        )

    def add_extension(self, extension: Extension) -> None:
        self._md.registerExtensions([extension], {})

    def render(self, raw: str) -> str:
        self._md.reset()
        return _TASK_RE.sub(_replace_task, self._md.convert(raw))


_engine: MarkdownEngine | None = None


def markdown_engine() -> MarkdownEngine:
    global _engine
    _engine = _engine or MarkdownEngine()
    return _engine


def reconfigure(enabled_names: list[str],
                plugins_directory: Path | None = None) -> list[tuple[str, str]]:
    """Keep startup usable even if an enabled extension fails during registration."""
    global _engine
    plugins, errors = load_enabled_named(enabled_names, plugins_directory)
    accepted = []
    candidate = MarkdownEngine()
    for name, extension in plugins:
        try:
            candidate.add_extension(extension)
        except Exception as exc:
            errors.append((name, f"注册失败：{type(exc).__name__}: {exc}"))
            # A faulty plugin may have already mutated registries. Discard that engine.
            try:
                candidate = MarkdownEngine([item for _name, item in accepted])
            except Exception as recovery_error:
                errors.extend((accepted_name, f"恢复失败：{recovery_error}")
                              for accepted_name, _item in accepted)
                accepted = []
                candidate = MarkdownEngine()
        else:
            accepted.append((name, extension))
    _engine = candidate
    return errors


def escape_html(value: str) -> str:
    return html.escape(value, quote=True)
