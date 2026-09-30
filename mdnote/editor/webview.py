"""渲染后 / 实时模式：QWebEngineView + QWebChannel 桥 + LiveDocument。"""

import json
import re
from pathlib import Path
from urllib.parse import unquote
from html import escape as html_escape
from typing import Callable, Optional

import nh3
from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView

from .. import config as app_config
from ..core.settings import settings_service
from ..services.image_service import import_image
from ..services.markdown_engine import markdown_engine
from .block_model import build_model, extract_headings, find_block_index, serialize
from . import transforms as T

_WEB_DIR = app_config.web_dir()


# ---------------- 渲染内容净化（nh3 / ammonia） ----------------

_ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "col", "colgroup", "dd",
    "del", "div", "dl", "dt", "em", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "input", "ins", "kbd", "li", "mark", "ol", "p",
    "pre", "q", "s", "samp", "small", "span", "strong", "sub", "sup",
    "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul", "var",
}

_ALLOWED_ATTRS = {
    "*": {"class", "id", "title", "style"},
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "input": {"type", "checked", "disabled"},
    "td": {"colspan", "rowspan", "align"},
    "th": {"colspan", "rowspan", "align"},
    "col": {"span"},
}

_URL_SCHEMES = {"http", "https", "mailto", "tel", "file", "data"}

_IMG_SRC_RE = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)
_HAS_SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:|^//", re.IGNORECASE)


def _rewrite_relative_images(markup: str, base: str | None) -> str:
    """把相对图片地址改写为基于文档目录的绝对 file:// URL。"""
    if not base:
        return markup

    def repl(m: re.Match) -> str:
        src = m.group(2)
        if _HAS_SCHEME_RE.match(src.strip()):
            return m.group(0)
        target = (Path(base) / unquote(src)).resolve()
        return f"{m.group(1)}{target.as_uri()}{m.group(3)}"

    return _IMG_SRC_RE.sub(repl, markup)


def _safe_html(markup: str, base: str | None = None) -> str:
    """相对图片改写 → nh3 净化。"""
    markup = _rewrite_relative_images(markup, base)
    return nh3.clean(
        markup,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRS,
        url_schemes=_URL_SCHEMES,
    )


def _blocks_payload(model, base: str | None = None) -> list[dict]:
    engine = markdown_engine()
    headings = extract_headings(model)
    heading_by_block = {h.block_index: h for h in headings}
    out = []
    for i, b in enumerate(model.blocks):
        if b.trailing:
            out.append({"index": i, "type": "paragraph", "raw": "", "html": "", "trailing": True})
            continue
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
        elif b.type == "heading":
            info = heading_by_block.get(i)
            rendered = engine.render(b.raw)
            if info:
                rendered = re.sub(
                    r'(<h[1-6]\s+)id="[^"]*"',
                    f'\\1id="{html_escape(info.id)}"',
                    rendered,
                )
        else:
            rendered = engine.render(b.raw)
        rendered = _safe_html(rendered, base)
        out.append(
            {"index": i, "type": b.type, "raw": b.raw, "html": rendered, "trailing": False}
        )
    return out


