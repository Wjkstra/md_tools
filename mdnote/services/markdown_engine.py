"""Markdown 渲染引擎：Python-Markdown + Pygments 代码高亮 + GFM 任务列表。"""

import html
import re
from pathlib import Path

from pygments.formatters import HtmlFormatter
import markdown

from .plugin_loader import load_enabled

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


# 内置基础扩展；用户插件追加在其后
BASE_EXTENSIONS = ["extra", "nl2br", "sane_lists", "toc", "codehilite"]


class MarkdownEngine:
    def __init__(self, plugin_extensions: list | None = None) -> None:
        extensions = BASE_EXTENSIONS + list(plugin_extensions or [])
        self._md = markdown.Markdown(
            extensions=extensions,
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
    _engine = _engine or MarkdownEngine()
    return _engine


def reconfigure(
    enabled_names: list[str],
    plugins_directory: Path | None = None,
) -> list[tuple[str, str]]:
    """按启用的插件名单重建单例引擎，返回加载错误列表。"""
    global _engine
    plugins, errors = load_enabled(enabled_names, plugins_directory)
    _engine = MarkdownEngine(plugins)
    return errors


def escape_html(s: str) -> str:
    return html.escape(s, quote=True)
