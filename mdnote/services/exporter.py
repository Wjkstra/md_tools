"""Sanitized, self-contained exports with asynchronous rendering and Pandoc jobs."""

import base64
import json
import mimetypes
import os
import re
import shutil
import tempfile
from functools import lru_cache
from html import escape
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal, Qt, QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from .. import config
from ..core.file_io import atomic_write_text
from ..editor.block_model import build_model, extract_headings
from .html_service import safe_html
from .markdown_engine import markdown_engine, pygments_css

PANDOC_FORMATS = {"docx": "docx", "epub": "epub", "latex": "latex", "odt": "odt"}
_BASE_CSS = """
body { max-width: 860px; margin: 40px auto; font: 16px/1.7 'Segoe UI',sans-serif; color: #24292f; }
h1,h2,h3 { line-height: 1.35; } img { max-width: 100%; }
table { border-collapse: collapse; } th,td { border: 1px solid #d0d7de; padding: 6px 12px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; } .mermaid { text-align: center; }
@media print { body { margin: 0; max-width: none; } img,svg { max-width: 100%; } }
"""

# Executed only after authored HTML has been sanitized. Completion includes images,
# fonts, formulas and asynchronous Mermaid; jobs also impose a native deadline.
_MEDIA_SCRIPT = r"""
window.__mdnoteExportState = {done: false, error: ''};
(async () => {
  try {
    if (window.katex) {
      const pattern = /(\$\$[^$]+\$\$|\$[^$\n]+\$)/;
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
        acceptNode(n) {
          return !n.parentElement.closest('code,pre,script,style,.mermaid') && pattern.test(n.nodeValue)
            ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
        }
      });
      const targets = []; while (walker.nextNode()) targets.push(walker.currentNode);
      for (const node of targets) {
        const fragment = document.createDocumentFragment();
        for (const part of node.nodeValue.split(pattern)) {
          const display = /^\$\$([^$]+)\$\$$/.exec(part), inline = /^\$([^$\n]+)\$$/.exec(part);
          if (display || inline) {
            const span = document.createElement('span');
            span.innerHTML = katex.renderToString((display || inline)[1], {displayMode: !!display, throwOnError: false});
            fragment.appendChild(span);
          } else fragment.appendChild(document.createTextNode(part));
        }
        node.replaceWith(fragment);
      }
    }
    const diagrams = [];
    for (const code of document.querySelectorAll('code.language-mermaid')) {
      const host = document.createElement('div'); host.className = 'mermaid';
      host.textContent = code.textContent; (code.closest('.codehilite') || code.closest('pre') || code).replaceWith(host);
      diagrams.push(host);
    }
    if (diagrams.length && window.mermaid) {
      mermaid.initialize({startOnLoad: false, securityLevel: 'strict', theme: 'neutral'});
      await mermaid.run({nodes: diagrams});
    }
    const waitImage = (image) => {
      if (image.naturalWidth) return Promise.resolve();
      // complete && naturalWidth 0 can mean decode is still pending in a busy
      // renderer; events distinguish success from failure, and polling covers an
      // event that fired before these listeners were attached.
      return new Promise((resolve, reject) => {
        const failTimer = setTimeout(fail, 15000);
        const poll = setInterval(check, 50);
        function cleanup() {
          clearTimeout(failTimer); clearInterval(poll);
          image.removeEventListener("load", ok);
          image.removeEventListener("error", fail);
        }
        function ok() { cleanup(); resolve(); }
        function fail() { cleanup(); reject(new Error("图片无法加载")); }
        function check() { if (image.naturalWidth) ok(); }
        image.addEventListener("load", ok, {once:true});
        image.addEventListener("error", fail, {once:true});
      });
    };
    await Promise.all(Array.from(document.images, waitImage));
    if (document.fonts) await document.fonts.ready;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  } catch (error) { window.__mdnoteExportState.error = String(error.message || error); }
  window.__mdnoteExportState.done = true;
})();
"""


@lru_cache(maxsize=4)
def _offline_asset(relative: str) -> str:
    source = config.web_dir() / "vendor" / relative
    text = source.read_text(encoding="utf-8")
    if source.suffix == ".css":
        def embed_font(match):
            name = match.group(1).strip('"\'')
            asset = (source.parent / name).resolve()
            mime = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            return "url(data:" + mime + ";base64," + base64.b64encode(asset.read_bytes()).decode("ascii") + ")"
        text = re.sub(r"url\(([^)]+)\)", embed_font, text)
    return text


