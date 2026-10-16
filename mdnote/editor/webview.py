"""渲染后（实时）模式：QWebEngineView + QWebChannel 桥 + LiveDocument。

连续表面模型：整篇文档渲染成一个 contenteditable 元素（见 services/surface.py
与 web/app.js）。Python 端只持有规范文本与块模型，结构编辑都在页面原生完成，
页面通过 updateSurfaceText 把编辑后的 Markdown 推回来。
"""

import json
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

from .. import config as app_config
from ..core.settings import settings_service
from ..services.image_service import import_image
from .block_model import build_model

_WEB_DIR = app_config.web_dir()


class LiveDocument:
    """规范文本 + 块模型的所有者。"""

    def __init__(self, on_text_changed: Callable[[], None]) -> None:
        self.text = ""
        self.model = build_model("")
        self.on_text_changed = on_text_changed
        self.doc_base: str | None = None
        self._undo: list[str] = []
        self._redo: list[str] = []

    # ---------------- 文本装载 ----------------

    def set_text(self, text: str) -> None:
        self.text = text
        self.model = build_model(text)
        self._undo.clear()
        self._redo.clear()

    def replace_text(self, text: str) -> None:
        """Record an asset-reference rewrite without discarding history."""
        if self.get_text() == text:
            return
        self._snapshot()
        self.text = text
        self.model = build_model(text)

    def set_surface_text(self, text: str) -> bool:
        """Adopt full Markdown produced by editing the continuous surface.

        Returns whether it changed. The surface handles per-keystroke undo, so no
        snapshot is taken here; notify the session (dirty / autosave) instead.
        """
        if text == self.get_text():
            return False
        self.text = text
        self.model = build_model(text)
        self.on_text_changed()
        return True

    def get_text(self) -> str:
        return self.text

    # ---------------- 历史 ----------------

    def _snapshot(self) -> None:
        if self._undo and self._undo[-1] == self.text:
            return
        self._undo.append(self.text)
        if len(self._undo) > 100:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.text)
        self.text = self._undo.pop()
        self.model = build_model(self.text)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.text)
        self.text = self._redo.pop()
        self.model = build_model(self.text)
        return True


class Bridge(QObject):
    """JS 通过 QWebChannel 调用的方法。"""

    test_result = Signal(str)
    operation_failed = Signal(str)

    def __init__(self, doc: LiveDocument, get_doc_path=None) -> None:
        super().__init__()
        self._doc = doc
        self._get_doc_path = get_doc_path or (lambda: None)

    @Slot(result=str)
    def loadSurfaceHtml(self) -> str:
        from ..services.surface import surface_html
        return json.dumps(surface_html(self._doc.get_text(), self._doc.doc_base),
                          ensure_ascii=False)

    @Slot(str, str, result=str)
    def highlightCode(self, language: str, source: str) -> str:
        from ..services.surface import highlight_code
        return highlight_code(source, language)

    @Slot(str, result=str)
    def renderMarkdown(self, source: str) -> str:
        from ..services.surface import surface_html
        return surface_html(source, self._doc.doc_base)

    @Slot(str)
    def updateSurfaceText(self, text: str) -> None:
        self._doc.set_surface_text(text)

    @Slot(str, result=str)
    def addImage(self, args_json: str) -> str:
        try:
            args = json.loads(args_json)
            s = settings_service().current
            return import_image(
                src_path=args.get("srcPath"), data_url=args.get("dataUrl"),
                file_name=args.get("fileName"), doc_path=self._get_doc_path(),
                folder=s.image_folder, path_type=s.image_path_type,
            )
        except (OSError, ValueError, TypeError) as exc:
            self.operation_failed.emit(f"图片导入失败：{exc}")
            return ""

    @Slot(str)
    def openExternal(self, url: str) -> None:
        qurl = QUrl(url)
        if qurl.scheme().lower() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(qurl)

    @Slot(str)
    def recordTestResult(self, msg: str) -> None:
        self.test_result.emit(msg)


