"""查找 / 替换小栏。"""

from PySide6.QtCore import Signal, QEvent, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QLabel,
    QPushButton,
    QWidget,
)


class FindBar(QWidget):
    find_next = Signal(str, bool)  # text, forward
    replace_one = Signal(str, str)
    closed = Signal()
    query_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("findBar")
        self._sequence = 0
        self.hide()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        self._find = QLineEdit()
        self._find.setPlaceholderText("查找…")
        self._replace = QLineEdit()
        self._replace.setPlaceholderText("替换为…")
        self._find.setAccessibleName("查找文本")
        self._replace.setAccessibleName("替换文本")
        prev = QPushButton("上一个")
        nxt = QPushButton("下一个")
        rep = QPushButton("替换")
        close = QPushButton("×")
        close.setFixedWidth(30)
        close.setToolTip("关闭查找（Esc）")
        close.setAccessibleName("关闭查找")
        prev.setToolTip("上一个匹配（Shift+Enter / Shift+F3）")
        nxt.setToolTip("下一个匹配（Enter / F3）")
        self._replace_button = rep
        self._feedback = QLabel("")
        self._feedback.setObjectName("secondaryText")
        self._feedback.setMinimumWidth(110)
        self._feedback.setAccessibleName("查找结果")
        self._find.setClearButtonEnabled(True)
        self._find.textChanged.connect(self.reset_feedback)
        self._find.textChanged.connect(self.query_changed.emit)

        prev.clicked.connect(lambda: self.find_next.emit(self._find.text(), False))
        nxt.clicked.connect(lambda: self.find_next.emit(self._find.text(), True))
        rep.clicked.connect(
            lambda: self.replace_one.emit(self._find.text(), self._replace.text())
        )
        close.clicked.connect(self._close)

        for w in (self._find, self._replace, prev, nxt, rep, self._feedback, close):
            layout.addWidget(w)
            w.installEventFilter(self)

    def set_source_mode(self, source: bool) -> None:
        self._replace.setVisible(source)
        self._replace_button.setVisible(source)

    def reset_feedback(self) -> None:
        self._sequence += 1
        self._feedback.clear()

    def begin_search(self) -> int:
        self.reset_feedback()
        return self._sequence

    def show_result(self, token: int, found: bool, wrapped: str = "") -> None:
        if token != self._sequence:
            return
        self._feedback.setText((wrapped or "找到匹配") if found else "未找到匹配")

    def open(self) -> None:
        self.show()
        self._find.setFocus()
        self._find.selectAll()

    def next_match(self, forward: bool = True) -> None:
        self.find_next.emit(self._find.text(), forward)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._close()
                return True
            if obj in (self._find, self._replace) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if obj is self._replace:
                    self.replace_one.emit(self._find.text(), self._replace.text())
                else:
                    self.next_match(not bool(event.modifiers() & Qt.ShiftModifier))
                return True
        return super().eventFilter(obj, event)

    def _close(self) -> None:
        self.reset_feedback()
        self.hide()
        self.closed.emit()