def _script(content: str) -> str:
    # Prevent trusted library literals from terminating the element. Only
    # "</script" closes a script element; "</body"/"</head" inside strings are
    # end tags with other names and stay literal, so they must not be escaped
    # (a blanket "</letter" escape would corrupt regexes such as /</g).
    return "<script>" + content.replace("</script", "<\\/script") + "</script>"


# Injected into the capture document only (never into exported artifacts): links
# are visual content, and no authored navigation may leave the local page.
_CAPTURE_GUARD_JS = r"""
window.__mdnoteCaptureGuarded = true;
document.querySelectorAll('a[href]').forEach(a=>a.removeAttribute('href'));
document.addEventListener('click', function(e){
  if (e.target.closest && e.target.closest('a')) e.preventDefault();
}, true);
"""


def build_standalone_html(text: str, include_toc: bool = False,
                          doc_base: str | None = None) -> str:
    """Sanitize authored markup; embed local images and needed offline libraries."""
    body = safe_html(markdown_engine().render(text), doc_base, embed_images=True)
    toc = ""
    if include_toc:
        items = "".join(f'<li style="margin-left:{(h.level-1)*12}px">{escape(h.text)}</li>'
                        for h in extract_headings(build_model(text)))
        toc = f"<nav><h2>目录</h2><ul>{items}</ul></nav>"
    assets = ""
    css = (_BASE_CSS + (config.web_dir() / "typography.css").read_text(encoding="utf-8")
           + pygments_css())
    if "$" in text:
        css += _offline_asset("katex/katex.min.css")
        assets += _script(_offline_asset("katex/katex.min.js"))
    if 'language-mermaid' in body:
        assets += _script(_offline_asset("mermaid/mermaid.min.js"))
    csp = ("default-src 'none'; img-src data: file: http: https:; font-src data:; "
           "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
           "base-uri 'none'; connect-src 'none'")
    return ("<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'/>"
            f'<meta http-equiv="Content-Security-Policy" content="{escape(csp, quote=True)}">'
            f'<style>{css}</style></head><body>{toc}<div class="md-document">{body}</div>'
            f"{assets}{_script(_MEDIA_SCRIPT)}</body></html>")


def export_html(path: str, text: str, doc_base: str | None = None) -> None:
    atomic_write_text(path, build_standalone_html(text, doc_base=doc_base))



