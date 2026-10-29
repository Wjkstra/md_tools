# -*- coding: utf-8 -*-
"""快捷键全覆盖：连续编辑面内键位、主窗口菜单接线、源码模式格式化。

Surface 层用合成 KeyboardEvent 驱动 document 监听；窗口层通过真实
QAction.trigger 验证接线，并用一次真实 QTest Ctrl+/ 验证快捷键上下文。
"""
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_live_editor as live
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QApplication
from mdnote.core.settings import AppSettings
from mdnote.core import settings as settings_module
from mdnote.core.settings import SettingsService
from mdnote.ui.main_window import MainWindow

F = "`" * 3


def fire(selector, init):
    return ("(()=>{const e=document.querySelector(%s);"
            "e.dispatchEvent(new KeyboardEvent('keydown',"
            "Object.assign({bubbles:true,cancelable:true},%s)));})()"
            % (json.dumps(selector), json.dumps(init)))


class SurfaceShortcutTests(unittest.TestCase):
    setUpClass = classmethod(live.LiveEditorTests.setUpClass.__func__)
    setUp = live.LiveEditorTests.setUp
    tearDown = live.LiveEditorTests.tearDown
    wait = live.LiveEditorTests.wait
    js = live.LiveEditorTests.js
    load = live.LiveEditorTests.load

    def capture(self):
        return self.js("App.captureMarkdown()")

    def select_all_text(self, selector):
        self.js("""
((sel)=>{const e=document.querySelector(sel);
 const r=document.createRange();r.selectNodeContents(e);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.getElementById('doc').focus();})""" + "(" + json.dumps(selector) + ")")

    # ----------------------------------------------- 行内格式
    def test_ctrl_b_i_k_wrap_selection(self):
        self.load("bold word here\n")
        self.select_all_text("#doc p")
        self.js(fire("#doc p", {"key": "b", "ctrlKey": True}))
        self.assertTrue(self.js("!!document.querySelector('#doc p strong')"))
        self.assertIn("**bold word here**", self.capture())

        self.load("italic word\n")
        self.select_all_text("#doc p")
        self.js(fire("#doc p", {"key": "i", "ctrlKey": True}))
        self.assertTrue(self.js("!!document.querySelector('#doc p em')"))
        self.assertIn("*italic word*", self.capture())

        self.load("link text\n")
        self.select_all_text("#doc p")
        self.js(fire("#doc p", {"key": "k", "ctrlKey": True}))
        self.assertIn("[link text](https://)", self.capture())

    def test_ctrl_number_and_zero_convert_blocks(self):
        self.load("标题文本\n")
        self.select_all_text("#doc p")
        self.js(fire("#doc p", {"key": "2", "ctrlKey": True}))
        self.wait(lambda: self.js("!!document.querySelector('#doc h2')"))
        self.assertIn("## 标题文本", self.capture())
        # Ctrl+0 降回正文
        self.js(fire("#doc h2", {"key": "0", "ctrlKey": True}))
        self.wait(lambda: self.js("!document.querySelector('#doc h2')"))
        self.assertNotIn("##", self.capture())

    def test_toggle_current_task_shortcut_handler(self):
        # Ctrl+Shift+Enter 是 QAction 接线（见窗口级用例）；此处验证其页面处理：
        # 普通段落 -> 任务列表项 -> 勾选
        self.load("todo item\n")
        self.select_all_text("#doc p")
        self.js("App.toggleCurrentTask()")
        self.wait(lambda: self.js("!!document.querySelector('.task-list-item')"))
        self.assertIn("- [ ] todo item", self.capture())
        self.js("App.toggleCurrentTask()")
        self.wait(lambda: self.js(
            "document.querySelector('.task-checkbox').hasAttribute('checked')"))
        self.assertIn("- [x] todo item", self.capture())

    # ----------------------------------------------- Backspace 去格式
    def test_backspace_at_start_strips_heading_list_quote(self):
        self.load("# 标题\n")
        self.js("""
(()=>{const e=document.querySelector('#doc h1');
 const r=App.caretRange(e,0);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);})()""")
        self.js(fire("#doc h1", {"key": "Backspace"}))
        self.wait(lambda: self.js("!document.querySelector('#doc h1')"))

        self.load("- 项目\n")
        self.js("""
(()=>{const e=document.querySelector('#doc li');
 const r=App.caretRange(e,0);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);})()""")
        self.js(fire("#doc li", {"key": "Backspace"}))
        self.wait(lambda: self.js("!document.querySelector('#doc ul')"))
        self.assertIn("项目", self.capture())

        self.load("> 引用\n")
        self.js("""
(()=>{const e=document.querySelector('blockquote p');
 const r=App.caretRange(e,0);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);})()""")
        self.js(fire("blockquote p", {"key": "Backspace"}))
        self.wait(lambda: self.js("!document.querySelector('blockquote')"))

    # ----------------------------------------------- 代码块内键位
    def test_code_tab_ctrl_enter_ctrl_a_shortcuts(self):
        self.load(f"{F}c\nx;\n{F}\n")
        area = "document.querySelector('.md-code-area')"
        self.js(f"(()=>{{const a={area};a.focus();App.selectOffsets(a,0);}})()")
        self.wait(lambda: self.js(f"document.activeElement==={area}"))
        # Tab 缩进
        self.js(f"(()=>{{{area}.dispatchEvent(new KeyboardEvent('keydown',"
                "{key:'Tab',bubbles:true,cancelable:true}));})()")
        self.assertEqual(self.js(f"HtmlToMd.codeText({area})"), "    x;")
        # Ctrl+A 局部全选（选区等于代码正文）
        self.js(f"(()=>{{{area}.dispatchEvent(new KeyboardEvent('keydown',"
                "{key:'a',ctrlKey:true,bubbles:true,cancelable:true}));})()")
        self.assertEqual(self.js("getSelection().toString()"), "    x;")
        # Ctrl+Enter 退出
        self.js(f"(()=>{{{area}.dispatchEvent(new KeyboardEvent('keydown',"
                "{key:'Enter',ctrlKey:true,bubbles:true,cancelable:true}));})()")
        self.wait(lambda: self.js(
            "!App.selectionElement().closest('.md-code-area')"))

    def test_escape_closes_fence_completion(self):
        self.load("\n")
        self.js(r"""
(()=>{const p=document.querySelector('#doc p');
 const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.execCommand('insertText',false,'```py');})()""")
        self.wait(lambda: self.js("!!document.querySelector('.md-fence-lang-list')"))
        self.js("document.dispatchEvent(new KeyboardEvent('keydown',"
                "{key:'Escape',bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("!document.querySelector('.md-fence-lang-list')"))


class WindowShortcutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @contextmanager
    def window(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(settings_module, "settings_file",
                              return_value=Path(folder) / "settings.json"):
                svc = SettingsService()
            svc.current.auto_check_updates = False
            with patch.object(settings_module, "_svc", svc), \
                    patch.object(MainWindow, "_restore_session"):
                window = MainWindow()
                window.show()
                self.app.processEvents()
                try:
                    yield window, svc, Path(folder)
                finally:
                    for index in range(window.tabs.count()):
                        window.tabs.widget(index).dirty = False
                    with patch(
                        "mdnote.ui.editor_session.EditorSession.flush_pending_edits",
                        lambda self: True,
                    ):
                        window.close()
                    window.deleteLater()
                    self.app.processEvents()

    def js(self, window, code):
        result = []
        window.current.preview.page().runJavaScript(code, result.append)
        deadline = __import__("time").monotonic() + 4
        while not result and __import__("time").monotonic() < deadline:
            self.app.processEvents()
            __import__("time").sleep(.002)
        self.assertTrue(result, f"JS no return: {code}")
        return result[0]

    def wait_js(self, window, predicate):
        deadline = __import__("time").monotonic() + 6
        while __import__("time").monotonic() < deadline:
            self.app.processEvents()
            if self.js(window, predicate):
                return
            __import__("time").sleep(.005)
        self.fail("timed out: " + predicate)

    def commands(self, window):
        # Keep every QMenu/QAction wrapper alive while walking: under the
        # offscreen platform, dropping a temporary wrapper can delete its
        # underlying C++ QMenu.
        refs = []
        result = {}

        def walk(menu, prefix=""):
            refs.append(menu)
            for act in menu.actions():
                refs.append(act)
                if act.isSeparator():
                    continue
                if act.menu():
                    walk(act.menu(), prefix + act.text().replace("&", "") + " / ")
                else:
                    result[prefix + act.text().replace("&", "")] = act
        walk(window.menuBar())
        window._test_menu_refs = refs
        return result

    def action(self, window, label):
        for title, act in self.commands(window).items():
            if title.endswith(label):
                return act
        raise KeyError(label)

    def md(self, window):
        self.assertTrue(window.current.preview.flush_surface())
        return window.current.doc.get_text()

    # ----------------------------------------------- 编辑菜单接线
    def test_inline_format_actions_in_live_mode(self):
        # 每种格式在全新文档上单独验证（格式渲染会重建内联 DOM 并折叠选区，
        # 这是 Typora 式即时渲染的预期行为）
        for label, selector, marker in (
            ("加粗", "#doc p strong", "**"),
            ("斜体", "#doc p em", "*"),
        ):
            with self.window() as (window, svc, folder):
                session = window.current
                session.load_text("普通文字\n")
                self.wait_js(window, "App.surfaceReady === true")
                self.js(window, r"""
(()=>{const p=document.querySelector('#doc p');
 const r=document.createRange();r.selectNodeContents(p);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.getElementById('doc').focus();})()""")
                self.action(window, label).trigger()
                self.wait_js(window, f"!!document.querySelector('{selector}')")
                self.assertIn(marker, self.md(window))

    def test_insert_actions_in_live_mode(self):
        with self.window() as (window, svc, folder):
            session = window.current
            session.load_text("")
            self.wait_js(window, "App.surfaceReady === true")
            self.action(window, "插入代码块").trigger()
            self.wait_js(window, "!!document.querySelector('.md-code-area')")
            self.assertIn(F + "\n\n" + F, self.md(window))
        with self.window() as (window, svc, folder):
            window.current.load_text("")
            self.wait_js(window, "App.surfaceReady === true")
            self.action(window, "插入表格").trigger()
            self.wait_js(window, "!!document.querySelector('table')")
        with self.window() as (window, svc, folder):
            window.current.load_text("")
            self.wait_js(window, "App.surfaceReady === true")
            self.action(window, "插入分隔线").trigger()
            self.wait_js(window, "!!document.querySelector('hr')")

    def test_strikethrough_inline_code_link_task_actions(self):
        for label, selector, expect in (
            ("删除线", "#doc p del", None),
            ("行内代码", "#doc p code", None),
        ):
            with self.window() as (window, svc, folder):
                window.current.load_text("abc\n")
                self.wait_js(window, "App.surfaceReady === true")
                self.js(window, r"""
(()=>{const p=document.querySelector('#doc p');
 const r=document.createRange();r.selectNodeContents(p);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.getElementById('doc').focus();})()""")
                self.action(window, label).trigger()
                self.wait_js(window, f"!!document.querySelector('{selector}')")

        # 链接：无选区时在光标处插入占位文本链接
        with self.window() as (window, svc, folder):
            window.current.load_text("")
            self.wait_js(window, "App.surfaceReady === true")
            self.js(window, r"""
(()=>{const p=document.querySelector('.surface-end')||document.querySelector('#doc p');
 const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.getElementById('doc').focus();})()""")
            self.action(window, "链接").trigger()
            self.wait_js(window, "!!document.querySelector('#doc p a')")

        # 任务项：普通段落 -> 任务列表
        with self.window() as (window, svc, folder):
            window.current.load_text("todo item\n")
            self.wait_js(window, "App.surfaceReady === true")
            self.js(window, r"""
(()=>{const p=document.querySelector('#doc p');
 const r=document.createRange();r.selectNodeContents(p);
 const s=getSelection();s.removeAllRanges();s.addRange(r);})()""")
            self.action(window, "切换任务完成状态 / 插入任务项").trigger()
            self.wait_js(window, "!!document.querySelector('.task-list-item')")

    def test_undo_redo_actions(self):
        with self.window() as (window, svc, folder):
            session = window.current
            session.load_text("")
            self.wait_js(window, "App.surfaceReady === true")
            self.js(window, r"""
(()=>{const p=document.querySelector('.surface-end')||document.querySelector('#doc p');
 const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.execCommand('insertText',false,'hello');})()""")
            self.wait_js(window,
                "document.querySelector('#doc p').textContent==='hello'")
            self.action(window, "撤销").trigger()
            self.wait_js(window, "document.querySelector('#doc p').textContent===''")
            self.action(window, "重做").trigger()
            self.wait_js(window,
                "document.querySelector('#doc p').textContent==='hello'")

    # ----------------------------------------------- 视图 / 查找
    def test_mode_toggle_sidebar_find_and_focus_flags(self):
        with self.window() as (window, svc, folder):
            self.assertEqual(window.current.mode, "live")
            # 真实快捷键 Ctrl+/ 切换模式
            QTest.keyClick(window, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)
            deadline = __import__("time").monotonic() + 3
            while window.current.mode != "source" and __import__("time").monotonic() < deadline:
                self.app.processEvents()
                __import__("time").sleep(.02)
            self.assertEqual(window.current.mode, "source")
            QTest.keyClick(window, Qt.Key.Key_Slash, Qt.KeyboardModifier.ControlModifier)
            deadline = __import__("time").monotonic() + 3
            while window.current.mode != "live" and __import__("time").monotonic() < deadline:
                self.app.processEvents()
                __import__("time").sleep(.02)
            self.app.processEvents()
            self.assertEqual(window.current.mode, "live")

            before = window.sidebar.isVisible()
            self.action(window, "切换侧边栏").trigger()
            self.app.processEvents()
            self.assertNotEqual(window.sidebar.isVisible(), before)
            self.action(window, "切换侧边栏").trigger()
            self.app.processEvents()

            self.action(window, "专注模式").trigger()
            self.assertTrue(svc.current.focus_mode)
            self.action(window, "打字机模式").trigger()
            self.assertTrue(svc.current.typewriter_mode)

            self.action(window, "查找…").trigger()
            self.app.processEvents()
            self.assertTrue(window.findbar.isVisible())

    def test_new_and_close_tab_actions(self):
        with self.window() as (window, svc, folder):
            count = window.tabs.count()
            self.action(window, "新建标签").trigger()
            self.app.processEvents()
            self.assertEqual(window.tabs.count(), count + 1)
            self.action(window, "关闭标签").trigger()
            self.app.processEvents()
            self.assertEqual(window.tabs.count(), count)

    def test_save_action_writes_file(self):
        with self.window() as (window, svc, folder):
            target = folder / "saved.md"
            session = window.current
            session.load_text("# 已保存\n")
            self.wait_js(window, "App.surfaceReady === true")
            with patch.object(QFileDialog, "getSaveFileName",
                              return_value=(str(target), "")):
                self.action(window, "保存").trigger()
            self.app.processEvents()
            self.assertTrue(target.exists())
            self.assertIn("# 已保存", target.read_text(encoding="utf-8"))

    # ----------------------------------------------- 源码模式
    def test_source_mode_format_and_insert_shortcuts(self):
        with self.window() as (window, svc, folder):
            session = window.current
            session.load_text("abc\n")
            session.toggle_mode()
            self.app.processEvents()
            self.assertEqual(session.mode, "source")
            editor = session.source
            editor.selectAll()
            self.action(window, "加粗").trigger()
            self.assertIn("**abc**", editor.get_text())
            self.action(window, "插入代码块").trigger()
            self.assertIn(F, editor.get_text())
            # 源码模式任务快捷键：光标置于行内时把该行转为任务项
            editor.set_text("plain line")
            cursor = editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.StartOfLine)
            editor.setTextCursor(cursor)
            self.action(window, "切换任务完成状态 / 插入任务项").trigger()
            self.assertIn("- [ ] plain line", editor.get_text())
            # 全选全文快捷键切到源码模式并全选
            session.toggle_mode()
            self.app.processEvents()
            self.action(window, "全选全文（源码模式）").trigger()
            self.app.processEvents()
            self.assertEqual(session.mode, "source")


if __name__ == "__main__":
    unittest.main()
