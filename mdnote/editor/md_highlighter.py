"""QPlainTextEdit 的 Markdown 语法高亮（轻量规则，支持主题调色板）。"""

import re

from PySide6.QtGui import QColor, QTextCharFormat, QFont, QSyntaxHighlighter


def _fmt(color, bold=False, italic=False, mono=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    f.setFontItalic(italic)
    if mono:
        f.setFontFamilies(["Consolas", "JetBrains Mono", "Courier New"])
    return f


# 每套主题的语义角色配色（角色: 标题 / 引用 / 列表 / 分隔 / 链接 / 代码 / 强调 / 正文 / 围栏）
PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "heading": "#0969da", "quote": "#57606a", "list": "#cf222e",
        "rule": "#57606a", "link": "#0969da", "code": "#cf222e",
        "strong": "#24292f", "text": "#24292f", "fence": "#57606a",
    },
    "dark": {
        "heading": "#58a6ff", "quote": "#8b949e", "list": "#ff7b72",
        "rule": "#8b949e", "link": "#58a6ff", "code": "#ff7b72",
        "strong": "#c9d1d9", "text": "#c9d1d9", "fence": "#8b949e",
    },
    "solarized": {
        "heading": "#268bd2", "quote": "#839496", "list": "#dc322f",
        "rule": "#839496", "link": "#268bd2", "code": "#dc322f",
        "strong": "#586e75", "text": "#586e75", "fence": "#839496",
    },
    "sepia": {
        "heading": "#9c6630", "quote": "#8a7663", "list": "#a04a3a",
        "rule": "#8a7663", "link": "#9c6630", "code": "#a04a3a",
        "strong": "#5b4636", "text": "#5b4636", "fence": "#8a7663",
    },
    "night": {
        "heading": "#7aa2f7", "quote": "#7d8590", "list": "#f7768e",
        "rule": "#7d8590", "link": "#7aa2f7", "code": "#f7768e",
        "strong": "#c4c9d2", "text": "#c4c9d2", "fence": "#7d8590",
    },
    "monokai": {
        "heading": "#a6e22e", "quote": "#a6a297", "list": "#f92672",
        "rule": "#a6a297", "link": "#a6e22e", "code": "#f92672",
        "strong": "#f8f8f2", "text": "#f8f8f2", "fence": "#a6a297",
    },
    "dracula": {
        "heading": "#bd93f9", "quote": "#a4acc4", "list": "#ff79c6",
        "rule": "#a4acc4", "link": "#bd93f9", "code": "#ff79c6",
        "strong": "#f8f8f2", "text": "#f8f8f2", "fence": "#a4acc4",
    },
}


def palette_for(theme: str) -> dict[str, str]:
    t = theme.lower()
    for theme_id, palette in PALETTES.items():
        if theme_id in t:
            return palette
    return PALETTES["light"]


# 编辑器背景 / 前景（由主题决定；供 QPlainTextEdit 使用）
EDITOR_COLORS: dict[str, tuple[str, str]] = {
    "light": ("#ffffff", "#24292f"),
    "dark": ("#0d1117", "#c9d1d9"),
    "solarized": ("#fdf6e3", "#586e75"),
    "sepia": ("#f5ecd9", "#5b4636"),
    "night": ("#000000", "#c4c9d2"),
    "monokai": ("#272822", "#f8f8f2"),
    "dracula": ("#282a36", "#f8f8f2"),
}


def editor_colors_for(theme: str) -> tuple[str, str]:
    t = theme.lower()
    for theme_id, colors in EDITOR_COLORS.items():
        if theme_id in t:
            return colors
    return EDITOR_COLORS["light"]


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, doc, palette: dict[str, str] | None = None) -> None:
        super().__init__(doc)
        self._fence = re.compile(r"^(\s{0,3})(`{3,}|~{3,})")
        self.set_palette(palette or PALETTES["light"], rehighlight=False)

    def set_palette(self, p: dict[str, str], rehighlight: bool = True) -> None:
        self._palette = p
        self._rules = [
            (re.compile(r"^(\s{0,3})(#{1,6})(\s.*)?$"),
             _fmt(p["heading"], bold=True)),
            (re.compile(r"^\s{0,3}>.*$"), _fmt(p["quote"], italic=True)),
            (re.compile(r"^\s{0,3}(?:[-+*]|\d{1,9}[.)])\s+"),
             _fmt(p["list"])),
            (re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})$"),
             _fmt(p["rule"])),
            (re.compile(r"!?\[[^\]]*\]\([^)]*\)"), _fmt(p["link"])),
            (re.compile(r"`[^`]+`"), _fmt(p["code"], mono=True)),
            (re.compile(r"\*\*[^*]+\*\*"), _fmt(p["strong"], bold=True)),
            (re.compile(r"(?<!\*)\*[^*]+\*(?!\*)"),
             _fmt(p["text"], italic=True)),
            (re.compile(r"~~[^~]+~~"), _fmt(p["quote"])),
        ]
        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        p = self._palette
        # 代码围栏整体置灰
        in_fence = self.previousBlockState() == 1
        m = self._fence.match(text)
        if m:
            self.setFormat(0, len(text), _fmt(p["fence"], mono=True))
            self.setCurrentBlockState(0 if in_fence else 1)
            return
        if in_fence:
            self.setFormat(0, len(text), _fmt(p["fence"], mono=True))
            self.setCurrentBlockState(1)
            return

        self.setCurrentBlockState(0)
        for rx, fmt in self._rules:
            for match in rx.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
