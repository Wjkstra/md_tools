"""状态栏：保存状态、字数统计、当前模式。"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QToolButton, QWidget

from ..core.word_count import DocStats


class StatusBar(QWidget):
    mode_requested = Signal()
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("statusBar")
        self.setMinimumHeight(34)
        from PySide6.QtWidgets import QHBoxLayout

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        self._state = QLabel("● 已保存")
        self._stats = QLabel("")
        self._mode = QToolButton()
        self._mode.setText("渲染后模式")
        self._mode.setToolTip("切换源码 / 渲染后模式（Ctrl+/）")
        self._mode.setAccessibleName("切换编辑模式")
        self._mode.clicked.connect(self.mode_requested.emit)
        self._stats.setObjectName("secondaryText")
        layout.addWidget(self._state)
        layout.addStretch(1)
        layout.addWidget(self._stats)
        layout.addWidget(self._mode)

    def show_message(self, message: str) -> None:
        self._state.setText(message)

    def update_state(self, dirty: bool, mode: str, stats: DocStats, file_name: str,
                     has_path: bool = True) -> None:
        self._state.setText("○ 未保存" if dirty else ("● 已保存" if has_path else "未命名"))
        self._mode.setText("渲染后模式" if mode == "live" else "源码模式")
        self._stats.setText(
            f"{stats.words} 字 · {stats.chars} 字符 · {stats.lines} 行 · 约 {stats.reading_minutes} 分钟"
        )
        self.setToolTip(file_name)
