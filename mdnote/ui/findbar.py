"""查找 / 替换小栏。"""

from PySide6.QtCore import Signal, QEvent, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)


class FindBar(QWidget):
    find_next = Signal(str, bool)  # text, forward
    replace_one = Signal(str, str)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
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

        prev.clicked.connect(lambda: self.find_next.emit(self._find.text(), False))
        nxt.clicked.connect(lambda: self.find_next.emit(self._find.text(), True))
        rep.clicked.connect(
            lambda: self.replace_one.emit(self._find.text(), self._replace.text())
        )
        close.clicked.connect(self._close)

        for w in (self._find, self._replace, prev, nxt, rep, close):
            layout.addWidget(w)
            w.installEventFilter(self)

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
        self.hide()
        self.closed.emit()
