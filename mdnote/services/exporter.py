"""导出：HTML 文件、PDF（QWebEnginePage.printToPdf）、Pandoc 子进程。"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QEventLoop, QMarginsF, QSizeF, QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..editor.block_model import build_model, extract_headings
from ..services.markdown_engine import markdown_engine, pygments_css

PANDOC_FORMATS = {
    "docx": "docx",
    "epub": "epub",
    "latex": "latex",
    "odt": "odt",
}

_BASE_CSS = """
body { max-width: 860px; margin: 40px auto; font: 16px/1.7 -apple-system, 'Segoe UI', sans-serif; color: #24292f; }
h1,h2,h3 { line-height: 1.35; }
table { border-collapse: collapse; } th, td { border: 1px solid #d0d7de; padding: 6px 12px; }
"""


def build_standalone_html(text: str, include_toc: bool = False) -> str:
    engine = markdown_engine()
    body = engine.render(text)
    toc = ""
    if include_toc:
        items = "".join(
            f'<li style="margin-left:{(h.level - 1) * 12}px">{h.text}</li>'
            for h in extract_headings(build_model(text))
        )
        toc = f"<nav><h2>目录</h2><ul>{items}</ul></nav>"
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/>"
        f"<style>{_BASE_CSS}{pygments_css()}</style></head><body>{toc}{body}</body></html>"
    )


def export_html(path: str, text: str) -> None:
    Path(path).write_text(build_standalone_html(text), encoding="utf-8")


def export_pdf(page: QWebEnginePage, path: str) -> bool:
    layout = page.layout()
    layout.setPageSize(QSizeF(210, 297))  # A4 mm
    layout.setContentsMargins(QMarginsF(18, 18, 18, 18))
    ok = page.printToPdf(path, layout)
    return bool(ok)


def pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def pandoc_export(text: str, fmt: str) -> tuple[bool, str | None]:
    if not pandoc_available():
        return False, "未检测到 Pandoc"
    ext = PANDOC_FORMATS.get(fmt, fmt)
    try:
        proc = subprocess.run(
            ["pandoc", "-f", "markdown", "-t", ext, "-o", f"export-output.{ext}"],
            input=text,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if proc.returncode != 0:
        return False, proc.stderr
    return True, None


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def export_image(html: str, path: str, fmt: str = "PNG") -> bool:
    """离屏加载完整 HTML → 按内容高度调整 → 整页截图保存。

    会短暂显示一个离屏窗口（QWebEngine 需真正渲染才能抓取）。
    """
    tmp = Path(tempfile.gettempdir()) / "mdnote-capture.html"
    tmp.write_text(html, encoding="utf-8")

    view = QWebEngineView()
    view.resize(900, 800)
    load_loop = QEventLoop()
    view.loadFinished.connect(load_loop.quit)
    view.setUrl(QUrl.fromLocalFile(str(tmp)))
    view.show()
    load_loop.exec()

    result = {"h": 0}
    h_loop = QEventLoop()

    def on_height(h) -> None:
        result["h"] = int(h or 0)
        h_loop.quit()

    view.page().runJavaScript("document.body.scrollHeight", on_height)
    h_loop.exec()

    view.resize(900, max(400, result["h"] + 48))
    _wait(450)  # 等待重排与图片/图表渲染

    pixmap = view.grab()
    view.close()
    return bool(pixmap.save(path, fmt))
