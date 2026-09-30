"""原生对话框：提示 / 确认 / 输入 / 设置面板。"""

from PySide6.QtCore import QEvent, Qt

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from ..core.settings import settings_service


class CommandPalette(QDialog):
    """All menu actions remain reachable with search, arrows and Enter."""

    def __init__(self, parent, commands) -> None:
        super().__init__(parent)
        self.setWindowTitle("命令面板")
        self.resize(620, 440)
        self.commands = commands
        self.chosen = None
        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("输入命令名称，↑↓ 选择，Enter 执行，Esc 取消")
        self.search.setAccessibleName("搜索命令")
        self.results = QListWidget()
        self.results.setAccessibleName("可用命令")
        layout.addWidget(self.search)
        layout.addWidget(self.results)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._choose)
        self.results.itemActivated.connect(lambda _item: self._choose())
        self.search.installEventFilter(self)
        self._filter("")
        self.search.setFocus()

    def _filter(self, query: str) -> None:
        self.results.clear()
        terms = query.casefold().split()
        for title, action in self.commands:
            if not action.isEnabled() or not all(term in title.casefold() for term in terms):
                continue
            shortcut = action.shortcut().toString()
            item = QListWidgetItem(title + (f"    {shortcut}" if shortcut else ""))
            item.setData(Qt.UserRole, action)
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _choose(self) -> None:
        item = self.results.currentItem()
        if item:
            self.chosen = item.data(Qt.UserRole)
            self.accept()

    def eventFilter(self, obj, event):
        if obj is self.search and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Up, Qt.Key_Down):
            step = -1 if event.key() == Qt.Key_Up else 1
            self.results.setCurrentRow(max(0, min(self.results.count() - 1, self.results.currentRow() + step)))
            return True
        return super().eventFilter(obj, event)

_THEMES = [
    "github-light",
    "github-dark",
    "monokai",
    "dracula",
    "night",
]


def alert(parent: QWidget, message: str) -> None:
    QMessageBox.information(parent, "MdNote", message)


def confirm(parent: QWidget, message: str) -> bool:
    return (
        QMessageBox.question(
            parent,
            "MdNote",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        == QMessageBox.Yes
    )


def prompt(parent: QWidget, message: str, default: str = "") -> str | None:
    text, ok = QInputDialog.getText(parent, "MdNote", message, text=default)
    return text if ok else None


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        svc = settings_service()
        s = svc.current

        form = QFormLayout(self)

        self._theme = QComboBox()
        self._theme.addItems(_THEMES)
        self._theme.setCurrentText(s.theme)

        self._font = QSpinBox()
        self._font.setRange(12, 28)
        self._font.setValue(s.font_size)

        self._autosave = QCheckBox("停顿 1 秒自动保存")
        self._autosave.setChecked(s.auto_save)

        self._mermaid = QCheckBox("启用 Mermaid 图表")
        self._mermaid.setChecked(s.mermaid)

        self._linenos = QCheckBox("代码块显示行号")
        self._linenos.setChecked(s.code_line_numbers)

        self._imgfolder = QLineEdit(s.image_folder)

        form.addRow("主题", self._theme)
        form.addRow("字号", self._font)
        form.addRow("", self._autosave)
        form.addRow("", self._mermaid)
        form.addRow("", self._linenos)
        form.addRow("图片目录", self._imgfolder)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self) -> None:
        settings_service().patch(
            theme=self._theme.currentText(),
            font_size=self._font.value(),
            auto_save=self._autosave.isChecked(),
            mermaid=self._mermaid.isChecked(),
            code_line_numbers=self._linenos.isChecked(),
            image_folder=self._imgfolder.text().strip() or "assets",
        )
        super().accept()