def _atomic_output(path: str, writer) -> None:
    """Keep an existing export intact if rendering or saving the replacement fails."""
    target = Path(path).resolve()
    fd, name = tempfile.mkstemp(prefix=".mdnote-export-", suffix=target.suffix, dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        if writer(temporary) is False:
            raise OSError("无法写入导出文件")
        with temporary.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        if target.exists():
            os.chmod(temporary, target.stat().st_mode)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


# Cleanup closures still holding a TemporaryDirectory after Windows sharing
# violations; module-level so retries outlive the finished export job.
_PENDING_TEMP_CLEANUPS: set = set()


def _retry_tempdir_cleanup(temp_dir, attempts: int = 12, delay_ms: int = 250) -> None:
    """Delete a capture temp directory after Chromium releases its files.

    On Windows the rendered document.html can stay locked right after
    deleteLater(). Retry briefly instead of letting the error swallow the
    finished signal; after the last attempt leave the (empty) directory for
    the OS temp cleanup rather than raising into Qt.
    """
    def attempt(remaining: int) -> None:
        try:
            temp_dir.cleanup()
            _PENDING_TEMP_CLEANUPS.discard(handle)
        except OSError:
            remaining -= 1
            if remaining > 0:
                QTimer.singleShot(delay_ms, lambda: attempt(remaining))
            else:
                _PENDING_TEMP_CLEANUPS.discard(handle)
    handle = (object(), attempt)
    _PENDING_TEMP_CLEANUPS.add(handle)
    QTimer.singleShot(0, lambda: attempt(attempts))


class RenderExportJob(QObject):
    """Own a complete export document until render/write completion or timeout."""
    finished = Signal(bool, str)

    def __init__(self, html: str, path: str, fmt: str, parent=None,
                 timeout_ms: int = 20000) -> None:
        super().__init__(parent)
        self._html, self._path, self._fmt = html, path, fmt.upper()
        self._done = False
        self._main_loaded = False
        self._render_started = False
        self._view = None
        self._temporary = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._finish(False, "导出超时，请检查图片或图表"))
        self._poll = QTimer(self)
        self._poll.setInterval(50)
        self._poll.timeout.connect(self._check_ready)
        self._timeout_ms = max(1, timeout_ms)
        QTimer.singleShot(0, self, self._start)

    def _start(self) -> None:
        if self._done:
            return
        try:
            self._temporary = tempfile.TemporaryDirectory(prefix="mdnote-export-")
            source = Path(self._temporary.name) / "document.html"
            guard = _script(_CAPTURE_GUARD_JS)
            # The real document body is the LAST "</body>"; earlier occurrences
            # live inside the inlined Mermaid source and must not be touched.
            index = self._html.lower().rfind("</body>")
            if index >= 0:
                document_html = self._html[:index] + guard + self._html[index:]
            else:
                document_html = self._html + guard
            source.write_text(document_html, encoding="utf-8")
            self._view = QWebEngineView()
            self._view.setAttribute(Qt.WA_DontShowOnScreen, True)
            self._view.resize(900, 800)
            # The capture page must stay on the local sanitized document.
            self._view.page().navigationRequested.connect(self._on_navigation)
            self._view.page().loadFinished.connect(self._loaded)
            self._timer.start(self._timeout_ms)
            self._view.setUrl(QUrl.fromLocalFile(str(source)))
            self._view.show()
        except (OSError, ValueError) as exc:
            self._finish(False, str(exc))

    def _loaded(self, ok: bool) -> None:
        if self._done or self._main_loaded:
            # Rejected link/redirect navigations still emit loadFinished(false);
            # the already-loaded capture document must not be torn down for them.
            return
        self._main_loaded = True
        if not ok:
            self._finish(False, "导出页面加载失败")
        else:
            self._poll.start()
            self._check_ready()

    def _on_navigation(self, request) -> None:
        # Authored content has already been sanitized; this keeps a link click or
        # redirect from ever leaving the controlled local capture page. The only
        # expected navigations are our own setUrl and framework auxiliary loads.
        navigation = request.navigationType()
        enum_type = type(navigation)
        # PySide6 wraps this scoped enum in a fresh class per access and (in 6.11)
        # renamed the members, so the deprecated NavigationType* aliases compare
        # unequal. Resolve members from the runtime enum class itself.
        def member(new_name: str, legacy_name: str):
            return getattr(enum_type, new_name, None) or getattr(enum_type, legacy_name, None)
        allowed = (member("TypedNavigation", "NavigationTypeTyped"),
                   member("OtherNavigation", "NavigationTypeOther"))
        value = getattr(navigation, "value", navigation)
        allowed_values = tuple(getattr(item, "value", item) for item in allowed)
        if navigation in allowed or value in allowed_values:
            request.accept()
        else:
            request.reject()

    def _check_ready(self) -> None:
        if self._done or self._view is None:
            return
        self._view.page().runJavaScript(
            "JSON.stringify(window.__mdnoteExportState || {done:false})", self._on_ready)

    def _on_ready(self, raw) -> None:
        if self._done or self._render_started or not raw:
            return
        try:
            state = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not state.get("done"):
            return
        self._poll.stop()
        self._render_started = True
        if state.get("error"):
            self._finish(False, "导出资源加载失败：" + state["error"])
            return
        if self._fmt == "PDF":
            layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait,
                                 QMarginsF(18, 18, 18, 18), QPageLayout.Millimeter)
            self._view.page().printToPdf(self._on_pdf, layout)
        else:
            self._view.page().runJavaScript(
                "Math.ceil(Math.max(document.body.scrollHeight,document.documentElement.scrollHeight))",
                self._on_height)

    def _on_pdf(self, data) -> None:
        if self._done:
            return
        try:
            content = bytes(data)
            if not content.startswith(b"%PDF"):
                self._finish(False, "PDF 生成失败")
                return
            _atomic_output(self._path, lambda target: target.write_bytes(content))
        except OSError as exc:
            self._finish(False, "PDF 保存失败：" + str(exc))
            return
        self._finish(True, self._path)

    def _on_height(self, height) -> None:
        if self._done:
            return
        try:
            height = max(400, int(height or 0) + 48)
        except (TypeError, ValueError):
            self._finish(False, "无法确定导出图片尺寸")
            return
        # Prevent exceeding Qt/Chromium texture limits or silently cropping output.
        if height > 16000:
            self._finish(False, "文档过长，无法导出为单张图片；请使用 PDF")
            return
        self._view.resize(900, height)
        QTimer.singleShot(150, self, self._capture)

    def _capture(self) -> None:
        if self._done:
            return
        try:
            pixmap = self._view.grab()
            _atomic_output(self._path, lambda target: pixmap.save(str(target), self._fmt))
        except OSError as exc:
            self._finish(False, "图片保存失败：" + str(exc))
            return
        self._finish(True, self._path)

    def cancel(self) -> None:
        self._finish(False, "已取消导出")

    def _finish(self, ok: bool, message: str) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self._poll.stop()
        # Notify terminal state exactly once and BEFORE releasing the page /
        # temp directory: a sharing violation during cleanup must never swallow
        # the signal (the job set in the main window would leak otherwise).
        view, self._view = self._view, None
        temporary, self._temporary = self._temporary, None
        self.finished.emit(ok, message)
        if view is not None:
            view.close()
            view.deleteLater()
        if temporary is not None:
            _retry_tempdir_cleanup(temporary)


