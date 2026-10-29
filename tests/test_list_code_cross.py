# -*- coding: utf-8 -*-
"""列表 / 代码块交叉组合与「退出列表后插入代码块失效」回归。

真实 QWebEngine + QTest 键驱动：在无序列表、有序列表、任务列表、嵌套列表
中用 Enter 退出后输入围栏并回车，验证代码块正常插入、语言正确、保存往返
保真、高亮渲染与撤销行为。
"""
import json
import os
import sys
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_live_editor as helpers
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from mdnote.editor.block_model import build_model

F = "`" * 3
T = "~" * 3


class ListCodeCrossTests(unittest.TestCase):
    setUpClass = classmethod(helpers.LiveEditorTests.setUpClass.__func__)
    setUp = helpers.LiveEditorTests.setUp
    tearDown = helpers.LiveEditorTests.tearDown
    wait = helpers.LiveEditorTests.wait
    js = helpers.LiveEditorTests.js
    load = helpers.LiveEditorTests.load

    # ------------------------------------------------------------ helpers
    def key(self, key, modifiers=None):
        if modifiers is None:
            modifiers = Qt.KeyboardModifier.NoModifier
        before = self.js("window.__mdLastInput||0") or 0
        QTest.keyClick(self.view.focusProxy() or self.view, key, modifiers)
        self._await_input(before)

    def type(self, text):
        before = self.js("window.__mdLastInput||0") or 0
        QTest.keyClicks(self.view.focusProxy() or self.view, text)
        self._await_input(before)

    def _await_input(self, before):
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            self.app.processEvents()
            if (self.js("window.__mdLastInput||0") or 0) > before:
                return
            time.sleep(.002)
        QTest.qWait(10)

    def md(self):
        self.assertTrue(self.view.flush_surface())
        return self.doc.get_text()

    def caret_end_of(self, selector):
        self.js(r"""
((selector)=>{const e=document.querySelector(selector);
 const r=document.createRange();r.selectNodeContents(e);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.getElementById('doc').focus();})""" + "(" + json.dumps(selector) + ")")
        self.view.setFocus()

    def exit_list_and_insert(self, opener, lang="python", marker=F):
        """Enter 产生空项、再 Enter 退出列表，输入围栏+语言并回车。"""
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js(
            "document.querySelectorAll('#doc li').length>=2 || "
            "!!document.querySelector('#doc > div')"))
        self.key(Qt.Key.Key_Return)
        # 退出列表：光标应位于不在 ul/ol/li 内的裸块（p 或 div）
        self.wait(lambda: self.js(r"""
(()=>{const e=App.selectionElement();
 const host=e&&e.closest&&e.closest('p,div');
 return !!host && host.id!=='doc' && !host.closest('li,ul,ol');})()"""))
        self.type(marker + lang)
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))

    # ----------------------------------------------------- 回归：三种列表
    def test_unordered_list_exit_then_fence_creates_code(self):
        self.load("- 第一项\n")
        self.caret_end_of("#doc li")
        self.exit_list_and_insert("- 第一项")
        self.assertEqual(
            self.js("document.querySelector('.md-code').dataset.lang"), "python")
        self.assertTrue(self.js(
            "document.activeElement.classList.contains('md-code-area')"))
        self.assertEqual(self.md(), f"- 第一项\n\n{F}python\n\n{F}")
        blocks = [(b.type, b.lang) for b in build_model(self.md()).blocks]
        self.assertIn(("list", None), blocks)
        self.assertIn(("code", "python"), blocks)

    def test_ordered_list_exit_then_fence_creates_code(self):
        self.load("3. 第三项\n")
        self.caret_end_of("#doc li")
        self.exit_list_and_insert("3. 第三项", "rust")
        self.assertEqual(
            self.js("document.querySelector('.md-code').dataset.lang"), "rust")
        text = self.md()
        self.assertEqual(text, f"3. 第三项\n\n{F}rust\n\n{F}")

    def test_task_list_exit_then_fence_creates_code(self):
        self.load("- [ ] 待办事项\n")
        self.caret_end_of("#doc li")
        self.exit_list_and_insert("- [ ] 待办", "go")
        self.assertEqual(
            self.js("document.querySelector('.md-code').dataset.lang"), "go")
        self.assertEqual(self.md(), f"- [ ] 待办事项\n\n{F}go\n\n{F}")

    def test_nested_list_exit_then_fence_creates_code(self):
        self.load("- 父项\n    - 子项\n")
        self.caret_end_of("#doc > ul > li li")
        self.key(Qt.Key.Key_Return)
        # 持续 Enter，直到光标脱离所有列表
        for _ in range(4):
            inside_list = self.js(r"""
(()=>{const e=App.selectionElement();
 return !!(e&&e.closest&&e.closest('li,ul,ol'));})()""")
            if not inside_list:
                break
            self.key(Qt.Key.Key_Return)
        self.assertFalse(self.js(r"""
(()=>{const e=App.selectionElement();
 return !!(e&&e.closest&&e.closest('li,ul,ol'));})()"""))
        self.type(F + "python")
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        text = self.md()
        self.assertIn("- 父项", text)
        self.assertIn(f"{F}python\n\n{F}", text)
        # 代码块必须位于顶层，而不是被吞进列表项
        top_level = self.js("!!document.querySelector('#doc > .md-code')")
        self.assertTrue(top_level, "代码块应是 #doc 的直接子节点")

    # ----------------------------------------------------- 围栏变体
    def test_tilde_fence_after_list_exit(self):
        self.load("- 项目\n")
        self.caret_end_of("#doc li")
        self.exit_list_and_insert("- 项目", "python", marker=T)
        self.assertEqual(self.md(), f"- 项目\n\n{T}python\n\n{T}")

    def test_fence_with_leading_text_after_list_exit(self):
        self.load("- 项目\n")
        self.caret_end_of("#doc li")
        self.key(Qt.Key.Key_Return)
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js(r"""
(()=>{const e=App.selectionElement();
 const h=e&&e.closest&&e.closest('p,div');
 return !!h&&!h.closest('li,ul,ol');})()"""))
        self.type("note" + F + "json")
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        text = self.md()
        self.assertEqual(text, f"- 项目\n\nnote\n\n{F}json\n\n{F}")

    def test_language_suggestions_appear_after_list_exit(self):
        self.load("- 项目\n")
        self.caret_end_of("#doc li")
        self.key(Qt.Key.Key_Return)
        self.key(Qt.Key.Key_Return)
        self.type(F + "py")
        labels = json.loads(self.js(
            "JSON.stringify([...document.querySelectorAll('.md-fence-lang-list button')]"
            ".map(b=>b.dataset.value))"))
        self.assertIn("python", labels)
        # 鼠标选择候选项
        self.js(r"""
(()=>{const b=[...document.querySelectorAll('.md-fence-lang-list button')]
 .find(x=>x.dataset.value==='python');
 b.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}));})()""")
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertEqual(
            self.js("document.querySelector('.md-code').dataset.lang"), "python")
        self.assertEqual(self.md(), f"- 项目\n\n{F}python\n\n{F}")

    # ----------------------------------------------------- 交叉：代码后再列表再代码
    def test_code_list_code_chain_roundtrip(self):
        self.load(f"{F}c\nint a;\n{F}\n")
        area = "document.querySelector('.md-code-area')"
        self.js(f"(()=>{{const a={area};a.focus();App.selectOffsets(a,a.textContent.length);}})()")
        self.wait(lambda: self.js(f"document.activeElement==={area}"))
        # Ctrl+Enter 退出代码块
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.wait(lambda: self.js(r"""
App.selectionElement() && !App.selectionElement().closest('.md-code-area')"""))
        # 输入列表项
        self.type("- middle item")
        self.wait(lambda: self.js("!!document.querySelector('#doc ul')"))
        # 退出列表后再插代码块
        self.key(Qt.Key.Key_Return)
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js(r"""
(()=>{const e=App.selectionElement();
 const h=e&&e.closest&&e.closest('p,div');
 return !!h&&!h.closest('li,ul,ol');})()"""))
        self.type(F + "python")
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("document.querySelectorAll('.md-code').length===2"))
        text = self.md()
        self.assertEqual(text,
                         f"{F}c\nint a;\n{F}\n\n- middle item\n\n{F}python\n\n{F}")
        types = [b.type for b in build_model(text).blocks]
        self.assertEqual([t for t in types if t != "paragraph"],
                         ["code", "list", "code"])
        # 两个代码块都拿到语言标签
        langs = self.js(
            "JSON.stringify([...document.querySelectorAll('.md-code')].map(b=>b.dataset.lang))")
        self.assertEqual(json.loads(langs), ["c", "python"])

    def test_heading_enter_then_fence(self):
        self.load("# 标题\n")
        self.caret_end_of("#doc h1")
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!App.selectionElement().closest('p')"))
        self.type(F + "go")
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertEqual(self.md(), f"# 标题\n\n{F}go\n\n{F}")

    def test_quote_enter_div_then_fence_serializes_quoted(self):
        self.load("> 引用文字\n")
        self.caret_end_of("blockquote p")
        self.key(Qt.Key.Key_Return)
        # Chromium 在引用内生成 div（p/div 均作为围栏宿主）
        self.type(F + "python")
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        text = self.md()
        # 引用内插入的代码块属于引用
        self.assertTrue(text.startswith("> "), text)
        self.assertIn("```python", text)

    # ----------------------------------------------------- 渲染与撤销
    def test_inserted_code_gets_highlight_and_label(self):
        self.load("- 项目\n")
        self.caret_end_of("#doc li")
        self.exit_list_and_insert("- 项目", "c")
        area = "document.querySelector('.md-code-area')"
        self.js(f"(()=>{{const a={area};a.focus();}})()")
        self.type("int x;")
        self.wait(lambda: self.js(
            "!!document.querySelector('.md-code-highlight .k, .md-code-highlight .kt')"))
        self.assertEqual(
            self.js("document.querySelector('.md-code-lang').textContent"), "c")

    def test_undo_restores_fence_text_after_div_conversion(self):
        self.load("- 项目\n")
        self.caret_end_of("#doc li")
        self.exit_list_and_insert("- 项目")
        self.assertTrue(self.js("!!document.querySelector('.md-code')"))
        self.js("App.undo()")
        self.app.processEvents()
        time.sleep(.05)
        self.app.processEvents()
        self.assertFalse(self.js("!!document.querySelector('.md-code')"))
        # 撤销恢复的是宿主段落里可见的围栏原文（保存时反引号会按正文转义）
        self.assertEqual(
            self.js("App.selectionElement().closest('p,div').textContent"),
            F + "python")

    def test_insert_markdown_menu_after_list_exit(self):
        # 工具栏/菜单的 insertMarkdown 路径同样要在裸 div 后正常
        self.load("- 项目\n")
        self.caret_end_of("#doc li")
        self.key(Qt.Key.Key_Return)
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js(r"""
(()=>{const e=App.selectionElement();
 const h=e&&e.closest&&e.closest('p,div');
 return !!h&&!h.closest('li,ul,ol');})()"""))
        source = "\n\n" + F + "c\n\n" + F + "\n\n"
        self.js("App.insertMarkdown(%s)" % json.dumps(source))
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertTrue(self.js(
            "document.activeElement.classList.contains('md-code-area')"))


if __name__ == "__main__":
    unittest.main()
