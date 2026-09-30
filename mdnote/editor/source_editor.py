"""源码模式编辑器：QPlainTextEdit + 行号区 + Markdown 高亮。"""

from PySide6.QtCore import QRect, Qt, Signal, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from .md_highlighter import MarkdownHighlighter

_PAIRED = {"[": "]", "`": "`", "*": "*", "~": "~"}


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
        self._line_area = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self._update_line_area_width()
        self._highlighter = MarkdownHighlighter(self.document())
        self.textChanged.connect(self.content_changed_detail.emit)

    def apply_theme(self, theme: str) -> None:
        """切换编辑器背景 / 前景与语法高亮调色板。"""
        from .md_highlighter import editor_colors_for, palette_for

        bg, fg = editor_colors_for(theme)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(bg))
        palette.setColor(self.foregroundRole(), QColor(fg))
        self.setPalette(palette)
        self._highlighter.set_palette(palette_for(theme))

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
        painter.fillRect(event.rect(), QColor("#f6f8fa"))
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#8b949e"))
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
                cursor.insertText("  ")
                return
            self._indent_selection(cursor, True)
            return
        if event.key() == Qt.Key_Backtab:
            self._indent_selection(self.textCursor(), False)
            return
        text = event.text()
        if text and text in _PAIRED:
            cursor = self.textCursor()
            if not cursor.hasSelection():
                super().keyPressEvent(event)
                self.textCursor().insertText(_PAIRED[text])
                # 光标移回配对符号之间
                cursor = self.textCursor()
                cursor.movePosition(QTextCursor.Left)
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
            remove = 1 if text.startswith("\t") else min(2, len(text) - len(text.lstrip(" ")))
            changes.append((block.position(), remove))
            block = block.next()
        cursor.beginEditBlock()
        total = 0
        start_delta = 0
        for position, remove in reversed(changes):
            cursor.setPosition(position)
            if indent:
                cursor.insertText("  ")
                delta = 2
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
            cursor.setPosition(max(0, min(offset, len(text))))
            self.setTextCursor(cursor)

    def get_text(self) -> str:
        return self.toPlainText()

    def get_offset(self) -> int:
        return self.textCursor().position()

    def goto_line(self, line: int) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.Down, n=max(0, line - 1))
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
        self.setFocus()
