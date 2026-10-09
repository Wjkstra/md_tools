"""Launch the verified Windows installer through the elevation-aware shell."""

import os
import subprocess
from pathlib import Path


def launch_installer(path: str) -> None:
    target = Path(path).resolve(strict=True)
    if not target.is_file():
        raise ValueError("安装包不是有效文件")
    if os.name == "nt":
        import ctypes

        if target.suffix.lower() != ".exe":
            raise ValueError("安装包格式无效")
        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(target), None, str(target.parent), 1
        )
        if result <= 32:
            raise OSError(f"安装程序启动取消或失败（系统代码 {result}）")
    else:
        subprocess.Popen([str(target)], start_new_session=True)
