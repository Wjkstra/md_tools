"""原生对话框：提示 / 确认 / 输入 / 设置面板。"""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QWidget,
)

from ..core.settings import settings_service

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
