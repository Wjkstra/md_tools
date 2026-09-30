"""主窗口：菜单、双模式编辑器、文件生命周期、侧边栏 / 查找 / 状态栏联动。"""

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QTimer, Qt
from PySide6.QtGui import QAction, QKeySequence, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import settings_service
from ..core.word_count import DocStats, count_stats
from ..editor.block_model import build_model, extract_headings
from ..editor.source_editor import SourceEditor
from ..editor.webview import LiveDocument, WebPreview
from ..services import exporter
from .dialogs import SettingsDialog, alert, confirm, prompt
from .findbar import FindBar
from .sidebar import Sidebar
from .statusbar import StatusBar

WELCOME = """# MdNote

欢迎使用 **Python / PySide6** 重写的 MdNote。

- 默认是渲染后模式，点击任意位置即可编辑
- `Ctrl+/` 切换源码模式
- 支持任务列表：

- [ ] 未完成项
- [x] 已完成项
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MdNote")
        self.resize(1280, 860)

        self._file_path: str | None = None
        self._mode = "live"
        self._dirty = False
        self._stats: DocStats = count_stats("")

        # 文档与编辑器
        self._doc = LiveDocument(self._on_content_changed)
        self._preview = WebPreview(self._doc, get_doc_path=lambda: self._file_path)
        self._source = SourceEditor()
        self._source.content_changed_detail.connect(self._on_content_changed)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._preview)
        self._stack.addWidget(self._source)

        # 侧边栏
        self.sidebar = Sidebar()
        self.sidebar.open_file_requested.connect(self.open_file)
        self.sidebar.jump_requested.connect(self.jump_heading)

        splitter = QSplitter()
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(1, 1)
        self.sidebar.hide()

        # 查找栏 / 状态栏
        self.findbar = FindBar()
        self.findbar.find_next.connect(self.find_text)
        self.findbar.replace_one.connect(self.replace_text)
        self.findbar.closed.connect(lambda: self._preview.setFocus())
        self.statusbar = StatusBar()

        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.findbar)
        layout.addWidget(self.statusbar)
        self.setCentralWidget(center)

        self._build_menus()
        self._build_timers()
        settings_service().on_change(lambda _s: self._preview.apply_prefs())
        self._restore_session()

    # ---------------- 菜单 ----------------

    def _build_menus(self) -> None:
        mb = self.menuBar()

        def action(label: str, slot, shortcut: str | None = None) -> QAction:
            act = QAction(label, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(slot)
            return act

        m_file = mb.addMenu("文件")
        m_file.addAction(action("新建", self.new_file, "Ctrl+N"))
        m_file.addAction(action("打开…", self.open_dialog, "Ctrl+O"))
        m_file.addAction(action("打开文件夹…", self.open_folder_dialog, "Ctrl+Shift+O"))
        m_file.addSeparator()
        m_file.addAction(action("保存", lambda: self.save(False), "Ctrl+S"))
        m_file.addAction(action("另存为…", lambda: self.save(True), "Ctrl+Shift+S"))
        m_file.addSeparator()
        m_export = m_file.addMenu("导出")
        m_export.addAction(action("HTML 文件", self.export_html))
        m_export.addAction(action("PDF 文件", self.export_pdf))
        m_export.addAction(action("PNG 图片", lambda: self.export_image_file("PNG")))
        m_export.addAction(action("JPEG 图片", lambda: self.export_image_file("JPEG")))
        for fmt in ("docx", "epub", "latex", "odt"):
            m_export.addAction(action(fmt.upper(), lambda checked=False, f=fmt: self.export_pandoc(f)))
        m_file.addSeparator()
        m_file.addAction(action("退出", self.close, "Ctrl+Q"))

        m_edit = mb.addMenu("编辑")
        m_edit.addAction(action("撤销", self._undo, "Ctrl+Z"))
        m_edit.addAction(action("重做", self._redo, "Ctrl+Y"))
        m_edit.addSeparator()
        m_edit.addAction(action("查找…", self.findbar.open, "Ctrl+F"))

        m_view = mb.addMenu("视图")
        m_view.addAction(action("切换源码 / 渲染后模式", self.toggle_mode, "Ctrl+/"))
        m_view.addAction(action("切换侧边栏", self.toggle_sidebar, "Ctrl+J"))
        m_view.addSeparator()
        m_view.addAction(action("专注模式", self.toggle_focus, "F8"))
        m_view.addAction(action("打字机模式", self.toggle_typewriter, "F9"))

        m_help = mb.addMenu("帮助")
        m_help.addAction(action("设置", lambda: SettingsDialog(self).exec(), "Ctrl+,"))
        m_help.addAction(
            action("关于", lambda: alert(self, f"MdNote {_version()}"), )
        )

    def _build_timers(self) -> None:
        self._stats_timer = QTimer(self)
        self._stats_timer.setSingleShot(True)
        self._stats_timer.timeout.connect(self._refresh_stats)

        self._outline_timer = QTimer(self)
        self._outline_timer.setSingleShot(True)
        self._outline_timer.timeout.connect(self._refresh_outline)

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave)

        self._watcher_timer = QTimer(self)
        self._watcher_timer.setSingleShot(True)

        # 外部文件改动监视
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._on_external_change)

    # ---------------- 内容变更 ----------------

    def _on_content_changed(self) -> None:
        self._set_dirty(True)
        self._stats_timer.start(200)
        self._outline_timer.start(300)
        if settings_service().current.auto_save and self._file_path:
            self._autosave_timer.start(1000)

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        self._refresh_status()

    def _current_text(self) -> str:
        if self._mode == "live":
            return self._doc.get_text()
        return self._source.get_text()

    def _refresh_status(self) -> None:
        name = Path(self._file_path).name if self._file_path else "无标题.md"
        self.statusbar.update_state(self._dirty, self._mode, self._stats, name)
        self.setWindowTitle(f"{'* ' if self._dirty else ''}{name.replace('.md', '')}")

    def _refresh_stats(self) -> None:
        self._stats = count_stats(self._current_text())
        self._refresh_status()

    def _refresh_outline(self) -> None:
        model = build_model(self._current_text())
        self.sidebar.set_headings(extract_headings(model))

    def _autosave(self) -> None:
        if not self._file_path:
            return
        target = self._file_path
        Path(target).write_text(self._current_text(), encoding="utf-8")
        self._set_dirty(False)

    # ---------------- 外部文件改动 ----------------

    def _watch_file(self, path: str | None) -> None:
        watched = self._file_watcher.files()
        if watched:
            self._file_watcher.removePaths(watched)
        if path:
            self._file_watcher.addPath(path)

    def _on_external_change(self, path: str) -> None:
        # 某些编辑器保存=替换文件，监视会丢失，重新挂接
        if path and not self._file_watcher.files():
            self._file_watcher.addPath(path)
        if path != self._file_path:
            return
        try:
            disk = Path(path).read_text(encoding="utf-8")
        except OSError:
            return
        if disk == self._current_text():
            return
        if self._dirty:
            if not confirm(self, "文件已被其他程序修改，是否重新载入？（未保存的修改将丢失）"):
                return
        self._load_text(disk)
        self._set_dirty(False)

    # ---------------- 文件操作 ----------------

    def _discard_guard(self) -> bool:
        if not self._dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("MdNote")
        box.setText("当前文档尚未保存")
        save_b = box.addButton("保存", QMessageBox.AcceptRole)
        box.addButton("不保存", QMessageBox.DestructiveRole)
        cancel_b = box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_b:
            return False
        if clicked is save_b:
            return self._do_save(False)
        return True

    def new_file(self) -> None:
        if not self._discard_guard():
            return
        self._file_path = None
        self._doc.doc_base = None
        self._watch_file(None)
        if self._mode == "live":
            self._doc.set_text("")
        else:
            self._source.set_text("")
        self._set_dirty(False)

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 Markdown", "", "Markdown (*.md *.markdown *.txt);;所有文件 (*)"
        )
        if path:
            self.open_file(path)

    def open_file(self, path: str) -> None:
        if path != self._file_path and not self._discard_guard():
            return
        text = Path(path).read_text(encoding="utf-8")
        self._file_path = path
        self._doc.doc_base = str(Path(path).parent)
        self._load_text(text)
        self._set_dirty(False)
        self._watch_file(path)
        self._push_recent(path)

    def _load_text(self, text: str) -> None:
        if self._mode == "live":
            self._doc.set_text(text)
        else:
            self._source.set_text(text)
        self._stats = count_stats(text)

    def open_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "打开文件夹")
        if folder:
            self.sidebar.open_folder(folder)
            self.sidebar.show()
            settings_service().patch(
                last_folder=folder, sidebar_visible=True, sidebar_tab="files"
            )

    def save(self, save_as: bool) -> None:
        self._do_save(save_as)

    def _do_save(self, save_as: bool) -> bool:
        target = self._file_path
        if not target or save_as:
            path, _ = QFileDialog.getSaveFileName(
                self,
                "保存",
                Path(target).name if target else "无标题.md",
                "Markdown (*.md)",
            )
            if not path:
                return False
            target = path
        Path(target).write_text(self._current_text(), encoding="utf-8")
        self._file_path = target
        self._doc.doc_base = str(Path(target).parent)
        self._set_dirty(False)
        settings_service().patch(last_file=target)
        return True

    def _push_recent(self, path: str) -> None:
        svc = settings_service()
        recent = [path] + [p for p in svc.current.recent_files if p != path]
        svc.patch(recent_files=recent[:10])

    # ---------------- 模式切换 ----------------

    def toggle_mode(self) -> None:
        if self._mode == "live":
            self._source.set_text(self._doc.get_text())
            self._mode = "source"
            self._stack.setCurrentIndex(1)
            self._source.setFocus()
        else:
            self._doc.set_text(self._source.get_text())
            self._mode = "live"
            self._stack.setCurrentIndex(0)
        self._refresh_status()

    def toggle_sidebar(self) -> None:
        if self.sidebar.isVisible():
            self.sidebar.hide()
        else:
            self.sidebar.show()

    def toggle_focus(self) -> None:
        s = settings_service().current
        settings_service().patch(focus_mode=not s.focus_mode)
        self._preview.apply_prefs()

    def toggle_typewriter(self) -> None:
        s = settings_service().current
        settings_service().patch(typewriter_mode=not s.typewriter)
        self._preview.apply_prefs()

    # ---------------- 撤销 / 重做 ----------------

    def _undo(self) -> None:
        if self._mode == "live":
            if self._doc.undo():
                self._set_dirty(True)
        else:
            self._source.undo()

    def _redo(self) -> None:
        if self._mode == "live":
            if self._doc.redo():
                self._set_dirty(True)
        else:
            self._source.redo()

    # ---------------- 查找 / 替换 ----------------

    def find_text(self, text: str, forward: bool) -> None:
        if not text:
            return
        if self._mode == "source":
            flags = QTextDocument.FindFlag(0)
            if not forward:
                flags |= QTextDocument.FindBackward
            if not self._source.find(text, flags):
                cursor = self._source.textCursor()
                cursor.movePosition(QTextCursor.Start if forward else QTextCursor.End)
                self._source.setTextCursor(cursor)
                self._source.find(text, flags)
        else:
            self._preview.page().findText(text)

    def replace_text(self, find: str, replacement: str) -> None:
        if self._mode != "source":
            alert(self, "替换功能请在源码模式下使用")
            return
        cursor = self._source.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == find:
            cursor.insertText(replacement)
        self._source.find(find)

    # ---------------- 大纲跳转 ----------------

    def jump_heading(self, block_index: int) -> None:
        model = build_model(self._current_text())
        b = model.blocks[block_index]
        if self._mode == "live":
            hid = extract_headings(model)
            target_id = next(
                (h.id for h in hid if h.block_index == block_index), None
            )
            if target_id:
                self._preview.page().runJavaScript(
                    f"document.getElementById({target_id!r}).scrollIntoView();"
                )
        else:
            line = self._current_text()[: b.start].count("\n") + 1
            self._source.goto_line(line)

    # ---------------- 导出 ----------------

    def export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 HTML", "export.html", "HTML (*.html)")
        if path:
            exporter.export_html(path, self._current_text())

    def export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", "export.pdf", "PDF (*.pdf)")
        if not path:
            return
        if self._mode == "live":
            exporter.export_pdf(self._preview.page(), path)
        else:
            alert(self, "请在渲染后模式下导出 PDF")

    def export_image_file(self, fmt: str) -> None:
        ext = "png" if fmt == "PNG" else "jpg"
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出 {fmt}", f"export.{ext}", f"{fmt} (*.{ext})"
        )
        if not path:
            return
        standalone = exporter.build_standalone_html(self._current_text())
        if not exporter.export_image(standalone, path, fmt):
            alert(self, "图片导出失败")

    def export_pandoc(self, fmt: str) -> None:
        if not exporter.pandoc_available():
            alert(self, "未检测到 Pandoc：https://pandoc.org/installing.html")
            return
        ok, err = exporter.pandoc_export(self._current_text(), fmt)
        if not ok:
            alert(self, f"导出失败：{err}")

    # ---------------- 会话恢复 ----------------

    def _restore_session(self) -> None:
        svc = settings_service()
        s = svc.current
        if s.sidebar_visible:
            self.sidebar.show()
        if s.last_folder:
            self.sidebar.open_folder(s.last_folder)
        if s.last_file and Path(s.last_file).exists():
            self.open_file(s.last_file)
        else:
            self._doc.set_text(WELCOME)
            self._stats = count_stats(WELCOME)
        self._refresh_status()

    # ---------------- 关闭守卫 ----------------

    def closeEvent(self, event) -> None:
        if not self._dirty:
            event.accept()
            return
        box = QMessageBox(self)
        box.setWindowTitle("MdNote")
        box.setText("文档有未保存的修改，是否保存？")
        save_b = box.addButton("保存", QMessageBox.AcceptRole)
        discard_b = box.addButton("不保存", QMessageBox.DestructiveRole)
        cancel_b = box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_b:
            event.ignore()
        elif clicked is save_b:
            if self._do_save(False):
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def _version() -> str:
    from .. import __version__

    return f"MdNote v{__version__}"
