"""Markdown 渲染引擎：Python-Markdown + Pygments 代码高亮 + GFM 任务列表。"""

import html
import re

from pygments.formatters import HtmlFormatter
import markdown


_TASK_RE = re.compile(
    r"<li(?P<attr>[^>]*)>(?P<lead><p>)?"
    r"\s*\[(?P<check>[ xX])\]\s?",
)


def _replace_task(m: re.Match) -> str:
    checked = "checked" if m.group("check").lower() == "x" else ""
    return (
        f'<li class="task-list-item"{m.group("attr")}>'
        f'<input class="task-checkbox" type="checkbox" disabled {checked}/>'
        f'{m.group("lead") or ""}'
    )


def pygments_css() -> str:
    return HtmlFormatter(style="default").get_style_defs(".codehilite")


class MarkdownEngine:
    def __init__(self) -> None:
        self._md = markdown.Markdown(
            extensions=[
                "extra",
                "nl2br",
                "sane_lists",
                "toc",
                "codehilite",
            ],
            extension_configs={
                "codehilite": {"guess_language": False, "use_pygments": True},
                "toc": {"permalink": False},
            },
        )

    def render(self, raw: str) -> str:
        self._md.reset()
        body = self._md.convert(raw)
        return _TASK_RE.sub(_replace_task, body)


_engine: MarkdownEngine | None = None


def markdown_engine() -> MarkdownEngine:
    global _engine
    if _engine is None:
        _engine = MarkdownEngine()
    return _engine


def escape_html(s: str) -> str:
    return html.escape(s, quote=True)
