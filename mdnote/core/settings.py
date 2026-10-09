"""JSON 设置服务：字段与 Electron 版 AppSettings 对齐。"""

import json
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Callable, List

from ..config import settings_file
from .file_io import atomic_write_text


@dataclass
class AppSettings:
    theme: str = "github-light"
    font_size: int = 16
    tab_size: int = 2
    code_line_numbers: bool = True
    mermaid: bool = True
    smart_punctuation: bool = False
    focus_mode: bool = False
    typewriter_mode: bool = False
    auto_bracket: bool = True
    image_folder: str = "assets"
    image_path_type: str = "relative"
    highlight_mark: bool = True
    auto_save: bool = False
    sidebar_visible: bool = False
    sidebar_tab: str = "files"
    last_file: str | None = None
    last_folder: str | None = None
    enabled_plugins: List[str] = field(default_factory=list)
    recent_files: List[str] = field(default_factory=list)
    recent_folders: List[str] = field(default_factory=list)
    update_url: str = ""        # 自定义更新清单地址（留空用内置默认）
    auto_check_updates: bool = True


class SettingsService:
    def __init__(self) -> None:
        self._path: Path = settings_file()
        self.current = self._load()
        self._listeners: list[Callable[[AppSettings], None]] = []

    def _load(self) -> AppSettings:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return AppSettings()
        if not isinstance(data, dict):
            return AppSettings()
        defaults = AppSettings()
        known = {f.name for f in fields(AppSettings)}
        values = {}
        for key, value in data.items():
            if key not in known:
                continue
            default = getattr(defaults, key)
            if isinstance(default, bool):
                valid = type(value) is bool
            elif isinstance(default, int):
                valid = type(value) is int
            elif isinstance(default, list):
                valid = isinstance(value, list)
                if valid:
                    value = [item for item in value if isinstance(item, str) and item and "\0" not in item]
            elif default is None:
                valid = value is None or (isinstance(value, str) and "\0" not in value)
            else:
                valid = isinstance(value, str) and "\0" not in value
            if valid:
                values[key] = value
        for key, minimum, maximum in (("font_size", 12, 28), ("tab_size", 1, 8)):
            if key in values:
                values[key] = max(minimum, min(maximum, values[key]))
        return AppSettings(**values)

    def _write(self, settings: AppSettings) -> None:
        atomic_write_text(self._path,
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        )

    def save(self) -> None:
        self._write(self.current)

    def patch(self, **kwargs) -> AppSettings:
        # Publish only persisted values. Failed writes leave the previous object,
        # disk contents and observers untouched.
        known = {item.name for item in fields(AppSettings)}
        updates = {key: list(value) if isinstance(value, list) else value
                   for key, value in kwargs.items() if key in known}
        candidate = replace(self.current, **updates)
        self._write(candidate)
        self.current = candidate
        for cb in list(self._listeners):
            cb(candidate)
        return candidate

    def on_change(self, cb: Callable[[AppSettings], None]) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)

    def off_change(self, cb: Callable[[AppSettings], None]) -> None:
        if cb in self._listeners:
            self._listeners.remove(cb)


_svc: SettingsService | None = None


def settings_service() -> SettingsService:
    global _svc
    if _svc is None:
        _svc = SettingsService()
    return _svc
