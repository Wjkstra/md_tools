"""渲染后 / 实时模式：QWebEngineView + QWebChannel 桥 + LiveDocument。"""

import json
import re
from functools import lru_cache
from pathlib import Path
from html import escape as html_escape
from typing import Callable, Optional

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage

from .. import config as app_config
from ..core.settings import settings_service
from ..services.html_service import safe_html as _safe_html, rewrite_relative_images as _rewrite_relative_images
from ..services.image_service import import_image
from ..services.markdown_engine import markdown_engine
from .block_model import build_model, extract_headings, find_block_index, serialize
from . import transforms as T

_WEB_DIR = app_config.web_dir()


_RENDER_GENERATION = 0


@lru_cache(maxsize=512)
def _render_block(raw: str) -> str:
    return markdown_engine().render(raw)


def invalidate_render_cache() -> None:
    """Markdown 引擎 / 启用插件变化后清空块渲染缓存。"""
    global _RENDER_GENERATION
    _RENDER_GENERATION += 1
    _render_block.cache_clear()


def _blocks_payload(model, base: str | None = None,
                    rendered_cache: dict | None = None) -> list[dict]:
    # Keep the document's working set rather than cycling through a small global LRU.
    cache = rendered_cache if rendered_cache is not None else {}
    used = set()
    headings = extract_headings(model)
    heading_by_block = {h.block_index: h for h in headings}
    toc_key = tuple((h.level, h.id, h.text) for h in headings)
    out = []
    for i, b in enumerate(model.blocks):
        if b.trailing:
            out.append({"index": i, "type": "paragraph", "raw": "", "html": "", "trailing": True})
            continue
        info = heading_by_block.get(i)
        key = (b.raw, b.type, base, info.id if info else None,
               toc_key if b.type == "toc" else None)
        used.add(key)
        rendered = cache.get(key)
        if rendered is None:
            if b.type == "toc":
                items = "".join(
                    f'<li class="toc-item toc-l{h.level}" style="padding-left:{(h.level - 1) * 14}px">'
                    f'<a class="toc-link" data-toc-id="{html_escape(h.id)}">{html_escape(h.text)}</a></li>'
                    for h in headings
                )
                rendered = (
                    '<nav class="toc-block"><div class="toc-title">目录</div>'
                    f'<ul class="toc-list">{items}</ul></nav>'
                )
            else:
                rendered = _render_block(b.raw)
                if b.type == "heading" and info:
                    rendered = re.sub(
                        r'(<h[1-6]\s+)id="[^"]*"',
                        lambda m: f'{m.group(1)}id="{html_escape(info.id)}"',
                        rendered,
                    )
            rendered = _safe_html(rendered, base)
            cache[key] = rendered
        out.append({"index": i, "type": b.type, "raw": b.raw,
                    "html": rendered, "trailing": False})
    # Deleted/changed blocks do not accumulate across the editing session.
    for stale in cache.keys() - used:
        del cache[stale]
    return out