def export_pdf(text: str, path: str, *, doc_base: str | None = None,
               parent=None, timeout_ms: int = 20000) -> RenderExportJob:
    """Return a job; finished(True, path) means the complete PDF was written."""
    return RenderExportJob(build_standalone_html(text, doc_base=doc_base), path,
                           "PDF", parent, timeout_ms)


def export_image(html: str, path: str, fmt: str = "PNG", *, parent=None,
                 timeout_ms: int = 20000) -> RenderExportJob:
    return RenderExportJob(html, path, fmt, parent, timeout_ms)


def pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


class PandocExportJob(QObject):
    finished = Signal(bool, str)

    def __init__(self, text: str, fmt: str, path: str, doc_base: str | None = None,
                 parent=None, timeout_ms: int = 120000) -> None:
        super().__init__(parent)
        self._text, self._fmt, self._path, self._base = text, fmt, path, doc_base
        self._staged_path = None
        self._done = False
        self._process = QProcess(self)
        self._process.finished.connect(self._completed)
        self._process.errorOccurred.connect(self._error)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self._stop("Pandoc 导出超时"))
        self._timeout_ms = timeout_ms
        QTimer.singleShot(0, self, self._start)

    def _start(self) -> None:
        if self._done:
            return
        executable = shutil.which("pandoc")
        if executable is None:
            self._finish(False, "未检测到 Pandoc")
            return
        if self._fmt not in PANDOC_FORMATS:
            self._finish(False, "不支持的导出格式")
            return
        try:
            target = Path(self._path).resolve()
            fd, name = tempfile.mkstemp(prefix=".mdnote-pandoc-", suffix=target.suffix, dir=target.parent)
            os.close(fd)
            self._staged_path = Path(name)
        except OSError as exc:
            self._finish(False, "无法创建导出文件：" + str(exc))
            return
        arguments = ["-f", "markdown", "-t", PANDOC_FORMATS[self._fmt],
                     "-o", str(self._staged_path)]
        if self._base:
            arguments.extend(["--resource-path", str(Path(self._base).resolve())])
            self._process.setWorkingDirectory(str(Path(self._base).resolve()))
        self._process.started.connect(self._write_input)
        self._timer.start(max(1, self._timeout_ms))
        self._process.start(executable, arguments)

    def _write_input(self) -> None:
        if not self._done:
            self._process.write(self._text.encode("utf-8"))
            self._process.closeWriteChannel()

    def _error(self, error) -> None:
        if error == QProcess.FailedToStart:
            self._finish(False, "无法启动 Pandoc：" + self._process.errorString())

    def _completed(self, code: int, status) -> None:
        if self._done:
            return
        if getattr(self, "_cancel_message", None):
            self._finish(False, self._cancel_message)
            return
        error = bytes(self._process.readAllStandardError()).decode("utf-8", errors="replace").strip()
        if status != QProcess.NormalExit or code != 0:
            self._finish(False, error or "Pandoc 导出失败")
        elif self._staged_path is None or not self._staged_path.is_file() or not self._staged_path.stat().st_size:
            self._finish(False, "Pandoc 未生成目标文件")
        else:
            try:
                os.replace(self._staged_path, Path(self._path).resolve())
            except OSError as exc:
                self._finish(False, "导出文件保存失败：" + str(exc))
                return
            self._finish(True, self._path)

    def _stop(self, message: str) -> None:
        if self._done:
            return
        self._cancel_message = message
        if self._process.state() == QProcess.NotRunning:
            self._finish(False, message)
        else:
            self._process.kill()

    def cancel(self) -> None:
        self._stop("已取消导出")

    def _finish(self, ok: bool, message: str) -> None:
        if self._done:
            return
        self._done = True
        self._timer.stop()
        if self._staged_path is not None:
            self._staged_path.unlink(missing_ok=True)
            self._staged_path = None
        self.finished.emit(ok, message)


def pandoc_export(text: str, fmt: str, path: str, *, doc_base: str | None = None,
                  parent=None, timeout_ms: int = 120000) -> PandocExportJob:
    return PandocExportJob(text, fmt, path, doc_base, parent, timeout_ms)
