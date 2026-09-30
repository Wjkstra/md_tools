"""单个标签的编辑会话：文档 + 两种编辑器 + 模式 / 文件 / dirty 状态。

一个 :class:`EditorSession` 对应标签栏中的一个标签，彼此独立。
主窗口（``host``）持有全局的侧边栏、查找栏、状态栏与文件监视器，
会话通过 ``host`` 上的少量方法与这些全局部件交互。
"""

from pathlib import Path
import json

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QFileDialog,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import settings_service
from ..core.word_count import count_stats
from ..editor.block_model import build_model, extract_headings
from ..editor.source_editor import SourceEditor
from ..editor.webview import LiveDocument, WebPreview


class EditorSession(QWidget):
    def __init__(self, host) -> None:
        super().__init__()
        self.host = host

        self.file_path: str | None = None
        self.mode = "live"
        self.dirty = False
        self.stats = count_stats("")

        # 文档与两种编辑器
        self.doc = LiveDocument(self.on_content_changed)
        self.preview = WebPreview(
            self.doc, get_doc_path=lambda: self.file_path
        )
        self.source = SourceEditor()
        self.source.content_changed_detail.connect(self.on_content_changed)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.preview)
        self.stack.addWidget(self.source)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self._build_timers()

    # ---------------- 防抖计时器（每会话独立） ----------------

    def _build_timers(self) -> None:
        self.stats_timer = QTimer(self)
        self.stats_timer.setSingleShot(True)
        self.stats_timer.timeout.connect(self.refresh_stats)

        self.outline_timer = QTimer(self)
        self.outline_timer.setSingleShot(True)
        self.outline_timer.timeout.connect(self.refresh_outline)

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.timeout.connect(self.autosave)

    # ---------------- 名称 / 标签 ----------------

    @property
    def display_name(self) -> str:
        return Path(self.file_path).name if self.file_path else "无标题.md"

    @property
    def tab_title(self) -> str:
        return ("• " if self.dirty else "") + self.display_name

    # ---------------- 内容变更 ----------------

    def on_content_changed(self) -> None:
        self.set_dirty(True)
        self.stats_timer.start(200)
        self.outline_timer.start(300)
        if settings_service().current.auto_save and self.file_path:
            self.autosave_timer.start(1000)

    def set_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self.host.request_status()

    def current_text(self) -> str:
        if self.mode == "live":
            return self.doc.get_text()
        return self.source.get_text()

    def refresh_stats(self) -> None:
        self.stats = count_stats(self.current_text())
        self.host.request_status()

    def refresh_outline(self) -> None:
        model = build_model(self.current_text())
        self.host.set_outline(extract_headings(model))

    def autosave(self) -> None:
        if not self.file_path:
            return
        Path(self.file_path).write_text(self.current_text(), encoding="utf-8")
        self.set_dirty(False)

    # ---------------- 装载 ----------------

    def load_text(self, text: str) -> None:
        if self.mode == "live":
            self.doc.set_text(text)
            self.preview.reload_blocks(focus=True)
        else:
            self.source.set_text(text)
        self.stats = count_stats(text)

    def reset(self) -> None:
        if self.mode == "live":
            self.doc.set_text("")
            self.preview.reload_blocks(focus=True)
        else:
            self.source.set_text("")
        self.stats = count_stats("")

    # ---------------- 保存 ----------------

    def do_save(self, save_as: bool) -> bool:
        target = self.file_path
        if not target or save_as:
            path, _ = QFileDialog.getSaveFileName(
                self.host,
                "保存",
                Path(target).name if target else "无标题.md",
                "Markdown (*.md)",
            )
            if not path:
                return False
            target = path
        Path(target).write_text(self.current_text(), encoding="utf-8")
        self.file_path = target
        self.doc.doc_base = str(Path(target).parent)
        self.set_dirty(False)
        settings_service().patch(last_file=target)
        return True

    # ---------------- 模式切换 ----------------

    def toggle_mode(self) -> None:
        if self.mode == "live":
            self.source.set_text(self.doc.get_text())
            self.mode = "source"
            self.stack.setCurrentIndex(1)
            self.source.setFocus()
        else:
            self.doc.set_text(self.source.get_text())
            self.preview.reload_blocks(focus=True)
            self.mode = "live"
            self.stack.setCurrentIndex(0)
            self.preview.setFocus()
        self.host.request_status()

    def focus_editor(self) -> None:
        if self.mode == "live":
            self.preview.focus_editor()
        else:
            self.source.setFocus()

    # ---------------- 格式 / 插入 ----------------

    def editor_command(self, method: str, *args) -> None:
        if self.mode != "live":
            return
        self.preview.setFocus()
        if args == ("__active__",):
            script = "App.switchTo(App.activeIndex, {raw:true, caret:0});"
        else:
            args_js = ",".join(json.dumps(a, ensure_ascii=False) for a in args)
            script = f"App.{method}({args_js});"
        guard = "typeof App !== 'undefined' && App.bridge && "
        self.preview.page().runJavaScript(guard + "(() => {" + script + "})();")

    def format_text(self, before: str, after: str | None = None) -> None:
        after = before if after is None else after
        if self.mode == "live":
            self.editor_command("wrapSelection", before, after)
            return
        cursor = self.source.textCursor()
        start = cursor.selectionStart()
        selected = cursor.selectedText().replace(" ", "\n")
        cursor.insertText(before + selected + after)
        cursor.setPosition(start + len(before))
        cursor.setPosition(
            start + len(before) + len(selected.encode("utf-16-le")) // 2,
            QTextCursor.KeepAnchor,
        )
        self.source.setTextCursor(cursor)
        self.source.setFocus()

    def insert_text(self, text: str) -> None:
        if self.mode == "live":
            self.editor_command("insertMarkdown", text)
        else:
            self.source.insertPlainText(text)
            self.source.setFocus()

    def toggle_task(self) -> None:
        if self.mode == "live":
            self.editor_command("toggleCurrentTask")
            return
        import re

        cursor = self.source.textCursor()
        cursor.select(QTextCursor.BlockUnderCursor)
        raw = cursor.selectedText()
        match = re.match(r"^(\s*[-+*]\s+)\[([ xX])\]", raw)
        if match:
            mark = "x" if match.group(2) == " " else " "
            text = raw[: match.start(2)] + mark + raw[match.end(2) :]
        else:
            text = "- [ ] " + raw
        cursor.insertText(text)
        self.source.setTextCursor(cursor)
        self.source.setFocus()

    def insert_image(self) -> None:
        from ..services.image_service import import_image

        path, _ = QFileDialog.getOpenFileName(
            self.host, "插入图片", "", "图片 (*.png *.jpg *.jpeg *.gif *.webp *.svg)"
        )
        if path:
            s = settings_service().current
            self.insert_text(
                import_image(
                    src_path=path,
                    doc_path=self.file_path,
                    folder=s.image_folder,
                    path_type=s.image_path_type,
                )
            )

    def select_document(self) -> None:
        self.source.selectAll()
        self.source.setFocus()

    # ---------------- 撤销 / 重做 ----------------

    def undo(self) -> None:
        if self.mode == "live":
            if self.doc.undo():
                self.preview.reload_blocks(focus=True)
                self.on_content_changed()
        else:
            self.source.undo()

    def redo(self) -> None:
        if self.mode == "live":
            if self.doc.redo():
                self.preview.reload_blocks(focus=True)
                self.on_content_changed()
        else:
            self.source.redo()

    # ---------------- 查找（由主窗口查找栏调用） ----------------

    def find_text(self, text: str, forward: bool) -> None:
        if not text:
            return
        if self.mode == "source":
            flags = QTextDocument.FindFlag(0)
            if not forward:
                flags |= QTextDocument.FindBackward
            if not self.source.find(text, flags):
                cursor = self.source.textCursor()
                cursor.movePosition(
                    QTextCursor.Start if forward else QTextCursor.End
                )
                self.source.setTextCursor(cursor)
                self.source.find(text, flags)
        else:
            from PySide6.QtWebEngineCore import QWebEnginePage

            flags = (
                QWebEnginePage.FindFlag(0)
                if forward
                else QWebEnginePage.FindFlag.FindBackward
            )
            self.preview.page().findText(text, flags)

    def replace_text(self, find: str, replacement: str) -> None:
        if self.mode != "source":
            self.host.alert("替换功能请在源码模式下使用")
            return
        cursor = self.source.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == find:
            cursor.insertText(replacement)
        self.source.find(find)

    def jump_heading(self, block_index: int) -> None:
        model = build_model(self.current_text())
        if self.mode == "live":
            self.editor_command("jumpTo", block_index)
        else:
            b = model.blocks[block_index]
            line = self.current_text()[: b.start].count("\n") + 1
            self.source.goto_line(line)

    # ---------------- 外观偏好 ----------------

    def apply_prefs(self) -> None:
        theme = settings_service().current.theme
        self.preview.apply_prefs()
        self.source.apply_theme(theme)