class LiveDocument:
    """规范文本 + 块模型的所有者；结构操作的 Python 端。"""

    def __init__(self, on_text_changed: Callable[[], None]) -> None:
        self.text = ""
        self.model = build_model("")
        self.on_text_changed = on_text_changed
        self.doc_base: str | None = None
        self._render_cache: dict = {}
        self._render_generation = _RENDER_GENERATION
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._draft: tuple[int, str] | None = None

    # ---------------- 文本装载 ----------------

    def set_text(self, text: str) -> None:
        self._draft = None
        self.text = text
        self.model = build_model(text)
        self._undo.clear()
        self._redo.clear()

    def replace_text(self, text: str) -> None:
        """Record an asset-reference rewrite without discarding editing history."""
        current = self.get_text()
        if current == text:
            return
        if self._draft is not None:
            self.text = current
            self.model = build_model(current)
            self._draft = None
        self._snapshot()
        self.text = text
        self.model = build_model(text)

    def set_surface_text(self, text: str) -> bool:
        """Adopt full Markdown produced by editing the continuous surface.

        Returns whether the text changed. Rebuilds the model and notifies the
        session (marks dirty / schedules save) but does not snapshot per keystroke;
        the surface's own undo handles history.
        """
        if text == self.get_text():
            return False
        self._draft = None
        self.text = text
        self.model = build_model(text)
        self._render_cache.clear()
        self.on_text_changed()
        return True

    def get_text(self) -> str:
        if self._draft is not None:
            index, raw = self._draft
            b = self.model.blocks[index]
            return self.text[:b.start] + self._insertion(index, raw) + self.text[b.end:]
        return self.text

    def _insertion(self, index: int, raw: str) -> str:
        b = self.model.blocks[index]
        if b.trailing and raw and self.text and not self.text.endswith("\n"):
            return "\n\n" + raw
        return raw

    def update_draft(self, index: int, raw: str) -> None:
        """同步输入供保存使用，编辑期间保持块索引稳定。"""
        if self._draft == (index, raw):
            return
        if self._draft is None and raw == self.model.blocks[index].raw:
            return
        if raw != self.model.blocks[index].raw:
            self._redo.clear()
        self._draft = (index, raw)
        self.on_text_changed()

    def payload(self) -> list[dict]:
        if self._render_generation != _RENDER_GENERATION:
            self._render_cache.clear()
            self._render_generation = _RENDER_GENERATION
        return _blocks_payload(self.model, self.doc_base, self._render_cache)

    # ---------------- 历史 ----------------

    def _snapshot(self) -> None:
        if self._undo and self._undo[-1] == self.text:
            return
        self._undo.append(self.text)
        if len(self._undo) > 100:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if self._draft is not None:
            index, raw = self._draft
            self.commit(index, raw)
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

    # ---------------- splice ----------------

    def _splice(self, start: int, end: int, insert: str, record: bool = True) -> None:
        self._draft = None
        if record:
            self._snapshot()
        self.text = self.text[:start] + insert + self.text[end:]
        self.model = build_model(self.text)

    # ---------------- 块级操作（供 JS 调用） ----------------

    def start_edit_raw(self, index: int) -> str:
        return self.model.blocks[index].raw

    def commit(self, index: int, raw: str) -> list[dict]:
        self._draft = None
        b = self.model.blocks[index]
        if raw != b.raw:
            insert = self._insertion(index, raw)
            self._snapshot()
            self._splice(b.start, b.end, insert, record=False)
            self.on_text_changed()
        return self.payload()

    def transform(self, index: int, command: str, offset: int, current_raw: str):
        b = self.model.blocks[index]
        settings = settings_service().current

        if command == "enter":
            r = T.split_at(current_raw, b.type, offset)
        elif command == "tab":
            r = T.indent_line(current_raw, offset, settings.tab_size, False)
        elif command == "shiftTab":
            r = T.indent_line(current_raw, offset, settings.tab_size, True)
        elif command == "spaceProbe":
            r = T.detect_space_trigger(current_raw, offset)
            if r is None:
                return None
        elif command == "backspace":
            prev = self.model.blocks[index - 1] if index > 0 else None
            if prev is None or prev.trailing:
                return {"text": current_raw, "caret": 0}
            self._snapshot()
            merged = T.merge_with(prev.raw, current_raw)
            span_start = prev.start
            span_end = b.end
            self._splice(span_start, span_end, merged.text, record=False)
            self.on_text_changed()
            blocks = self.payload()
            return {"blocks": blocks, "enter": {"index": index - 1, "caret": merged.caret}}
        else:
            return None

        self._snapshot()
        insert = self._insertion(index, r.text)
        prefix_len = len(insert) - len(r.text)
        self._splice(b.start, b.end, insert, record=False)
        self.on_text_changed()
        # 块索引可能因解析变化而移动：用 caret 全局偏移重新定位块
        caret_global = b.start + prefix_len + r.caret
        new_index = find_block_index(self.model, caret_global)
        if (self.model.blocks[new_index].trailing and new_index > 0
                and self.model.blocks[new_index - 1].end == caret_global
                and not r.text.endswith("\n")):
            new_index -= 1
        new_b = self.model.blocks[new_index]
        return {"blocks": self.payload(), "index": new_index,
                "text": new_b.raw, "caret": caret_global - new_b.start}

    def toggle_task(self, index: int, task_index: int = 0) -> list[dict]:
        b = self.model.blocks[index]
        lines = b.raw.split("\n")
        checkboxes: list[int] = []
        for i, line in enumerate(lines):
            if __import__("re").match(r"^\s*[-+*]\s+\[[ xX]\]", line):
                checkboxes.append(i)
        if not 0 <= task_index < len(checkboxes):
            return self.payload()
        line_i = checkboxes[task_index]
        m = __import__("re").match(r"^(\s*[-+*]\s+)\[([ xX])\]", lines[line_i])
        nxt = " " if m.group(2).lower() == "x" else "x"
        lines[line_i] = f"{m.group(1)}[{nxt}]" + lines[line_i][m.end():]
        new_raw = "\n".join(lines)
        self._snapshot()
        self._splice(b.start, b.end, new_raw, record=False)
        self.on_text_changed()
        return self.payload()

    def update_table(self, index: int, markdown: str) -> list[dict]:
        b = self.model.blocks[index]
        if markdown == b.raw:
            return self.payload()
        self._snapshot()
        self._splice(b.start, b.end, markdown, record=False)
        self.on_text_changed()
        return self.payload()


