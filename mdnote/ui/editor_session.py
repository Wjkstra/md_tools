"""单个标签的编辑会话：文档 + 两种编辑器 + 模式 / 文件 / dirty 状态。

一个 :class:`EditorSession` 对应标签栏中的一个标签，彼此独立。
主窗口（``host``）持有全局的侧边栏、查找栏、状态栏与文件监视器，
会话通过 ``host`` 上的少量方法与这些全局部件交互。
"""

from pathlib import Path
import json
import tempfile

from PySide6.QtCore import QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QFileDialog,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import settings_service
from ..core.file_io import atomic_write_text
from ..core.word_count import count_stats
from ..editor.block_model import build_model, extract_headings
from ..editor.source_editor import SourceEditor
from ..editor.webview import LiveDocument, WebPreview


class EditorSession(QWidget):
    def __init__(self, host) -> None:
        super().__init__()
        self.host = host

        self.file_path: str | None = None
        self._disk_text: str | None = None
        self._autosave_error_token = None
        self._external_notice = None
        self._asset_temp = tempfile.TemporaryDirectory(prefix="mdnote-assets-")
        self.destroyed.connect(lambda _obj=None, temp=self._asset_temp: temp.cleanup())
        self.mode = "live"
        self.dirty = False
        self.stats = count_stats("")

        # 文档与两种编辑器
        self.doc = LiveDocument(self.on_content_changed)
        self.doc.doc_base = self._asset_temp.name
        self.preview = WebPreview(
            self.doc, get_doc_path=self.image_document_path
        )
        self.preview._bridge.operation_failed.connect(self.host.alert)
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
        self.autosave_timer.timeout.connect(
            lambda: self.autosave() if settings_service().current.auto_save else None
        )

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
        if self.host.current is self:
            self.host.findbar.reset_feedback()
        self.stats_timer.start(200)
        self.outline_timer.start(300)
        if settings_service().current.auto_save and self.file_path:
            self.autosave_timer.start(1000)

    def image_document_path(self) -> str:
        return self.file_path or str(Path(self._asset_temp.name) / "untitled.md")

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
        if self.host.current is not self:
            return
        model = build_model(self.current_text())
        self.host.set_outline(extract_headings(model))

    def _guard_existing_save(self, target: str, *, automatic: bool = False) -> str:
        """Keep the loaded disk version until the user explicitly resolves a conflict."""
        if not self.file_path or Path(target).resolve() != Path(self.file_path).resolve():
            return "save"
        try:
            disk = Path(target).read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            disk = None
        except (OSError, UnicodeError) as exc:
            token = ("read", str(exc))
            if not automatic or self._autosave_error_token != token:
                self.host.alert(f"无法检查文件版本，修改仍保留在编辑器中：{exc}")
            self._autosave_error_token = token
            return "cancel"
        if disk == self._disk_text or disk == self.current_text():
            return "save"
        if automatic:
            token = ("conflict", disk)
            if self._autosave_error_token != token:
                self.host.alert(
                    f"「{self.display_name}」已被其他程序修改，自动保存已暂停。"
                    "\n本地修改仍保留，请按 Ctrl+S 选择另存为或处理冲突。"
                )
            self._autosave_error_token = token
            return "cancel"
        action = self.host.resolve_save_conflict(self)
        if action != "overwrite":
            return action
        # A modal dialog can stay open while another process changes the file again.
        try:
            latest = Path(target).read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            latest = None
        except (OSError, UnicodeError) as exc:
            self.host.alert(f"无法检查文件版本：{exc}")
            return "cancel"
        if latest != disk:
            self.host.alert("外部文件再次发生变化，请重新保存并确认。")
            return "cancel"
        return "save"

    def autosave(self) -> None:
        if not self.file_path or not self.dirty:
            return
        if self._guard_existing_save(self.file_path, automatic=True) != "save":
            return
        try:
            text = self.current_text()
            atomic_write_text(self.file_path, text)
        except OSError as exc:
            token = ("write", str(exc))
            if self._autosave_error_token != token:
                self.host.alert(f"自动保存失败，修改仍保留在编辑器中：{exc}")
            self._autosave_error_token = token
            return
        self._disk_text = text
        self._autosave_error_token = None
        self._external_notice = None
        self.set_dirty(False)
        self.host._arm_watcher(self.file_path)

    # ---------------- 装载 ----------------

    def load_text(self, text: str) -> None:
        if self.mode == "live":
            self.doc.set_text(text)
            # Before the page's first load, App.init will itself loadBlocks this
            # already-set text; a second loadDocument here races the init load and
            # can mark the document dirty after the explicit set_dirty(False).
            if self.preview._app_ready:
                self.preview.reload_blocks(focus=True)
        else:
            self.source.set_text(text)
        self.stats = count_stats(text)
        self.refresh_outline()

    def reset(self) -> None:
        self._disk_text = None
        self._external_notice = None
        self._autosave_error_token = None
        self.doc.doc_base = self._asset_temp.name
        if self.mode == "live":
            self.doc.set_text("")
            self.preview.reload_blocks(focus=True)
        else:
            self.source.set_text("")
        self.stats = count_stats("")
        self.refresh_outline()

    # ---------------- 保存 ----------------

    def do_save(self, save_as: bool) -> bool:
        target = self.file_path
        if not target or save_as:
            path, _ = QFileDialog.getSaveFileName(
                self.host, "保存", target or "无标题.md", "Markdown (*.md)"
            )
            if not path:
                return False
            target = path
        other = self.host._find_session_for_path(target)
        if other is not None and other is not self:
            self.host.alert("该文件已在另一个标签中打开，请切换到该标签，或选择其他文件名。")
            return False
        action = self._guard_existing_save(target)
        if action == "save_as":
            return self.do_save(True)
        if action != "save":
            return False
        from ..services.image_service import prepare_images_for_save

        previous_path = self.file_path
        prepared = None
        original = self.current_text()
        try:
            prepared = prepare_images_for_save(
                original, self.doc.doc_base, target,
                folder=settings_service().current.image_folder,
            )
            text = prepared.text
            atomic_write_text(target, text)
        except (OSError, ValueError) as exc:
            if prepared is not None:
                prepared.rollback()
            self.host.alert(f"保存失败，修改仍保留在编辑器中：{exc}")
            return False
        prepared.commit()
        if text != original:
            if self.mode == "live":
                self.doc.replace_text(text)
            else:
                offset = self.source.get_offset()
                with QSignalBlocker(self.source):
                    cursor = self.source.textCursor()
                    cursor.select(QTextCursor.Document)
                    cursor.insertText(text)
                    cursor.setPosition(min(offset, self.source.document().characterCount() - 1))
                    self.source.setTextCursor(cursor)
        self._disk_text = text
        self._autosave_error_token = None
        self._external_notice = None
        self.file_path = target
        self.doc.doc_base = str(Path(target).resolve().parent)
        self.stats = count_stats(text)
        self.set_dirty(False)
        self.host._arm_watcher(target)
        self.host._push_recent(target)
        if (previous_path != target or text != original) and self.mode == "live":
            self.preview.reload_blocks(focus=False)
        return True

    # ---------------- 模式切换 ----------------

    def toggle_mode(self) -> None:
        if self.mode == "live":
            text = self.doc.get_text()
            if self.source.get_text() != text:
                with QSignalBlocker(self.source):
                    self.source.set_text(text, offset=self.source.get_offset())
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
        self.preview.run_app_script(script)

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
                    doc_path=self.image_document_path(),
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

    def find_text(self, text: str, forward: bool, on_result=None) -> None:
        if not text:
            return
        if self.mode == "source":
            flags = QTextDocument.FindFlag(0)
            if not forward:
                flags |= QTextDocument.FindBackward
            original = self.source.textCursor()
            found = self.source.find(text, flags)
            wrapped = ""
            if not found:
                cursor = self.source.textCursor()
                cursor.movePosition(
                    QTextCursor.Start if forward else QTextCursor.End
                )
                self.source.setTextCursor(cursor)
                found = self.source.find(text, flags)
                if found:
                    wrapped = "已回到文档开头" if forward else "已回到文档末尾"
                else:
                    self.source.setTextCursor(original)
            if on_result:
                on_result(found, wrapped)
        else:
            def report(raw):
                if not on_result:
                    return
                # runJavaScript 对普通对象的自动转换在不同后端上不可靠（可能得到
                # 空字符串），统一让页面端 JSON.stringify 后再解析。
                try:
                    result = json.loads(raw) if raw else {}
                except (TypeError, ValueError):
                    result = {}
                total = int(result.get("total", 0))
                active = int(result.get("active", 0))
                message = f"{active} / {total} 处匹配" if total else ""
                on_result(bool(result.get("found")), message)
            self.preview.page().runJavaScript(
                "typeof App !== 'undefined' && JSON.stringify(App.findDocument("
                + json.dumps(text, ensure_ascii=False) + ","
                + ("true" if forward else "false") + "))",
                report,
            )

    def replace_text(self, find: str, replacement: str, on_result=None) -> None:
        if not find:
            return
        if self.mode != "source":
            self.host.alert("替换功能请在源码模式下使用")
            return
        cursor = self.source.textCursor()
        if cursor.hasSelection() and cursor.selectedText().replace("\u2029", "\n").casefold() == find.casefold():
            cursor.insertText(replacement)
        self.find_text(find, True, on_result)

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
        self.source.apply_prefs()
