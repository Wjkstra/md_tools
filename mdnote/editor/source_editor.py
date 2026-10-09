"""源码模式编辑器：QPlainTextEdit + 行号区 + Markdown 高亮。"""

from PySide6.QtCore import QRect, Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QTextCursor, QPalette
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from .md_highlighter import MarkdownHighlighter
from ..core.settings import settings_service

_PAIRED = {"[": "]", "(": ")", "{": "}", "`": "`", "*": "*", "~": "~"}


class LineNumberArea(QWidget):
    def __init__(self, editor: "SourceEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_line_numbers(event)


class SourceEditor(QPlainTextEdit):
    content_changed_detail = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        font = QFont(["Consolas", "JetBrains Mono", "Courier New"], 10)
        self.setFont(font)
        self._gutter_bg = QColor("#f6f8fa")
        self._gutter_fg = QColor("#8b949e")
        self._line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self._update_line_area_width()
        self._highlighter = MarkdownHighlighter(self.document())
        self.textChanged.connect(self.content_changed_detail.emit)
        self.apply_prefs()

    def apply_prefs(self) -> None:
        settings = settings_service().current
        self._tab_size = max(1, min(8, settings.tab_size))
        self._auto_bracket = settings.auto_bracket
        font = self.font()
        font.setPixelSize(settings.font_size)
        if font != self.font():
            self.setFont(font)
            self._update_line_area_width()
        distance = self.fontMetrics().horizontalAdvance(" ") * self._tab_size
        if self.tabStopDistance() != distance:
            self.setTabStopDistance(distance)
        self.apply_theme(settings.theme)

    def apply_theme(self, theme: str) -> None:
        """切换编辑器背景 / 前景与语法高亮调色板。"""
        from .md_highlighter import editor_colors_for, palette_for

        bg, fg = editor_colors_for(theme)
        colors = palette_for(theme)
        signature = (bg, fg, tuple(colors.items()))
        if getattr(self, "_applied_theme", None) == signature:
            return
        self._applied_theme = signature
        palette = self.palette()
        palette.setColor(QPalette.Base, QColor(bg))
        palette.setColor(QPalette.Text, QColor(fg))
        self._gutter_bg = QColor(bg).lighter(130) if QColor(bg).lightness() < 128 else QColor(bg).darker(104)
        self._gutter_fg = QColor(palette_for(theme)["quote"])
        self._line_area.update()
        self.setPalette(palette)
        accent = palette_for(theme)["link"]
        self.setStyleSheet(f"QPlainTextEdit {{ background-color: {bg}; color: {fg}; "
                          f"border: 0; selection-background-color: {accent}; "
                          f"selection-color: {bg}; }}")
        self._highlighter.set_palette(colors)

    # ---------------- 行号 ----------------

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_area_width(self) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_area(self, rect: QRect, dy: int) -> None:
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(
            QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height())
        )

    def paint_line_numbers(self, event) -> None:
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), self._gutter_bg)
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(self._gutter_fg)
                painter.drawText(
                    0,
                    top,
                    self._line_area.width() - 4,
                    self.fontMetrics().height(),
                    Qt.AlignRight,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            block_number += 1

    # ---------------- 按键 ----------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Tab:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                cursor.insertText(" " * self._tab_size)
                return
            self._indent_selection(cursor, True)
            return
        if event.key() == Qt.Key_Backtab:
            self._indent_selection(self.textCursor(), False)
            return
        text = event.text()
        plain_key = not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
        if self._auto_bracket and plain_key:
            cursor = self.textCursor()
            position = cursor.position()
            if not cursor.hasSelection():
                following = self.document().characterAt(position)
                if text in ("]", ")", "}") and following == text:
                    cursor.movePosition(QTextCursor.Right)
                    self.setTextCursor(cursor)
                    return
                if event.key() == Qt.Key_Backspace and position > 0:
                    preceding = self.document().characterAt(position - 1)
                    if _PAIRED.get(preceding) == following:
                        cursor.beginEditBlock()
                        cursor.setPosition(position - 1)
                        cursor.setPosition(position + 1, QTextCursor.KeepAnchor)
                        cursor.removeSelectedText()
                        cursor.endEditBlock()
                        self.setTextCursor(cursor)
                        return
            if text in _PAIRED:
                start = cursor.selectionStart()
                selected = cursor.selectedText().replace("\u2029", "\n")
                cursor.beginEditBlock()
                cursor.insertText(text + selected + _PAIRED[text])
                cursor.setPosition(start + 1)
                if selected:
                    cursor.setPosition(start + 1 + len(selected.encode("utf-16-le")) // 2,
                                       QTextCursor.KeepAnchor)
                cursor.endEditBlock()
                self.setTextCursor(cursor)
                return
        super().keyPressEvent(event)

    def _indent_selection(self, cursor: QTextCursor, indent: bool) -> None:
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        selected = cursor.hasSelection()
        first = self.document().findBlock(start)
        last = self.document().findBlock(max(start, end - 1) if selected else end)
        changes = []
        block = first
        while block.isValid() and block.position() <= last.position():
            text = block.text()
            remove = 1 if text.startswith("\t") else min(self._tab_size, len(text) - len(text.lstrip(" ")))
            changes.append((block.position(), remove))
            block = block.next()
        cursor.beginEditBlock()
        total = 0
        start_delta = 0
        for position, remove in reversed(changes):
            cursor.setPosition(position)
            if indent:
                cursor.insertText(" " * self._tab_size)
                delta = self._tab_size
            else:
                cursor.setPosition(position + remove, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                delta = -remove
            total += delta
            if position <= start:
                start_delta += delta if delta >= 0 else -min(remove, start - position)
        cursor.endEditBlock()
        cursor.setPosition(max(0, start + start_delta))
        if selected:
            cursor.setPosition(max(0, end + total), QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)

    # ---------------- 文本 API ----------------

    def set_text(self, text: str, offset: int | None = None) -> None:
        self.setPlainText(text)
        if offset is not None:
            cursor = self.textCursor()
            cursor.setPosition(max(0, min(offset, self.document().characterCount() - 1)))
            self.setTextCursor(cursor)

    def get_text(self) -> str:
        return self.toPlainText()

    def get_offset(self) -> int:
        return self.textCursor().position()

    def goto_line(self, line: int) -> None:
        cursor = self.textCursor()
        block = self.document().findBlockByNumber(
            max(0, min(line - 1, self.document().blockCount() - 1))
        )
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.setFocus()