class Bridge(QObject):
    """JS 通过 QWebChannel 调用的方法。全部 JSON 字符串往返。"""

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

    @Slot(str)
    def updateSurfaceText(self, text: str) -> None:
        self._doc.set_surface_text(text)

    @Slot(str)
    def recordTestResult(self, msg: str) -> None:
        self.test_result.emit(msg)

    @Slot(result=str)
    def loadBlocks(self) -> str:
        return json.dumps(self._doc.payload(), ensure_ascii=False)

    @Slot(int, result=str)
    def startEdit(self, index: int) -> str:
        return json.dumps(self._doc.start_edit_raw(index), ensure_ascii=False)

    @Slot(int, str, result=str)
    def commit(self, index: int, raw: str) -> str:
        return json.dumps(self._doc.commit(index, raw), ensure_ascii=False)

    @Slot(int, str, int, result=str)
    def commitAndLocate(self, index: int, raw: str, target_index: int) -> str:
        block = self._doc.model.blocks[index]
        target = self._doc.model.blocks[target_index].start
        if target_index > index:
            target += len(self._doc._insertion(index, raw)) - len(block.raw)
        blocks = self._doc.commit(index, raw)
        return json.dumps({"blocks": blocks,
                           "index": find_block_index(self._doc.model, target)}, ensure_ascii=False)

    @Slot(int, str)
    def updateDraft(self, index: int, raw: str) -> None:
        self._doc.update_draft(index, raw)

    @Slot(int, str, int, str, result=str)
    def transform(self, index: int, command: str, offset: int, current_raw: str) -> str:
        # DOM selections count UTF-16 code units; Python strings count code points.
        prefix = current_raw.encode("utf-16-le")[:max(0, offset) * 2]
        py_offset = len(prefix.decode("utf-16-le", errors="ignore"))
        r = self._doc.transform(index, command, py_offset, current_raw)
        if r is not None:
            target = r.get("enter", r)
            raw = (r["blocks"][target["index"]]["raw"]
                   if "blocks" in r else r["text"])
            target["caret"] = len(raw[:target["caret"]].encode("utf-16-le")) // 2
        return json.dumps(r, ensure_ascii=False)

    @Slot(int, result=str)
    @Slot(int, int, result=str)
    def toggleTask(self, index: int, task_index: int = 0) -> str:
        return json.dumps(self._doc.toggle_task(index, task_index), ensure_ascii=False)

    @Slot(int, str, result=str)
    def updateTable(self, index: int, markdown: str) -> str:
        return json.dumps(self._doc.update_table(index, markdown), ensure_ascii=False)

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
        scheme = qurl.scheme().lower()
        if scheme in ("http", "https", "mailto"):
            QDesktopServices.openUrl(qurl)

    @Slot(result=str)
    def undo(self) -> str:
        if self._doc.undo():
            self._doc.on_text_changed()
        return json.dumps(self._doc.payload(), ensure_ascii=False)

    @Slot(result=str)
    def redo(self) -> str:
        if self._doc.redo():
            self._doc.on_text_changed()
        return json.dumps(self._doc.payload(), ensure_ascii=False)


