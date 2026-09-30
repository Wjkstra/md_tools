"""原生对话框：提示 / 确认 / 输入 / 设置面板。"""

from PySide6.QtCore import QEvent, Qt

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from ..core.settings import settings_service
from ..services.plugin_loader import discover, plugins_dir


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

# 主题 id → 显示名（id 同时用于 CSS data-theme 与源码高亮调色板）
THEME_CHOICES = [
    ("light", "浅色"),
    ("dark", "深色"),
    ("solarized", "护眼（Solarized）"),
    ("sepia", "羊皮纸"),
    ("night", "深夜（OLED）"),
    ("monokai", "Monokai"),
    ("dracula", "Dracula"),
]
_THEMES = [name for name, _label in THEME_CHOICES]


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
        for theme_id, label in THEME_CHOICES:
            self._theme.addItem(label, theme_id)
        # 选中当前主题（按保存的 id；未知主题默认第一项）
        current_theme_index = next(
            (i for i, (tid, _) in enumerate(THEME_CHOICES)
             if tid in s.theme.lower()), 0
        )
        self._theme.setCurrentIndex(current_theme_index)

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

        # 插件：列出已发现的扩展供勾选
        self._plugins = QListWidget()
        self._plugins.setMinimumHeight(120)
        known = {p.name for p in discover()}
        for name in sorted(set(s.enabled_plugins) | known):
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in s.enabled_plugins else Qt.Unchecked)
            if name not in known:
                item.setText(f"{name}（未找到）")
                item.setForeground(Qt.gray)
            self._plugins.addItem(item)
        plugin_hint = QLabel(f"插件目录：{plugins_dir()}\n插件为 Python 代码，请只启用信任来源。")
        plugin_hint.setWordWrap(True)
        plugin_hint.setStyleSheet("color: gray;")

        form.addRow("主题", self._theme)
        form.addRow("字号", self._font)
        form.addRow("", self._autosave)
        form.addRow("", self._mermaid)
        form.addRow("", self._linenos)
        form.addRow("图片目录", self._imgfolder)
        form.addRow("插件", self._plugins)
        form.addRow("", plugin_hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self) -> None:
        enabled = [
            self._plugins.item(i).text().replace("（未找到）", "")
            for i in range(self._plugins.count())
            if self._plugins.item(i).checkState() == Qt.Checked
        ]
        settings_service().patch(
            theme=self._theme.currentData(),
            font_size=self._font.value(),
            auto_save=self._autosave.isChecked(),
            mermaid=self._mermaid.isChecked(),
            code_line_numbers=self._linenos.isChecked(),
            image_folder=self._imgfolder.text().strip() or "assets",
            enabled_plugins=enabled,
        )
        super().accept()
