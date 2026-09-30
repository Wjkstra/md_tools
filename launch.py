"""PyInstaller 入口：以绝对导入启动应用。

（不直接用 mdnote/__main__.py，因为打包后它没有父包上下文，相对导入会失败。）
"""

import sys

from mdnote.app import run


if __name__ == "__main__":
    sys.exit(run())
