"""状态栏：保存状态、字数统计、当前模式。"""

from PySide6.QtWidgets import QLabel, QWidget

from ..core.word_count import DocStats


class StatusBar(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(26)
        from PySide6.QtWidgets import QHBoxLayout

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        self._state = QLabel("● 已保存")
        self._stats = QLabel("")
        self._mode = QLabel("渲染后模式")
        layout.addWidget(self._state)
        layout.addStretch(1)
        layout.addWidget(self._stats)
        layout.addWidget(self._mode)

    def update_state(self, dirty: bool, mode: str, stats: DocStats, file_name: str) -> None:
        self._state.setText("○ 未保存" if dirty else "● 已保存")
        self._mode.setText("渲染后模式" if mode == "live" else "源码模式")
        self._stats.setText(
            f"{stats.words} 字 · {stats.chars} 字符 · {stats.lines} 行 · 约 {stats.reading_minutes} 分钟"
        )
        self.setToolTip(file_name)
