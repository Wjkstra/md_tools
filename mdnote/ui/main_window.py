"""主窗口：多标签文档管理、菜单、侧边栏 / 查找 / 状态栏联动。"""

from pathlib import Path
from dataclasses import asdict

from PySide6.QtCore import QFileSystemWatcher, QTimer, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from shiboken6 import isValid
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core.settings import settings_service
from ..core.word_count import count_stats
from .. import config
from ..services import exporter, markdown_engine
from .dialogs import CommandPalette, SettingsDialog
from .editor_session import EditorSession
from .findbar import FindBar
from .sidebar import Sidebar
from .statusbar import StatusBar
from .theme import apply_shell_theme, configure_ui_font

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
        configure_ui_font(self)
        self.setWindowTitle("MdNote")
        self.setWindowIcon(QIcon(str(config.icon_file())))
        self.resize(1280, 860)

        # 启动即按已启用插件配置渲染引擎（需在首次构建渲染负载之前）
        self._enabled_plugins = list(settings_service().current.enabled_plugins)
        plugin_errors = markdown_engine.reconfigure(self._enabled_plugins)
        self._manual_update_check = False
        self._operation_message = ""
        self._export_jobs = set()
        self._closing = False

        # 自动更新（清单 URL：设置覆盖 > 内置默认）。空白值（空格/换行）等同未配置。
        from .. import __version__
        from ..services.updater import UpdateManager

        manifest_url = (
            (settings_service().current.update_url or "").strip()
            or config.DEFAULT_MANIFEST_URL
        )
        self.updater = UpdateManager(manifest_url, __version__, self)
        self._wire_updater()

        # 标签栏
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self._new_tab_button = QToolButton()
        self._new_tab_button.setText("+")
        self._new_tab_button.setToolTip("新建标签（Ctrl+T）")
        self._new_tab_button.setAccessibleName("新建标签")
        self._new_tab_button.clicked.connect(self.new_tab)
        self.tabs.setCornerWidget(self._new_tab_button, Qt.TopRightCorner)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 侧边栏
        self.sidebar = Sidebar()
        self.sidebar.open_file_requested.connect(self.open_file)
        self.sidebar.jump_requested.connect(self.jump_heading)
        self.sidebar.return_editor_requested.connect(self.focus_editor)
        self.sidebar.open_search_result.connect(self.open_search_result)

        splitter = QSplitter()
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)
        self.sidebar.hide()

        # 查找栏 / 状态栏（全局共享，作用于当前标签）
        self.findbar = FindBar()
        self.findbar.find_next.connect(self.find_text)
        self.findbar.replace_one.connect(self.replace_text)
        self.findbar.closed.connect(self._close_find)
        self.findbar.query_changed.connect(self._clear_find_highlights)
        self.statusbar = StatusBar()
        self.statusbar.mode_requested.connect(self.toggle_mode)

        center = QWidget()
        center.setObjectName("shellCenter")
        layout = QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.findbar)
        layout.addWidget(self.statusbar)
        self.setCentralWidget(center)

        # 监视全部已打开文件；保存前仍检查磁盘版本。
        self._file_watcher = QFileSystemWatcher(self)
        self._file_watcher.fileChanged.connect(self._on_external_change)

        apply_shell_theme(self, settings_service().current.theme)
        self._build_menus()
        self._applied_settings = asdict(settings_service().current)
        settings_service().on_change(self._on_settings_changed)

        # 始终先创建一个初始标签（即使 _restore_session 被打桩也存在）
        self._initial_session = self.add_session(focus=True)
        self._restore_session()
        if plugin_errors:
            detail = "\n".join(f"• {name}: {message}" for name, message in plugin_errors)
            QTimer.singleShot(0, self, lambda: self.alert(f"部分插件未能加载，其他功能可继续使用：\n{detail}"))

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
        session.apply_prefs()
        index = self.tabs.addTab(session, "无标题.md")
        if file_path:
            session.file_path = file_path
            session._disk_text = text
            session.doc.doc_base = str(Path(file_path).parent)
        if text:
            session.load_text(text)
        session.set_dirty(False)
        if focus:
            self.tabs.setCurrentIndex(index)
        self.request_status()
        session.refresh_outline()
        return session

    def _read_document(self, path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            self.alert(f"无法打开文件：{path}\n{exc}\n请检查文件是否存在、可读取，并使用 UTF-8 编码。")
            return None

    def open_file(self, path: str) -> EditorSession | None:
        existing = self._find_session_for_path(path)
        if existing is not None:
            self.tabs.setCurrentIndex(self.tabs.indexOf(existing))
            existing.focus_editor()
            return existing
        text = self._read_document(path)
        if text is None:
            return None
        session = self.add_session(text, file_path=path)
        self._arm_watcher(path)
        self._push_recent(path)
        return session

    def _push_recent(self, path: str) -> None:
        target = str(Path(path).resolve())
        recent = [p for p in settings_service().current.recent_files
                  if Path(p).resolve() != Path(target)]
        try:
            settings_service().patch(last_file=target, recent_files=[target, *recent][:20])
        except OSError as exc:
            self.alert(f"文档操作已完成，但最近文件记录未能保存：{exc}")

    def _refresh_recent_menu(self) -> None:
        self._recent_menu.clear()
        recent = settings_service().current.recent_files
        if not recent:
            item = self._recent_menu.addAction("暂无最近文件")
            item.setEnabled(False)
            return
        for path in recent:
            item = self._recent_menu.addAction(f"{Path(path).name} — {Path(path).parent}")
            item.setToolTip(path)
            item.triggered.connect(lambda checked=False, p=path: self.open_file(p))

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
        # Pull debounced/atom edits from the surface before deciding whether
        # the document is dirty, so the very latest input is never dropped.
        if not session.flush_pending_edits():
            self.alert("编辑页面尚未就绪，请稍后重试关闭。")
            return
        if not session.dirty or self._discard_guard(session):
            self.tabs.removeTab(index)
            session.autosave_timer.stop()
            session.deleteLater()
            self._arm_watcher()
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
        for index in range(self.tabs.count()):
            item = self.tabs.widget(index)
            if isinstance(item, EditorSession):
                self.tabs.setTabText(index, item.tab_title)
                self.tabs.setTabToolTip(index, item.file_path or "未命名文档 · Ctrl+S 保存")
        session = self.current
        if session is not None:
            self.statusbar.update_state(
                session.dirty, session.mode, session.stats,
                session.file_path or session.display_name, bool(session.file_path),
            )
            self.findbar.set_source_mode(session.mode == "source")
            self.setWindowTitle(f"{'* ' if session.dirty else ''}{session.display_name} — MdNote")
        if self._operation_message:
            self.statusbar.show_message(self._operation_message)

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
        if not isValid(self):
            return
        values = asdict(s)
        previous = self._applied_settings
        changed = {key for key, value in values.items() if previous.get(key) != value}
        self._applied_settings = values
        if "theme" in changed:
            apply_shell_theme(self, s.theme)
        editor_prefs = {"theme", "font_size", "tab_size", "auto_bracket", "mermaid",
                        "code_line_numbers", "focus_mode", "typewriter_mode", "smart_punctuation"}
        if changed & editor_prefs:
            for index in range(self.tabs.count()):
                session = self.tabs.widget(index)
                if isinstance(session, EditorSession):
                    session.apply_prefs()
        if "recent_files" in changed:
            self._refresh_recent_menu()
        if changed & {"update_url", "auto_check_updates"}:
            self.updater.set_manifest_url(
                (s.update_url or "").strip() or config.DEFAULT_MANIFEST_URL)
            if hasattr(self, "_update_check_timer"):
                self._update_check_timer.stop()
            if s.auto_check_updates and self.updater._url:
                self._update_check_timer.start(1500)
        enabled = list(s.enabled_plugins)
        if enabled != self._enabled_plugins:
            errors = markdown_engine.reconfigure(enabled)
            self._enabled_plugins = enabled
            for index in range(self.tabs.count()):
                session = self.tabs.widget(index)
                if isinstance(session, EditorSession) and session.mode == "live":
                    session.preview.reload_blocks(focus=False)
            if errors:
                detail = "\n".join(f"• {name}: {msg}" for name, msg in errors)
                self.alert(f"部分插件未能加载，其他功能可继续使用：\n{detail}")

    def _patch_settings(self, **values) -> bool:
        try:
            settings_service().patch(**values)
        except (OSError, ValueError) as exc:
            self.alert(f"设置未能保存，原有配置仍保留：{exc}")
            return False
        return True

    def resolve_save_conflict(self, session: EditorSession) -> str:
        box = QMessageBox(self)
        box.setWindowTitle("文件已被其他程序修改")
        box.setText(f"「{session.display_name}」的磁盘版本已改变，本地修改仍保留。")
        box.setInformativeText("另存为可保留两份内容；覆盖会替换外部版本。")
        save_as = box.addButton("另存为", QMessageBox.AcceptRole)
        overwrite = box.addButton("覆盖外部版本", QMessageBox.DestructiveRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(save_as)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_as:
            return "save_as"
        return "overwrite" if clicked is overwrite else "cancel"

    def _show_operation(self, message: str = "") -> None:
        self._operation_message = message
        self.request_status()

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
        self._recent_menu = m_file.addMenu("最近打开")
        self._recent_menu.aboutToShow.connect(self._refresh_recent_menu)
        self._refresh_recent_menu()
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
        m_view.addAction(action("在文件夹中搜索", lambda: self.focus_sidebar("search"), "Ctrl+Shift+F"))
        m_view.addAction(action("返回编辑器", self.focus_editor, "Ctrl+Alt+E"))
        m_view.addAction(action("下一个标签", lambda: self._next_tab(1), "Ctrl+Tab"))
        m_view.addAction(action("上一个标签", lambda: self._next_tab(-1), "Ctrl+Shift+Tab"))
        m_view.addAction(action("下一个区域", lambda: self.cycle_focus(False), "F6"))
        m_view.addAction(action("上一个区域", lambda: self.cycle_focus(True), "Shift+F6"))
        m_view.addSeparator()
        m_view.addAction(action("专注模式", self.toggle_focus, "F8"))
        m_view.addAction(action("打字机模式", self.toggle_typewriter, "F9"))

        m_help = mb.addMenu("帮助(&H)")
        m_help.addAction(action("检查更新…", self.check_for_updates))
        m_help.addAction(action("命令面板…", self.open_commands, "Ctrl+Shift+P"))
        m_help.addAction(action("设置", lambda: SettingsDialog(self).exec(), "Ctrl+,"))
        m_help.addAction(action("关于", lambda: self.alert(f"MdNote {_version()}")))

    def menu_commands(self):
        self._refresh_recent_menu()
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
        if dialog.chosen and isValid(dialog.chosen):
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
        if not session.flush_pending_edits():
            self.alert("编辑页面尚未就绪，请稍后重试新建。")
            return
        if session.dirty and not self._discard_guard(session):
            return
        session.file_path = None
        session.doc.doc_base = session._asset_temp.name
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

    def _clear_find_highlights(self) -> None:
        if self.current and self.current.mode == "live":
            self.current.preview.page().runJavaScript(
                "typeof App !== 'undefined' && App.clearDocumentFind()"
            )

    def _close_find(self) -> None:
        self._clear_find_highlights()
        self.focus_editor()

    def find_text(self, text, forward) -> None:
        session = self.current
        token = self.findbar.begin_search()
        if session and text:
            def report(found, wrapped=""):
                if isValid(self) and isValid(session) and self.current is session:
                    self.findbar.show_result(token, found, wrapped)
            session.find_text(text, forward, report)

    def replace_text(self, find, replacement) -> None:
        session = self.current
        if session and find:
            self.findbar.reset_feedback()
            def report(found, wrapped=""):
                if isValid(self) and isValid(session) and self.current is session:
                    token = self.findbar.begin_search()
                    self.findbar.show_result(token, found, wrapped)
            session.replace_text(find, replacement, report)


    def jump_heading(self, block_index) -> None:
        self.current and self.current.jump_heading(block_index)

    def open_search_result(self, path: str, line: int) -> None:
        session = self._find_session_for_path(path)
        if session is None:
            session = self.open_file(path)
            if session is None:
                return
        else:
            self.tabs.setCurrentIndex(self.tabs.indexOf(session))
        # 打开后定位到目标行（源码模式按行跳转；渲染模式定位块）
        if session is not None and line > 0:
            if session.mode == "source":
                session.source.goto_line(line)
            else:
                self._locate_line_in_live(session, path, line)

    def _locate_line_in_live(self, session: EditorSession, path: str, line: int) -> None:
        """渲染后模式：按文件行号算出字符偏移，定位到所在块并滚动。"""
        from ..editor.block_model import build_model, find_block_index

        text = session.current_text()
        lines = text.splitlines(keepends=True)
        char_offset = sum(len(l) for l in lines[: line - 1])
        model = build_model(text)
        idx = find_block_index(model, char_offset)
        # 块内行偏移（传给页面以放置光标）
        block = model.blocks[idx]
        in_block = len(block.raw[:char_offset - block.start].encode("utf-16-le")) // 2
        session.editor_command("jumpToLine", idx, in_block)

    def open_folder_dialog(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "打开文件夹")
        if folder:
            self.sidebar.open_folder(folder)
            self.sidebar.show()
            self._patch_settings(last_folder=folder, sidebar_visible=True, sidebar_tab="files")

    def toggle_sidebar(self) -> None:
        if self.sidebar.isVisible():
            self.sidebar.hide()
            self.focus_editor()
        else:
            self.sidebar.show()
            self.sidebar.focus_current()

    def toggle_focus(self) -> None:
        s = settings_service().current
        self._patch_settings(focus_mode=not s.focus_mode)

    def toggle_typewriter(self) -> None:
        s = settings_service().current
        self._patch_settings(typewriter_mode=not s.typewriter_mode)

    # =========================================================
    #  导出
    # =========================================================

    def _current_text(self) -> str:
        return self.current.current_text() if self.current else ""

    def _export_base(self) -> str | None:
        return self.current.doc.doc_base if self.current else None

    def _export_busy(self) -> bool:
        if self._export_jobs:
            self.alert("已有导出任务正在进行，请等待完成。")
            return True
        return False

    def _track_export(self, job, path: str) -> None:
        self._export_jobs.add(job)
        self._show_operation("正在导出…")
        def finished(ok: bool, error: str):
            self._export_jobs.discard(job)
            if not isValid(self) or self._closing:
                return
            self._show_operation(f"已导出：{Path(path).name}" if ok else "")
            if not ok:
                self.alert(f"导出失败：{error or '未能生成文件'}")
        job.finished.connect(finished)

    def export_html(self) -> None:
        if self._export_busy():
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 HTML", "export.html", "HTML (*.html)")
        if path:
            try:
                exporter.export_html(path, self._current_text(), doc_base=self._export_base())
            except (OSError, ValueError) as exc:
                self.alert(f"导出失败：{exc}")
            else:
                self._show_operation(f"已导出：{Path(path).name}")

    def export_pdf(self) -> None:
        if self._export_busy():
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出 PDF", "export.pdf", "PDF (*.pdf)")
        if path:
            try:
                job = exporter.export_pdf(self._current_text(), path,
                                          doc_base=self._export_base(), parent=self)
                self._track_export(job, path)
            except (OSError, ValueError) as exc:
                self.alert(f"导出失败：{exc}")

    def export_image_file(self, fmt) -> None:
        if self._export_busy():
            return
        ext = "png" if fmt == "PNG" else "jpg"
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出 {fmt}", f"export.{ext}", f"{fmt} (*.{ext})"
        )
        if path:
            try:
                standalone = exporter.build_standalone_html(
                    self._current_text(), doc_base=self._export_base()
                )
                self._track_export(exporter.export_image(standalone, path, fmt, parent=self), path)
            except (OSError, ValueError) as exc:
                self.alert(f"导出失败：{exc}")

    def export_pandoc(self, fmt) -> None:
        if self._export_busy():
            return
        if not exporter.pandoc_available():
            self.alert("未检测到 Pandoc：https://pandoc.org/installing.html")
            return
        ext = "tex" if fmt == "latex" else fmt
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出 {fmt.upper()}", f"export.{ext}", f"{fmt.upper()} (*.{ext})"
        )
        if path:
            try:
                job = exporter.pandoc_export(self._current_text(), fmt, path,
                                            doc_base=self._export_base(), parent=self)
                self._track_export(job, path)
            except (OSError, ValueError) as exc:
                self.alert(f"导出失败：{exc}")

    # =========================================================
    #  自动更新
    # =========================================================

    def _wire_updater(self) -> None:
        self.updater.update_available.connect(self._on_update_available)
        self.updater.check_failed.connect(
            lambda msg: self._on_update_error("检查更新", msg)
        )
        self.updater.download_progress.connect(self._on_download_progress)
        self.updater.download_finished.connect(self._on_download_finished)
        self.updater.download_failed.connect(
            lambda msg: self._on_update_error("更新", msg)
        )
        self.updater.check_finished.connect(self._on_check_finished)
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setSingleShot(True)
        self._update_check_timer.timeout.connect(lambda: self.updater.check(silent=True))
        if settings_service().current.auto_check_updates and self.updater._url:
            self._update_check_timer.start(1500)

    def check_for_updates(self) -> None:
        if not self.updater._url:
            self.alert("尚未配置更新源，请在设置中填写 HTTPS 更新清单地址。")
            return
        if self.updater.busy or self.updater.checking:
            self.alert("更新任务正在进行，请稍后再试。")
            return
        self._manual_update_check = True
        self._show_operation("正在检查更新…")
        self.updater.check(silent=False)

    def _on_check_finished(self, newer: bool) -> None:
        manual, self._manual_update_check = self._manual_update_check, False
        if self.updater.busy:
            self._show_operation("正在下载更新…")
        elif manual:
            self._show_operation("发现新版本" if newer else "当前已是最新版本")

    def _on_update_error(self, action: str, message: str) -> None:
        if self._closing:
            return
        self._manual_update_check = False
        self._show_operation()
        self.alert(f"{action}失败：{message}")

    def _on_update_available(self, release) -> None:
        required = self.updater.required()
        title = "发现新版本" if not required else "发现重要更新"
        box = QMessageBox(self)
        box.setWindowTitle(title)
        notes = release.notes.strip() or "（未提供更新说明）"
        box.setText(f"新版本 {release.version} 可用（当前 {self.updater._current}）")
        box.setInformativeText(notes)
        now = box.addButton(
            "立即下载" if not required else "立即更新",
            QMessageBox.AcceptRole,
        )
        later = box.addButton(
            "稍后" if not required else "退出",
            QMessageBox.RejectRole,
        )
        box.setDefaultButton(now)
        box.exec()
        if box.clickedButton() is now:
            self._download_message = box
            self.updater.download()

    def _on_download_progress(self, percent: int) -> None:
        self._show_operation(f"正在下载更新… {percent}%")

    def _on_download_finished(self, path: str) -> None:
        import sys
        from ..services.installer_service import launch_installer

        self._show_operation("更新安装包已校验")
        installed = bool(getattr(sys, "frozen", False))
        if installed and not self.close():
            self.alert(f"安装包已准备好，请保存并退出后运行：\n{path}")
            return
        try:
            launch_installer(path)
        except (OSError, ValueError) as exc:
            self.alert(f"无法启动安装程序：{exc}\n可稍后手动打开：\n{path}")

    # =========================================================
    #  外部文件改动
    # =========================================================

    def _arm_watcher(self, path: str | None = None) -> None:
        desired = {
            str(Path(session.file_path).resolve())
            for index in range(self.tabs.count())
            if isinstance(session := self.tabs.widget(index), EditorSession)
            and session.file_path and Path(session.file_path).exists()
        }
        watched = set(self._file_watcher.files())
        if stale := watched - desired:
            self._file_watcher.removePaths(list(stale))
        if missing := desired - watched:
            self._file_watcher.addPaths(list(missing))

    def _on_tab_changed(self, _index) -> None:
        session = self.current
        self._arm_watcher()
        self.request_status()
        self.findbar.reset_feedback()
        self._clear_find_highlights()
        if session:
            if session.file_path:
                self._on_external_change(session.file_path, force=True)
            session.refresh_outline()

    def _on_external_change(self, path: str, force: bool = False) -> None:
        session = self._find_session_for_path(path)
        # Atomic replacement can remove one watcher even while other files remain watched.
        self._arm_watcher()
        if not session:
            return
        try:
            disk = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError):
            return
        if disk == session._disk_text:
            return
        if disk == session.current_text():
            session._disk_text = disk
            session._external_notice = None
            session.set_dirty(False)
            return
        if session is not self.current:
            return  # Recheck on activation; autosave independently checks its disk version.
        if session.dirty:
            if session._external_notice == disk and not force:
                return
            session._external_notice = disk
            if not self.confirm("文件已被其他程序修改，是否重新载入？（未保存的修改将丢失）"):
                # Not acknowledged: a later activation must be able to recheck.
                session._external_notice = None
                return  # Do not acknowledge a disk version we have chosen not to load.
        session._disk_text = disk
        session._external_notice = None
        session._autosave_error_token = None
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
        discard_b = box.addButton("不保存", QMessageBox.DestructiveRole)
        cancel_b = box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_b:
            return session.do_save(False)
        return clicked is discard_b

    def _restore_session(self) -> None:
        svc = settings_service()
        s = svc.current

        # 内容装载进 __init__ 已创建的初始标签，避免多出一个空标签
        session = self._initial_session
        if s.last_file and Path(s.last_file).exists():
            text = self._read_document(s.last_file)
            if text is not None:
                session.file_path = s.last_file
                session._disk_text = text
                session.doc.doc_base = str(Path(s.last_file).parent)
                session.load_text(text)
                session.set_dirty(False)
                self._arm_watcher(s.last_file)
                self._push_recent(s.last_file)
            else:
                session.load_text(WELCOME)
                session.set_dirty(False)
        else:
            session.load_text(WELCOME)
            session.set_dirty(False)

        if s.sidebar_visible:
            self.sidebar.show()
        if s.last_folder:
            self.sidebar.open_folder(s.last_folder)
        self.request_status()

    def closeEvent(self, event) -> None:
        # Flush every surface first so debounced/atom edits count as dirty.
        for i in range(self.tabs.count()):
            session = self.tabs.widget(i)
            if isinstance(session, EditorSession):
                if not session.flush_pending_edits():
                    self.alert("编辑页面尚未就绪，请稍后重试退出。")
                    event.ignore()
                    return
        dirty_sessions = [
            self.tabs.widget(i)
            for i in range(self.tabs.count())
            if isinstance(self.tabs.widget(i), EditorSession)
            and self.tabs.widget(i).dirty
        ]
        if not dirty_sessions:
            self._finish_close(event)
            return
        box = QMessageBox(self)
        box.setWindowTitle("MdNote")
        box.setText(f"有 {len(dirty_sessions)} 个文档尚未保存")
        save_b = box.addButton("全部保存", QMessageBox.AcceptRole)
        discard_b = box.addButton("全部不保存", QMessageBox.DestructiveRole)
        cancel_b = box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is not save_b and clicked is not discard_b:
            event.ignore()
        elif clicked is save_b:
            # 任一文档保存被取消（如另存为）则不退出
            if all(session.do_save(False) for session in dirty_sessions):
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

        if event.isAccepted():
            self._finish_close(event)

    def _finish_close(self, event) -> None:
        if self.sidebar.shutdown_search():
            self._closing = True
            self._update_check_timer.stop()
            self.updater.shutdown()
            for job in tuple(self._export_jobs):
                job.cancel()
            settings_service().off_change(self._on_settings_changed)
            event.accept()
        else:
            event.ignore()
            self.alert("搜索任务正在取消，请稍后再次关闭窗口。")

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
