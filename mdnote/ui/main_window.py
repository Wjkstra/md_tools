"""主窗口：多标签文档管理、菜单、侧边栏 / 查找 / 状态栏联动。"""

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import settings_service
from ..core.word_count import count_stats
from .. import config
from ..editor.webview import invalidate_render_cache
from ..services import exporter, markdown_engine
from .dialogs import CommandPalette, SettingsDialog
from .editor_session import EditorSession
from .findbar import FindBar
from .sidebar import Sidebar
from .statusbar import StatusBar

WELCOME = """# MdNote

欢迎使用 **Python / PySide6** 构建的 MdNote。

- 默认是渲染后模式，点击任意位置即可编辑
- `Ctrl+/` 切换源码模式
- 可打开多个文件，用标签切换：

- [ ] 未完成项
- [x] 已完成项
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("MdNote")
        self.setWindowIcon(QIcon(str(config.icon_file())))
        self.resize(1280, 860)

        # 启动即按已启用插件配置渲染引擎（需在首次构建渲染负载之前）
        self._enabled_plugins = list(settings_service().current.enabled_plugins)
        markdown_engine.reconfigure(self._enabled_plugins)

        # 标签栏
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 侧边栏
        self.sidebar = Sidebar()
        self.sidebar.open_file_requested.connect(self.open_file)
        self.sidebar.jump_requested.connect(self.jump_heading)
        self.sidebar.return_editor_requested.connect(self.focus_editor)

        splitter = QSplitter()
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        self.sidebar.hide()

        # 查找栏 / 状态栏（全局共享，作用于当前标签）
        self.findbar = FindBar()
        self.findbar.find_next.connect(self.find_text)
        self.findbar.replace_one.connect(self.replace_text)
        self.findbar.closed.connect(self.focus_editor)
        self.statusbar = StatusBar()

        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.findbar)
        layout.addWidget(self.statusbar)
        self.setCentralWidget(center)

        # 外部文件改动监视（跟随当前标签）
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._on_external_change)

        self._build_menus()
        settings_service().on_change(self._on_settings_changed)

        # 始终先创建一个初始标签（即使 _restore_session 被打桩也存在）
        self._initial_session = self.add_session(focus=True)
        self._restore_session()

    # =========================================================
    #  标签管理
    # =========================================================

    @property
    def current(self) -> EditorSession | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, EditorSession) else None

    def add_session(
        self,
        text: str = "",
        file_path: str | None = None,
        focus: bool = True,
    ) -> EditorSession:
        session = EditorSession(self)
        index = self.tabs.addTab(session, "无标题.md")
        if file_path:
            session.file_path = file_path
            session.doc.doc_base = str(Path(file_path).parent)
        if text:
            session.load_text(text)
        session.set_dirty(False)
        if focus:
            self.tabs.setCurrentIndex(index)
        return session

    def open_file(self, path: str) -> None:
        # 已在某标签打开 → 直接聚焦该标签
        existing = self._find_session_for_path(path)
        if existing is not None:
            self.tabs.setCurrentIndex(self.tabs.indexOf(existing))
            return
        text = Path(path).read_text(encoding="utf-8")
        session = self.add_session(text, file_path=path)
        self._arm_watcher(path)
        self._push_recent(path)

    def _find_session_for_path(self, path: str) -> EditorSession | None:
        target = str(Path(path).resolve())
        for i in range(self.tabs.count()):
            session = self.tabs.widget(i)
            if (
                isinstance(session, EditorSession)
                and session.file_path
                and str(Path(session.file_path).resolve()) == target
            ):
                return session
        return None

    def close_tab(self, index: int) -> None:
        session = self.tabs.widget(index)
        if not isinstance(session, EditorSession):
            self.tabs.removeTab(index)
            return
        if not session.dirty or self._discard_guard(session):
            self.tabs.removeTab(index)
            session.deleteLater()
            # 没有标签时自动新建一个空白标签
            if self.tabs.count() == 0:
                self.add_session()

    def new_tab(self) -> None:
        self.add_session()

    def _next_tab(self, delta: int) -> None:
        if self.tabs.count() < 2:
            return
        index = (self.tabs.currentIndex() + delta) % self.tabs.count()
        self.tabs.setCurrentIndex(index)

    # =========================================================
    #  会话（EditorSession）通过 host 调用的方法
    # =========================================================

    def request_status(self) -> None:
        session = self.current
        # 更新当前标签标题
        cur_index = self.tabs.currentIndex()
        if session is not None and cur_index >= 0:
            self.tabs.setTabText(cur_index, session.tab_title)
            name = session.display_name
            self.statusbar.update_state(
                session.dirty, session.mode, session.stats, name
            )
            self.setWindowTitle(
                f"{'* ' if session.dirty else ''}{name.replace('.md', '')}"
            )

    def set_outline(self, headings) -> None:
        self.sidebar.set_headings(headings)

    def alert(self, message: str) -> None:
        QMessageBox.information(self, "MdNote", message)

    def confirm(self, message: str) -> bool:
        return (
            QMessageBox.question(
                self, "MdNote", message,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
            )
            == QMessageBox.Yes
        )

    # =========================================================
    #  设置变化（插件 / 外观）
    # =========================================================

    def _on_settings_changed(self, s) -> None:
        self.current and self.current.apply_prefs()
        enabled = list(s.enabled_plugins)
        if enabled != self._enabled_plugins:
            errors = markdown_engine.reconfigure(enabled)
            invalidate_render_cache()
            self._enabled_plugins = enabled
            if self.current and self.current.mode == "live":
                self.current.preview.reload_blocks(focus=False)
            if errors:
                detail = "\n".join(
                    f"• {name}: {msg}" for name, msg in errors
                )
                self.alert(f"部分插件未能加载：\n{detail}")

    # =========================================================
    #  菜单
    # =========================================================

    def _build_menus(self) -> None:
        mb = self.menuBar()

        def action(label, slot, shortcut=None):
            act = QAction(label, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(slot)
            return act

        def with_session(method_name):
            def caller():
                session = self.current
                if session:
                    getattr(session, method_name)()
            return caller

        m_file = mb.addMenu("文件(&F)")
        m_file.addAction(action("新建", self.new_tab, "Ctrl+N"))
        m_file.addAction(action("新建标签", self.new_tab, "Ctrl+T"))
        m_file.addAction(action("打开…", self.open_dialog, "Ctrl+O"))
        m_file.addAction(action("打开文件夹…", self.open_folder_dialog, "Ctrl+Shift+O"))
        m_file.addSeparator()
        m_file.addAction(action("保存", lambda: self.current and self.current.do_save(False), "Ctrl+S"))
        m_file.addAction(action("另存为…", lambda: self.current and self.current.do_save(True), "Ctrl+Shift+S"))
        m_file.addAction(action("关闭标签", lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W"))
        m_file.addSeparator()
        m_export = m_file.addMenu("导出")
        m_export.addAction(action("HTML 文件", self.export_html))
        m_export.addAction(action("PDF 文件", self.export_pdf))
        m_export.addAction(action("PNG 图片", lambda: self.export_image_file("PNG")))
        m_export.addAction(action("JPEG 图片", lambda: self.export_image_file("JPEG")))
        for fmt in ("docx", "epub", "latex", "odt"):
            m_export.addAction(
                action(fmt.upper(), lambda checked=False, f=fmt: self.export_pandoc(f))
            )
        m_file.addSeparator()
        m_file.addAction(action("退出", self.close, "Ctrl+Q"))

        m_edit = mb.addMenu("编辑(&E)")
        m_edit.addAction(action("撤销", with_session("undo"), "Ctrl+Z"))
        m_edit.addAction(action("重做", with_session("redo"), "Ctrl+Y"))
        m_edit.addSeparator()
        m_edit.addAction(action("查找…", self.findbar.open, "Ctrl+F"))
        m_edit.addAction(action("替换（源码模式）…", self.open_replace, "Ctrl+H"))
        m_edit.addAction(action("全选全文（源码模式）", self.select_document, "Ctrl+Shift+A"))
        m_edit.addAction(action("查找下一个", lambda: self.findbar.next_match(True), "F3"))
        m_edit.addAction(action("查找上一个", lambda: self.findbar.next_match(False), "Shift+F3"))
        m_edit.addSeparator()
        m_edit.addAction(action("加粗", lambda: self.current and self.current.format_text("**"), "Ctrl+B"))
        m_edit.addAction(action("斜体", lambda: self.current and self.current.format_text("*"), "Ctrl+I"))
        m_edit.addAction(action("删除线", lambda: self.current and self.current.format_text("~~"), "Ctrl+Shift+X"))
        m_edit.addAction(action("行内代码", lambda: self.current and self.current.format_text("`"), "Ctrl+Shift+`"))
        m_edit.addAction(action("链接", lambda: self.current and self.current.format_text("[", "](https://)"), "Ctrl+K"))
        m_edit.addAction(action("插入代码块", lambda: self.current and self.current.insert_text("\n\n```\n\n```\n\n"), "Ctrl+Shift+K"))
        m_edit.addAction(action("插入表格", lambda: self.current and self.current.insert_text("\n\n| 列一 | 列二 |\n| --- | --- |\n|  |  |\n\n")))
        m_edit.addAction(action("切换任务完成状态 / 插入任务项", with_session("toggle_task"), "Ctrl+Shift+Enter"))
        m_edit.addAction(action("插入图片…", with_session("insert_image"), "Ctrl+Shift+I"))
        m_edit.addAction(action("插入分隔线", lambda: self.current and self.current.insert_text("\n\n---\n\n")))
        m_edit.addAction(action("编辑当前块源码", lambda: self.current and self.current.editor_command("switchTo", "__active__"), "F2"))

        m_table = m_edit.addMenu("表格")
        for title, command in (("在下方插入行", "row"), ("在右侧插入列", "column"),
                               ("删除当前行", "deleteRow"), ("删除当前列", "deleteColumn"),
                               ("当前列左对齐", "left"), ("当前列居中", "center"), ("当前列右对齐", "right")):
            m_table.addAction(
                action(title, lambda checked=False, c=command:
                       self.current and self.current.editor_command("tableCommand", c))
            )

        m_view = mb.addMenu("视图(&V)")
        m_view.addAction(action("切换源码 / 渲染后模式", with_session("toggle_mode"), "Ctrl+/"))
        m_view.addAction(action("切换侧边栏", self.toggle_sidebar, "Ctrl+J"))
        m_view.addAction(action("转到文件树", lambda: self.focus_sidebar("files"), "Ctrl+Shift+E"))
        m_view.addAction(action("转到大纲", lambda: self.focus_sidebar("outline"), "Ctrl+Shift+L"))
        m_view.addAction(action("返回编辑器", self.focus_editor, "Ctrl+Alt+E"))
        m_view.addAction(action("下一个标签", lambda: self._next_tab(1), "Ctrl+Tab"))
        m_view.addAction(action("上一个标签", lambda: self._next_tab(-1), "Ctrl+Shift+Tab"))
        m_view.addAction(action("下一个区域", lambda: self.cycle_focus(False), "F6"))
        m_view.addAction(action("上一个区域", lambda: self.cycle_focus(True), "Shift+F6"))
        m_view.addSeparator()
        m_view.addAction(action("专注模式", self.toggle_focus, "F8"))
        m_view.addAction(action("打字机模式", self.toggle_typewriter, "F9"))

        m_help = mb.addMenu("帮助(&H)")
        m_help.addAction(action("命令面板…", self.open_commands, "Ctrl+Shift+P"))
        m_help.addAction(action("设置", lambda: SettingsDialog(self).exec(), "Ctrl+,"))
        m_help.addAction(action("关于", lambda: self.alert(f"MdNote {_version()}")))

    def menu_commands(self):
        def walk(menu, prefix=""):
            for act in menu.actions():
                if act.isSeparator():
                    continue
                title = (prefix + " / " if prefix else "") + act.text().replace("&", "")
                if act.menu():
                    yield from walk(act.menu(), title)
                else:
                    yield title, act
        return list(walk(self.menuBar()))

    def open_commands(self) -> None:
        dialog = CommandPalette(self, self.menu_commands())
        dialog.exec()
        if dialog.chosen:
            dialog.chosen.trigger()
        dialog.deleteLater()

    # =========================================================
    #  焦点导航
    # =========================================================

    def focus_editor(self) -> None:
        self.current and self.current.focus_editor()

    def toggle_mode(self) -> None:
        self.current and self.current.toggle_mode()

    def new_file(self) -> None:
        """当前标签重置为空白文档（清除其文件关联）；新建独立标签用 new_tab。"""
        session = self.current
        if not session:
            self.new_tab()
            return
        if session.dirty and not self._discard_guard(session):
            return
        session.file_path = None
        session.doc.doc_base = None
        self._arm_watcher(None)
        session.reset()
        session.set_dirty(False)

    def focus_sidebar(self, name) -> None:
        self.current and self.current.refresh_outline()
        self.sidebar.show()
        self.sidebar.show_tab(name)
        self.sidebar.focus_current()

    def cycle_focus(self, backwards) -> None:
        self.sidebar.show()
        panes = [self.tabs, self.sidebar]
        if self.findbar.isVisible():
            panes.append(self.findbar)
        focused = QApplication.focusWidget()
        current_index = next(
            (i for i, pane in enumerate(panes)
             if pane is focused or pane.isAncestorOf(focused)),
            0,
        )
        target = panes[(current_index + (-1 if backwards else 1)) % len(panes)]
        if target is self.tabs:
            self.focus_editor()
        elif target is self.sidebar:
            self.sidebar.focus_current()
        else:
            self.findbar.open()

    # =========================================================
    #  文件 / 编辑动作（委托当前标签）
    # =========================================================

    def open_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "打开 Markdown", "",
            "Markdown (*.md *.markdown *.txt);;所有文件 (*)",
        )
        if path:
            self.open_file(path)

    def open_replace(self) -> None:
        session = self.current
        if session and session.mode == "live":
            session.toggle_mode()
        self.findbar.open()

    def select_document(self) -> None:
        session = self.current
        if session and session.mode == "live":
            session.toggle_mode()
        if session:
            session.select_document()

    def find_text(self, text, forward) -> None:
        self.current and self.current.find_text(text, forward)

    def replace_text(self, find, replacement) -> None:
        self.current and self.current.replace_text(find, replacement)

    def jump_heading(self, block_index) -> None:
        self.current and self.current.jump_heading(block_index)

    def open_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "打开文件夹")
        if folder:
            self.sidebar.open_folder(folder)
            self.sidebar.show()
            settings_service().patch(
                last_folder=folder, sidebar_visible=True, sidebar_tab="files"
            )

    def toggle_sidebar(self) -> None:
        if self.sidebar.isVisible():
            self.sidebar.hide()
            self.focus_editor()
        else:
            self.sidebar.show()
            self.sidebar.focus_current()

    def toggle_focus(self) -> None:
        s = settings_service().current
        settings_service().patch(focus_mode=not s.focus_mode)
        self.current and self.current.apply_prefs()

    def toggle_typewriter(self) -> None:
        s = settings_service().current
        settings_service().patch(typewriter_mode=not s.typewriter_mode)
        self.current and self.current.apply_prefs()

    # =========================================================
    #  导出
    # =========================================================

    def _current_text(self) -> str:
        return self.current.current_text() if self.current else ""

    def export_html(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 HTML", "export.html", "HTML (*.html)")
        if path:
            exporter.export_html(path, self._current_text())

    def export_pdf(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", "export.pdf", "PDF (*.pdf)")
        if not path:
            return
        if self.current and self.current.mode == "live":
            exporter.export_pdf(self.current.preview.page(), path)
        else:
            self.alert("请在渲染后模式下导出 PDF")

    def export_image_file(self, fmt) -> None:
        ext = "png" if fmt == "PNG" else "jpg"
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出 {fmt}", f"export.{ext}", f"{fmt} (*.{ext})"
        )
        if not path:
            return
        standalone = exporter.build_standalone_html(self._current_text())
        if not exporter.export_image(standalone, path, fmt):
            self.alert("图片导出失败")

    def export_pandoc(self, fmt) -> None:
        if not exporter.pandoc_available():
            self.alert("未检测到 Pandoc：https://pandoc.org/installing.html")
            return
        ok, err = exporter.pandoc_export(self._current_text(), fmt)
        if not ok:
            self.alert(f"导出失败：{err}")

    # =========================================================
    #  外部文件改动
    # =========================================================

    def _arm_watcher(self, path: str | None) -> None:
        watched = self._file_watcher.files()
        if watched:
            self._file_watcher.removePaths(watched)
        if path:
            self._file_watcher.addPath(path)

    def _on_tab_changed(self, _index) -> None:
        session = self.current
        self._arm_watcher(session.file_path if session else None)
        self.request_status()

    def _on_external_change(self, path: str) -> None:
        session = self.current
        # 某些编辑器保存=替换文件，监视会丢失，重新挂接
        if path and not self._file_watcher.files():
            self._file_watcher.addPath(path)
        if not session or path != session.file_path:
            return
        try:
            disk = Path(path).read_text(encoding="utf-8")
        except OSError:
            return
        if disk == session.current_text():
            return
        if session.dirty and not self.confirm(
            "文件已被其他程序修改，是否重新载入？（未保存的修改将丢失）"
        ):
            return
        session.load_text(disk)
        session.set_dirty(False)

    # =========================================================
    #  关闭某个标签 / 整个窗口的守卫
    # =========================================================

    def _discard_guard(self, session: EditorSession) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("MdNote")
        box.setText(f"「{session.display_name}」尚未保存")
        save_b = box.addButton("保存", QMessageBox.AcceptRole)
        box.addButton("不保存", QMessageBox.DestructiveRole)
        cancel_b = box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_b:
            return False
        if clicked is save_b:
            return session.do_save(False)
        return True

    def _restore_session(self) -> None:
        svc = settings_service()
        s = svc.current

        # 内容装载进 __init__ 已创建的初始标签，避免多出一个空标签
        session = self._initial_session
        if s.last_file and Path(s.last_file).exists():
            text = Path(s.last_file).read_text(encoding="utf-8")
            session.file_path = s.last_file
            session.doc.doc_base = str(Path(s.last_file).parent)
            session.load_text(text)
            session.set_dirty(False)
            self._arm_watcher(s.last_file)
            self._push_recent(s.last_file)
        else:
            session.load_text(WELCOME)
            session.set_dirty(False)

        if s.sidebar_visible:
            self.sidebar.show()
        if s.last_folder:
            self.sidebar.open_folder(s.last_folder)
        self.request_status()

    def closeEvent(self, event) -> None:
        dirty_sessions = [
            self.tabs.widget(i)
            for i in range(self.tabs.count())
            if isinstance(self.tabs.widget(i), EditorSession)
            and self.tabs.widget(i).dirty
        ]
        if not dirty_sessions:
            event.accept()
            return
        box = QMessageBox(self)
        box.setWindowTitle("MdNote")
        box.setText(f"有 {len(dirty_sessions)} 个文档尚未保存")
        save_b = box.addButton("全部保存", QMessageBox.AcceptRole)
        box.addButton("全部不保存", QMessageBox.DestructiveRole)
        cancel_b = box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is cancel_b:
            event.ignore()
        elif clicked is save_b:
            # 任一文档保存被取消（如另存为）则不退出
            if all(session.do_save(False) for session in dirty_sessions):
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    # ---- 兼容旧集成测试的属性 / 方法（指向当前标签） ----

    @property
    def _doc(self):
        return self.current.doc if self.current else None

    @property
    def _preview(self):
        return self.current.preview if self.current else None

    @property
    def _source(self):
        return self.current.source if self.current else None

    @property
    def _mode(self):
        return self.current.mode if self.current else "live"

    @_mode.setter
    def _mode(self, value):
        if self.current:
            self.current.mode = value

    @property
    def _file_path(self):
        return self.current.file_path if self.current else None

    @_file_path.setter
    def _file_path(self, value):
        if self.current:
            self.current.file_path = value

    @property
    def _dirty(self):
        return bool(self.current and self.current.dirty)

    def _set_dirty(self, value) -> None:
        self.current and self.current.set_dirty(value)

    def _on_content_changed(self) -> None:
        self.current and self.current.on_content_changed()

    def _load_text(self, text) -> None:
        self.current and self.current.load_text(text)

    def _do_save(self, save_as) -> bool:
        return bool(self.current and self.current.do_save(save_as))

    def _autosave(self) -> None:
        self.current and self.current.autosave()

    def _refresh_status(self) -> None:
        self.request_status()

    def _refresh_outline(self) -> None:
        self.current and self.current.refresh_outline()


def _version() -> str:
    from .. import __version__

    return f"MdNote v{__version__}"
