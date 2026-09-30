"""侧边栏：搜索 / 文件树 / 大纲三个标签页。"""

from pathlib import Path

from PySide6.QtCore import Qt, Signal, QEvent, QTimer
from PySide6.QtWidgets import (
    QFileSystemModel,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..services.search_service import start_search


class Sidebar(QWidget):
    open_file_requested = Signal(str)
    jump_requested = Signal(int)
    return_editor_requested = Signal()
    open_search_result = Signal(str, int)   # 文件路径, 行号

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(220)
        self._tabs = QTabWidget(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tabs)

        # 搜索
        search_pane = QWidget()
        search_layout = QVBoxLayout(search_pane)
        search_layout.setContentsMargins(6, 6, 6, 6)
        search_layout.setSpacing(4)
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("在当前文件夹中搜索，Enter 开始…")
        self._search_box.setClearButtonEnabled(True)
        self._search_status = QLabel("")
        self._search_status.setStyleSheet("color: gray;")
        self._search_results = QListWidget()
        search_layout.addWidget(self._search_box)
        search_layout.addWidget(self._search_status)
        search_layout.addWidget(self._search_results, 1)
        self._search_box.returnPressed.connect(self._run_search)
        self._search_results.itemActivated.connect(self._on_search_result)

        # 文件树
        self._model = QFileSystemModel()
        self._model.setRootPath("")
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        for col in range(1, 4):
            self._tree.hideColumn(col)
        self._tree.activated.connect(self._on_tree_double)
        self._tree.setAccessibleName("文件树，Enter 打开，Esc 返回编辑器")
        self._tabs.addTab(self._tree, "文件")

        # 大纲
        self._outline = QListWidget()
        self._outline.itemClicked.connect(self._on_outline_click)
        self._outline.itemActivated.connect(self._on_outline_click)
        self._outline.setAccessibleName("文档大纲，Enter 跳转，Esc 返回编辑器")
        self._tabs.addTab(self._outline, "大纲")

        # 搜索放在最后，保持 文件(0)/大纲(1) 索引稳定
        self._tabs.addTab(search_pane, "搜索")

        self._folder: str | None = None
        self._search_thread = None
        self._search_box.installEventFilter(self)
        self._tree.installEventFilter(self)
        self._outline.installEventFilter(self)
        self._search_results.installEventFilter(self)
        self._tabs.tabBar().installEventFilter(self)

    def open_folder(self, folder: str) -> None:
        self._folder = folder
        idx = self._model.setRootPath(folder)
        self._tree.setRootIndex(idx)

    def _on_tree_double(self, idx) -> None:
        path = self._model.filePath(idx)
        if Path(path).is_file() and path.lower().endswith((".md", ".markdown", ".txt")):
            self.open_file_requested.emit(path)

    def set_headings(self, headings) -> None:
        entries = [("　" * (h.level - 1) + h.text, h.block_index) for h in headings]
        existing = [(self._outline.item(i).text(), self._outline.item(i).data(Qt.UserRole))
                    for i in range(self._outline.count())]
        if entries == existing:
            return
        row = self._outline.currentRow()
        self._outline.clear()
        for text, block_index in entries:
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, block_index)
            self._outline.addItem(item)
        if entries:
            self._outline.setCurrentRow(max(0, min(row, len(entries) - 1)))

    def _on_outline_click(self, item: QListWidgetItem) -> None:
        self.jump_requested.emit(int(item.data(Qt.UserRole)))

    # ---------------- 全文搜索 ----------------

    def _run_search(self) -> None:
        query = self._search_box.text().strip()
        if not query:
            return
        if not self._folder:
            self._search_status.setText("请先用「打开文件夹」选择搜索范围。")
            return
        self._search_results.clear()
        self._search_status.setText("搜索中…")
        start_search(
            self, self._folder, query, self._on_search_done
        )

    def _on_search_done(self, payload) -> None:
        self._search_results.clear()
        for hit in payload:
            path = Path(hit["path"])
            if hit["kind"] == "name":
                label = f"📄 {path.name}"
                hint = str(path)
                line = 0
            else:
                line = hit["line"]
                label = f"行 {line}: {hit['text']}"
                hint = str(path)
            item = QListWidgetItem(label)
            item.setToolTip(hint)
            item.setData(Qt.UserRole, (hit["path"], line))
            self._search_results.addItem(item)
        count = len(payload)
        scope = Path(self._folder).name if self._folder else ""
        self._search_status.setText(f"在「{scope}」中找到 {count} 项")

    def _on_search_result(self, item: QListWidgetItem) -> None:
        path, line = item.data(Qt.UserRole)
        self.open_search_result.emit(path, line)

    def focus_search(self, query: str = "") -> None:
        self._tabs.setCurrentWidget(self._search_box.parentWidget())
        if query:
            self._search_box.setText(query)
        self._search_box.setFocus()
        self._search_box.selectAll()

    def show_tab(self, name: str) -> None:
        mapping = {"files": 0, "outline": 1, "search": 2}
        self._tabs.setCurrentIndex(mapping.get(name, 0))

    def focus_current(self) -> None:
        self._tabs.currentWidget().setFocus()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.return_editor_requested.emit()
            return True
        return super().eventFilter(obj, event)
