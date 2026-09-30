"""侧边栏：文件树 / 大纲两个标签页。"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileSystemModel,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QTreeView,
    QWidget,
)


class Sidebar(QWidget):
    open_file_requested = Signal(str)
    jump_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(220)
        self._tabs = QTabWidget(self)
        from PySide6.QtWidgets import QVBoxLayout

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

        # 文件树
        self._model = QFileSystemModel()
        self._model.setRootPath("")
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        for col in range(1, 4):
            self._tree.hideColumn(col)
        self._tree.doubleClicked.connect(self._on_tree_double)
        self._tabs.addTab(self._tree, "文件")

        # 大纲
        self._outline = QListWidget()
        self._outline.itemClicked.connect(self._on_outline_click)
        self._tabs.addTab(self._outline, "大纲")

        self._folder: str | None = None

    def open_folder(self, folder: str) -> None:
        self._folder = folder
        idx = self._model.setRootPath(folder)
        self._tree.setRootIndex(idx)

    def _on_tree_double(self, idx) -> None:
        path = self._model.filePath(idx)
        if Path(path).is_file() and path.lower().endswith((".md", ".markdown", ".txt")):
            self.open_file_requested.emit(path)

    def set_headings(self, headings) -> None:
        self._outline.clear()
        for h in headings:
            item = QListWidgetItem("　" * (h.level - 1) + h.text)
            item.setData(Qt.UserRole, h.block_index)
            self._outline.addItem(item)

    def _on_outline_click(self, item: QListWidgetItem) -> None:
        self.jump_requested.emit(int(item.data(Qt.UserRole)))

    def show_tab(self, name: str) -> None:
        self._tabs.setCurrentIndex(0 if name == "files" else 1)
