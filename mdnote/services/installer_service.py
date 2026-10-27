"""Launch the verified Windows installer through the elevation-aware shell."""

import os
import subprocess
import sys
from pathlib import Path


def launch_installer(path: str, *, install_dir: str | Path | None = None) -> None:
    target = Path(path).resolve(strict=True)
    if not target.is_file():
        raise ValueError("安装包不是有效文件")
    if install_dir is None and getattr(sys, "frozen", False):
        install_dir = Path(sys.executable).resolve().parent
    parameters = None
    if install_dir is not None:
        destination = Path(install_dir).resolve(strict=True)
        if not destination.is_dir() or any(ch in str(destination) for ch in '\r\n"'):
            raise ValueError("已有安装目录无效")
        # NSIS consumes everything after /D= as the directory, including spaces.
        # It must be the LAST argument and must not be enclosed in quotes.
        parameters = "/D=" + str(destination)
    if os.name == "nt":
        import ctypes

        if target.suffix.lower() != ".exe":
            raise ValueError("安装包格式无效")
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(target), parameters, str(target.parent), 1
        )
        if result <= 32:
            raise OSError(f"安装程序启动取消或失败（系统代码 {result}）")
    else:
        subprocess.Popen([str(target)] + ([parameters] if parameters else []), start_new_session=True)
