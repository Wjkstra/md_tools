"""Native application colors aligned with the document's built-in themes."""
import sys
from pathlib import Path
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from ..editor.md_highlighter import editor_colors_for, palette_for


def configure_ui_font(window) -> None:
    # Offscreen Windows sessions may not enumerate system fonts.
    if sys.platform == "win32" and not QFontDatabase.families():
        font_file = Path("C:/Windows/Fonts/msyh.ttc")
        if font_file.is_file():
            QFontDatabase.addApplicationFont(str(font_file))
    window.setFont(QFont(["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                          "Noto Sans CJK SC", "Segoe UI", "sans-serif"], 10))


def apply_shell_theme(window, theme: str) -> None:
    bg, fg = editor_colors_for(theme)
    semantic = palette_for(theme)
    accent = semantic["link"]
    muted = semantic["quote"]
    dark = QColor(bg).lightness() < 128
    panel = QColor(bg).lighter(130).name() if dark else QColor(bg).darker(104).name()
    border = QColor(bg).lighter(180).name() if dark else QColor(bg).darker(118).name()
    if bg == "#000000":
        panel, border = "#12141a", "#2b3038"
    palette = window.palette()
    for role, color in (
        (QPalette.Window, panel), (QPalette.WindowText, fg),
        (QPalette.Base, bg), (QPalette.AlternateBase, panel),
        (QPalette.Text, fg), (QPalette.Button, panel), (QPalette.ButtonText, fg),
        (QPalette.Highlight, accent), (QPalette.HighlightedText, bg),
        (QPalette.ToolTipBase, panel), (QPalette.ToolTipText, fg),
    ):
        palette.setColor(role, QColor(color))
    window.setPalette(palette)
    window.setStyleSheet(f"""
        QMainWindow, QDialog, QWidget#shellCenter, QWidget#findBar,
        QWidget#statusBar {{ background: {panel}; color: {fg}; }}
        QMenuBar, QMenu {{ background: {panel}; color: {fg}; }}
        QMenu {{ border: 1px solid {border}; padding: 4px; }}
        QMenu::item {{ padding: 6px 24px; }}
        QMenu::item:selected, QMenuBar::item:selected {{ background: {accent}; color: {bg}; }}
        QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
        QTabWidget::pane {{ border: 0; background: {bg}; }}
        QTabBar::tab {{ background: {panel}; color: {muted}; padding: 9px 12px;
                        border-bottom: 2px solid transparent; min-width: 48px; }}
        QTabBar::tab:selected {{ background: {bg}; color: {fg}; border-bottom-color: {accent}; }}
        QTabBar::tab:hover {{ color: {fg}; }}
        QTreeView, QListWidget {{ background: {bg}; color: {fg}; border: 0;
                                  outline: 0; selection-background-color: {accent};
                                  selection-color: {bg}; }}
        QTreeView::item, QListWidget::item {{ padding: 5px 4px; }}
        QLineEdit, QSpinBox, QComboBox {{ background: {bg}; color: {fg};
            border: 1px solid {border}; border-radius: 4px; padding: 5px 7px;
            selection-background-color: {accent}; selection-color: {bg}; }}
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {accent}; }}
        QPushButton, QToolButton {{ background: {panel}; color: {fg}; border: 1px solid {border};
                                   border-radius: 4px; padding: 5px 9px; }}
        QPushButton:hover, QToolButton:hover {{ border-color: {accent}; }}
        QPushButton:focus, QToolButton:focus {{ border-color: {accent}; }}
        QPushButton:disabled, QToolButton:disabled {{ color: {muted}; }}
        QSplitter::handle {{ background: {border}; width: 1px; }}
        QScrollBar:vertical {{ background: {panel}; width: 10px; margin: 0; }}
        QScrollBar:horizontal {{ background: {panel}; height: 10px; margin: 0; }}
        QScrollBar::handle {{ background: {border}; border-radius: 4px; min-width: 20px; min-height: 20px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
        QLabel, QCheckBox, QRadioButton {{ color: {fg}; }}
        QLabel#secondaryText {{ color: {muted}; }}
        QWidget#statusBar {{ border-top: 1px solid {border}; }}
        QToolTip {{ color: {fg}; background: {panel}; border: 1px solid {border}; padding: 5px; }}
    """)