class LiveDocument:
    """规范文本 + 块模型的所有者；结构操作的 Python 端。"""

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

    def get_text(self) -> str:
        return serialize(self.model)

    def payload(self) -> list[dict]:
        return _blocks_payload(self.model, self.doc_base)

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

    # ---------------- splice ----------------

    def _splice(self, start: int, end: int, insert: str, record: bool = True) -> None:
        if record:
            self._snapshot()
        self.text = self.text[:start] + insert + self.text[end:]
        self.model = build_model(self.text)

    # ---------------- 块级操作（供 JS 调用） ----------------

    def start_edit_raw(self, index: int) -> str:
        return self.model.blocks[index].raw

    def commit(self, index: int, raw: str) -> list[dict]:
        b = self.model.blocks[index]
        if b.trailing and raw:
            # 在文末挂尾块输入：文本直接追加
            self._snapshot()
            self._splice(b.start, b.start, raw, record=False)
        elif raw != b.raw:
            self._snapshot()
            self._splice(b.start, b.end, raw, record=False)
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
        self._splice(b.start, b.end, r.text, record=False)
        self.on_text_changed()
        # 块索引可能因解析变化而移动：用 caret 全局偏移重新定位块
        caret_global = b.start + r.caret
        new_index = find_block_index(self.model, caret_global)
        new_b = self.model.blocks[new_index]
        return {"index": new_index, "text": new_b.raw, "caret": caret_global - new_b.start}

    def toggle_task(self, index: int) -> list[dict]:
        b = self.model.blocks[index]
        lines = b.raw.split("\n")
        checkboxes: list[int] = []
        for i, line in enumerate(lines):
            if __import__("re").match(r"^\s*[-+*]\s+\[[ xX]\]", line):
                checkboxes.append(i)
        if not checkboxes:
            return self.payload()
        line_i = checkboxes[0]
        m = __import__("re").match(r"^(\s*[-+*]\s+)\[([ xX])\]", lines[line_i])
        nxt = " " if m.group(2) == "x" else "x"
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

    def __init__(self, doc: LiveDocument, get_doc_path=None) -> None:
        super().__init__()
        self._doc = doc
        self._get_doc_path = get_doc_path or (lambda: None)

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

    @Slot(int, str, int, str, result=str)
    def transform(self, index: int, command: str, offset: int, current_raw: str) -> str:
        r = self._doc.transform(index, command, offset, current_raw)
        return json.dumps(r, ensure_ascii=False)

    @Slot(int, result=str)
    def toggleTask(self, index: int) -> str:
        return json.dumps(self._doc.toggle_task(index), ensure_ascii=False)

    @Slot(int, str, result=str)
    def updateTable(self, index: int, markdown: str) -> str:
        return json.dumps(self._doc.update_table(index, markdown), ensure_ascii=False)

    @Slot(str, result=str)
    def addImage(self, args_json: str) -> str:
        args = json.loads(args_json)
        s = settings_service().current
        return import_image(
            src_path=args.get("srcPath"),
            data_url=args.get("dataUrl"),
            file_name=args.get("fileName"),
            doc_path=self._get_doc_path(),
            folder=s.image_folder,
            path_type=s.image_path_type,
        )

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
        channel = QWebChannel(self.page())
        channel.registerObject("bridge", self._bridge)
        self.page().setWebChannel(channel)
        url = QUrl.fromLocalFile(str(_WEB_DIR / "index.html"))
        self.setUrl(url)
        self.loadFinished.connect(lambda _ok: self.apply_prefs())
        # 拦截一切会让视图离开本应用页面的导航（外链已在页面层交系统浏览器）
        self.page().navigationRequested.connect(self._on_navigation)

    def _on_navigation(self, request) -> None:
        # 链接点击在页面层已处理（外链 → 系统浏览器，锚点 → 页内滚动）。
        # 若仍有「链接」导航抵达这里，说明绕过了页面脚本——拒绝以防视图跳走；
        # 初始加载(Other)、刷新(Reload) 等其余类型放行。
        nav_type = getattr(request, "navigationType", None)
        if nav_type is not None and int(nav_type) == 0:  # Link
            request.reject()
        else:
            request.accept()

    def apply_prefs(self) -> None:
        s = settings_service().current
        dark = self._is_dark(s.theme)
        self.page().runJavaScript(
            "document.body.classList.toggle('focus-mode', "
            f"{'true' if s.focus_mode else 'false'});"
            "document.body.classList.toggle('theme-dark', "
            f"{'true' if dark else 'false'});"
            f"window.__typewriter = {'true' if s.typewriter_mode else 'false'};"
            f"window.__smartQuotes = {'true' if s.smart_punctuation else 'false'};"
        )

    @staticmethod
    def _is_dark(theme: str) -> bool:
        t = theme.lower()
        return any(k in t for k in ("dark", "night", "monokai", "dracula"))

    def reload_blocks(self) -> None:
        self.page().runJavaScript("App && App.bridge && App.bridge.loadBlocks((p)=>App.renderAll(p));")
