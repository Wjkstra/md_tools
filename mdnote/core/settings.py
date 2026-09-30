"""JSON 设置服务：字段与 Electron 版 AppSettings 对齐。"""

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Callable, List

from ..config import settings_file


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
        known = {f.name for f in fields(AppSettings)}
        return AppSettings(**{k: v for k, v in data.items() if k in known})

    def save(self) -> None:
        self._path.write_text(
            json.dumps(asdict(self.current), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def patch(self, **kwargs) -> AppSettings:
        for k, v in kwargs.items():
            if hasattr(self.current, k):
                setattr(self.current, k, v)
        self.save()
        for cb in list(self._listeners):
            cb(self.current)
        return self.current

    def on_change(self, cb: Callable[[AppSettings], None]) -> None:
        self._listeners.append(cb)


_svc: SettingsService | None = None


def settings_service() -> SettingsService:
    global _svc
    if _svc is None:
        _svc = SettingsService()
    return _svc
