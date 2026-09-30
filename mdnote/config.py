"""应用路径：用户数据目录、Web 资源目录。"""

import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def app_data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
    if not base:
        base = str(Path.home() / ".mdnote_py")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def custom_css_file() -> Path:
    return app_data_dir() / "custom.css"


def _base_dir() -> Path:
    # PyInstaller 打包后资源解压到 sys._MEIPASS
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ""))
    return Path(__file__).resolve().parent.parent


def web_dir() -> Path:
    return _base_dir() / "mdnote" / "editor" / "web"


def icon_file() -> Path:
    return _base_dir() / "mdnote" / "resources" / "icon.ico"