class WebPreview(QWebEngineView):
    """承载实时模式的 QWebEngineView。"""

    def __init__(self, doc: LiveDocument, get_doc_path=None, parent=None) -> None:
        super().__init__(parent)
        self._bridge = Bridge(doc, get_doc_path)
        # App commands issued before the first page load (e.g. a jump right after
        # opening a file) would be dropped by the "typeof App" guard; queue them.
        self._app_ready = False
        self._pending_app_scripts: list[str] = []
        channel = QWebChannel(self.page())
        channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(channel)
        url = QUrl.fromLocalFile(str(_WEB_DIR / "index.html"))
        self.setUrl(url)
        self.page().loadStarted.connect(self._on_page_load_started)
        self.page().loadFinished.connect(self._on_page_loaded)
        self.loadFinished.connect(lambda _ok: self.apply_prefs())
        # 拦截一切会让视图离开本应用页面的导航（外链已在页面层交系统浏览器）
        self.page().navigationRequested.connect(self._on_navigation)

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
        # app.js is a synchronous script, so App exists whenever load succeeded.
        self._app_ready = bool(ok)
        if not ok:
            return
        pending, self._pending_app_scripts = self._pending_app_scripts, []
        for command in pending:
            # Wait (in the page) for startup loads to settle before delivering.
            self.page().runJavaScript(
                "window.__mdnoteDeliver("
                + json.dumps(command) + ");")

    def _on_navigation(self, request) -> None:
        # 链接点击在页面层已处理（外链 → 系统浏览器，锚点 → 页内滚动）。
        # 若仍有「链接」导航抵达这里，说明绕过了页面脚本——拒绝以防视图跳走；
        # 初始加载(Other)、刷新(Reload) 等其余类型放行。
        nav_type = request.navigationType()
        if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
            request.reject()
        else:
            request.accept()

    def apply_prefs(self) -> None:
        s = settings_service().current
        theme_id = self._theme_id(s.theme)
        self.page().runJavaScript(
            "document.body.classList.toggle('focus-mode', "
            f"{'true' if s.focus_mode else 'false'});"
            f"document.body.setAttribute('data-theme', {json.dumps(theme_id)});"
            f"window.__typewriter = {'true' if s.typewriter_mode else 'false'};"
            f"window.__smartQuotes = {'true' if s.smart_punctuation else 'false'};"
            f"window.__autoBracket = {'true' if s.auto_bracket else 'false'};"
            f"window.__mermaid = {'true' if s.mermaid else 'false'};"
            f"window.__codeLineNumbers = {'true' if s.code_line_numbers else 'false'};"
            f"if (document.body.style.fontSize !== {json.dumps(str(s.font_size) + 'px')}) {{"
            f"document.body.style.fontSize = {json.dumps(str(s.font_size) + 'px')};"
            "if (typeof App !== 'undefined') { App.measuredHeights.clear(); App.scheduleViewportUpdate(); }"
            "}"
            "if (typeof App !== 'undefined' && App.applyRenderPrefs) App.applyRenderPrefs();"
        )

    @staticmethod
    def _theme_id(theme: str) -> str:
        """把设置中的主题名映射到 CSS data-theme id（未知主题回落到 light）。"""
        t = theme.lower()
        known = ("light", "dark", "solarized", "sepia",
                  "night", "monokai", "dracula")
        for theme_id in known:
            if theme_id in t:
                return theme_id
        return "light"

    def reload_blocks(self, focus: bool = False) -> None:
        # Rebuild the continuous surface from the current document text.
        self.setFocus()
        self.run_app_script("App.loadSurface();")

    def focus_editor(self) -> None:
        self.setFocus()
        self.page().runJavaScript(
            "typeof App !== 'undefined' && App.bridge && App.loadSurface();")
