"""查找 / 替换小栏。"""

from PySide6.QtCore import Signal
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

    def open(self) -> None:
        self.show()
        self._find.setFocus()

    def _close(self) -> None:
        self.hide()
        self.closed.emit()