class WebPreview(QWebEngineView):
    """承载实时模式连续表面的 QWebEngineView。"""

    def __init__(self, doc: LiveDocument, get_doc_path=None, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("QWebEngineView { border: 0; padding: 0; background: transparent; }")
        self._doc = doc
        self._bridge = Bridge(doc, get_doc_path)
        # App commands issued before the first page load are queued.
        self._app_ready = False
        self._pending_app_scripts: list[str] = []
        # Paint the native view background to match the theme BEFORE the first
        # frame; otherwise Chromium shows a black rectangle during startup.
        self.page().setBackgroundColor(QColor(self._theme_background()))
        channel = QWebChannel(self.page())
        channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(channel)
        url = QUrl.fromLocalFile(str(_WEB_DIR / "index.html"))
        self.setUrl(url)
        self.page().loadStarted.connect(self._on_page_load_started)
        self.page().loadFinished.connect(self._on_page_loaded)
        self.loadFinished.connect(lambda _ok: self.apply_prefs())
        self.page().navigationRequested.connect(self._on_navigation)

    def flush_surface(self) -> bool:
        """Capture pending input before a synchronous save or mode switch."""
        if not self._app_ready:
            return True  # The model is authoritative before the initial load.
        from PySide6.QtCore import QEventLoop, QTimer
        result = []
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def received(value):
            result.append(value)
            loop.quit()

        self.page().runJavaScript(
            "typeof App !== 'undefined' && App.surfaceReady"
            " ? App.captureMarkdown() : null", received)
        timer.start(1200)
        if not result:
            loop.exec()
        timer.stop()
        if not result or not isinstance(result[0], str):
            return False
        self._doc.set_surface_text(result[0])
        return True

    def run_app_script(self, script_body: str) -> None:
        """Run an ``App.*`` call now, or as soon as the page has initialized."""
        command = "(() => {" + script_body + "})();"
        if self._app_ready:
            self.page().runJavaScript(command)
        else:
            self._pending_app_scripts.append(command)

    def _on_page_load_started(self) -> None:
        self._app_ready = False

    def _on_page_loaded(self, ok: bool) -> None:
        # app.js is synchronous, so App exists whenever load succeeded.
        self._app_ready = bool(ok)
        if not ok:
            return
        pending, self._pending_app_scripts = self._pending_app_scripts, []
        for command in pending:
            self.page().runJavaScript(
                "window.__mdnoteDeliver(" + json.dumps(command) + ");")

    def _on_navigation(self, request) -> None:
        # Page-level clicks are already handled (external -> OS browser, anchors
        # -> in-page scroll). Reject any link navigation that bypasses that; the
        # initial setUrl (Typed) and framework loads (Other) are allowed.
        navigation = request.navigationType()
        enum_type = type(navigation)
        # PySide6 wraps this enum in a fresh class per access and renamed the
        # members, so resolve from the runtime enum class (compare by value too).
        def member(new_name: str, legacy_name: str):
            return getattr(enum_type, new_name, None) or getattr(enum_type, legacy_name, None)
        blocked = (member("LinkClickedNavigation", "NavigationTypeLinkClicked"),
                   member("RedirectNavigation", "NavigationTypeRedirect"),
                   member("ReloadNavigation", "NavigationTypeReload"),
                   member("BackForwardNavigation", "NavigationTypeBackForward"))
        value = getattr(navigation, "value", navigation)
        blocked_values = tuple(getattr(item, "value", item) for item in blocked)
        if navigation in blocked or value in blocked_values:
            request.reject()
        else:
            request.accept()

    def apply_prefs(self) -> None:
        s = settings_service().current
        theme_id = self._theme_id(s.theme)
        self.page().setBackgroundColor(QColor(self._theme_background()))
        self.page().runJavaScript(
            "document.body.classList.toggle('focus-mode', "
            f"{'true' if s.focus_mode else 'false'});"
            f"document.body.setAttribute('data-theme', {json.dumps(theme_id)});"
            f"window.__typewriter = {'true' if s.typewriter_mode else 'false'};"
            f"window.__autoBracket = {'true' if s.auto_bracket else 'false'};"
            f"window.__mermaid = {'true' if s.mermaid else 'false'};"
            f"window.__tabSize = {int(s.tab_size)};"
            f"window.__codeLineNumbers = {json.dumps(s.code_line_numbers)};"
            f"window.__defaultCodeLanguage = {json.dumps(s.default_code_language)};"
            "if (typeof App !== 'undefined') App.applyCodePrefs();"
            f"document.body.style.fontSize = {json.dumps(str(s.font_size) + 'px')};"
        )

    @staticmethod
    def _theme_id(theme: str) -> str:
        """Map the setting theme name to the CSS data-theme id."""
        t = theme.lower()
        for theme_id in ("light", "dark", "solarized", "sepia",
                         "night", "monokai", "dracula"):
            if theme_id in t:
                return theme_id
        return "light"

    _THEME_BACKGROUNDS = {"light": "#ffffff", "dark": "#0d1117",
                          "solarized": "#fdf6e3", "sepia": "#f5ecd9",
                          "night": "#000000", "monokai": "#272822",
                          "dracula": "#282a36"}

    def _theme_background(self) -> str:
        try:
            theme_id = self._theme_id(settings_service().current.theme)
        except Exception:
            theme_id = "light"
        return self._THEME_BACKGROUNDS.get(theme_id, "#ffffff")

    def reload_blocks(self, focus: bool = False) -> None:
        """Rebuild the continuous surface from the current document text."""
        if focus:
            self.setFocus()
        self.run_app_script("App.loadSurface();")

    def focus_editor(self) -> None:
        self.setFocus()
        self.run_app_script("App.focusEditor();")
