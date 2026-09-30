"""QPlainTextEdit 的 Markdown 语法高亮（轻量规则）。"""

import re

from PySide6.QtGui import QColor, QTextCharFormat, QFont, QSyntaxHighlighter


def _fmt(color: str, bold=False, italic=False, mono=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    f.setFontItalic(italic)
    if mono:
        f.setFontFamilies(["Consolas", "JetBrains Mono", "Courier New"])
    return f


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, doc) -> None:
        super().__init__(doc)
        self._rules = [
            (re.compile(r"^(\s{0,3})(#{1,6})(\s.*)?$"), _fmt("#0969da", bold=True)),
            (re.compile(r"^\s{0,3}>.*$"), _fmt("#57606a", italic=True)),
            (re.compile(r"^\s{0,3}(?:[-+*]|\d{1,9}[.)])\s+"), _fmt("#cf222e")),
            (re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})$"), _fmt("#57606a")),
            (re.compile(r"!?\[[^\]]*\]\([^)]*\)"), _fmt("#0969da")),
            (re.compile(r"`[^`]+`"), _fmt("#cf222e", mono=True)),
            (re.compile(r"\*\*[^*]+\*\*"), _fmt("#24292f", bold=True)),
            (re.compile(r"(?<!\*)\*[^*]+\*(?!\*)"), _fmt("#24292f", italic=True)),
            (re.compile(r"~~[^~]+~~"), _fmt("#57606a")),
        ]
        self._fence = re.compile(r"^(\s{0,3})(`{3,}|~{3,})")

    def highlightBlock(self, text: str) -> None:
        # 代码围栏整体置灰
        in_fence = self.previousBlockState() == 1
        m = self._fence.match(text)
        if m:
            self.setFormat(0, len(text), _fmt("#57606a", mono=True))
            self.setCurrentBlockState(0 if in_fence else 1)
            return
        if in_fence:
            self.setFormat(0, len(text), _fmt("#57606a", mono=True))
            self.setCurrentBlockState(1)
            return

        self.setCurrentBlockState(0)
        for rx, fmt in self._rules:
            for match in rx.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)
