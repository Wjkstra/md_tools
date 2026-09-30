"""Real WebEngine/bridge regression tests: python tests/test_live_editor.py."""
import json
import os
import sys
import time
import unittest
import tempfile
from unittest.mock import patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from mdnote.editor.webview import LiveDocument, WebPreview


class LiveEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setApplicationName("MdNoteRegression")

    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.005)
        self.fail("Timed out waiting for WebEngine")

    def js(self, script):
        result = []
        self.view.page().runJavaScript(script, lambda value: result.append(value))
        self.wait(lambda: bool(result))
        return result[0]

    def setUp(self):
        self.changes = []
        self.doc = LiveDocument(lambda: self.changes.append(True))
        self.doc.set_text("old")
        self.view = WebPreview(self.doc)
        self.view.resize(800, 600)
        self.view.show()
        self.wait(lambda: self.js("typeof App !== 'undefined' && App.blocks.length > 0"))

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def edit(self, text):
        self.js("App.startEdit(0, null, 0)")
        self.js("(() => { const el = document.querySelector('.is-editing');"
                f"el.textContent = {json.dumps(text)};"
                "App.setCaret(el, el.textContent.length);"
                "el.dispatchEvent(new InputEvent('input', {bubbles:true})); })()")
        self.wait(lambda: self.doc.get_text() == text)

    def enter(self):
        self.js("document.querySelector('.is-editing').dispatchEvent("
                "new KeyboardEvent('keydown', {key:'Enter',bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("App.blocks[0].raw") == self.doc.model.blocks[0].raw)

    def load(self, text):
        self.doc.set_text(text)
        self.view.reload_blocks()
        self.wait(lambda: self.js("App.blocks.map(b => b.raw).join('|')") ==
                  "|".join(b.raw for b in self.doc.model.blocks))

    def select(self, start, end):
        self.js("(() => { const el = document.querySelector('.is-editing');"
                "const r = document.createRange();"
                f"r.setStart(el.firstChild, {start}); r.setEnd(el.firstChild, {end});"
                "getSelection().removeAllRanges(); getSelection().addRange(r); })()")

    def key(self, key, extra=""):
        self.js("document.activeElement.dispatchEvent(new KeyboardEvent('keydown', {"
                f"key:{json.dumps(key)}, bubbles:true, cancelable:true {extra}" + "}))")

    def test_emoji_middle_enter(self):
        self.edit("A😀BC")
        self.select(3, 3)  # DOM offsets use UTF-16, Python offsets do not.
        self.key("Enter")
        self.wait(lambda: "\n" in self.doc.get_text())
        self.assertEqual(self.doc.get_text(), "A😀\nBC")
        self.assertEqual(self.js("App.textOffset(document.activeElement, getSelection().anchorNode, getSelection().anchorOffset)"), 4)

    def test_native_keyboard_typing_and_enter(self):
        self.load("")
        self.js("App.startEdit(0,null,0)")
        QTest.keyClicks(self.view.focusProxy(), "hello")
        self.wait(lambda: self.doc.get_text() == "hello")
        QTest.keyClick(self.view.focusProxy(), Qt.Key.Key_Return)
        self.wait(lambda: self.js("App.editingIndex") == 1)
        QTest.keyClicks(self.view.focusProxy(), "next")
        self.wait(lambda: self.doc.get_text() == "hello\nnext")

    def test_code_block_enter_stays_inside_block(self):
        self.load("```python\nprint(1)\n```")
        self.js("App.startEdit(0,null,18)")
        self.key("Enter")
        self.wait(lambda: self.js("!App.pendingTransform"))
        self.assertEqual(self.doc.get_text(), "```python\nprint(1)\n\n```")
        self.assertEqual(self.js("App.blocks[App.editingIndex].type"), "code")

    def test_reverse_selection_replacement(self):
        self.edit("abcdef")
        self.js("getSelection().setBaseAndExtent(document.activeElement.firstChild,4,document.activeElement.firstChild,2)")
        self.key(" ")
        self.wait(lambda: self.doc.get_text() == "ab ef")

    def test_switch_block_after_paste_changes_block_count(self):
        self.load("old\n\ntarget")
        self.js("App.startEdit(0,null,0); document.activeElement.textContent='one\\n\\ntwo'; App.syncDraft()")
        self.js("document.querySelector('.block[data-index=\"1\"]').dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("App.editingIndex") == 2)
        self.assertEqual(self.js("App.editingRaw()"), "target")
        self.assertEqual(self.doc.get_text(), "one\n\ntwo\n\ntarget")

    def test_enter_replaces_selection(self):
        self.edit("abcdef")
        self.select(2, 4)
        self.key("Enter")
        self.wait(lambda: "\n" in self.doc.get_text())
        self.assertEqual(self.doc.get_text(), "ab\nef")

    def test_space_replaces_selection(self):
        self.edit("abcdef")
        self.select(2, 4)
        self.key(" ")
        self.wait(lambda: " " in self.doc.get_text())
        self.assertEqual(self.doc.get_text(), "ab ef")

    def test_composition_enter_does_not_split(self):
        self.edit("中文")
        self.key("Enter", ", isComposing:true")
        self.assertEqual(self.doc.get_text(), "中文")
        self.assertEqual(self.js("App.editingRaw()"), "中文")

    def test_consecutive_enters(self):
        self.edit("abc")
        self.js("for (let i=0;i<2;i++) document.activeElement.dispatchEvent("
                "new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));")
        self.wait(lambda: self.doc.get_text().endswith("\n"))
        # A bridge roundtrip ensures both requests have completed.
        self.js("App.bridge.loadBlocks(() => {window.__done = true})")
        self.wait(lambda: self.js("window.__done === true"))
        self.assertEqual(self.doc.get_text(), "abc\n\n")

    def test_typing_while_enter_response_is_delayed(self):
        self.edit("abc")
        self.js("(() => { const transform=App.bridge.transform.bind(App.bridge);"
                "App.bridge.transform=(i,c,o,r,cb)=>transform(i,c,o,r,s=>setTimeout(()=>cb(s),80));"
                "document.activeElement.dispatchEvent(new KeyboardEvent('keydown',"
                "{key:'Enter',bubbles:true,cancelable:true}));"
                "const e=new InputEvent('beforeinput',{inputType:'insertText',data:'X',bubbles:true,cancelable:true});"
                "if(document.activeElement.dispatchEvent(e)) document.execCommand('insertText',false,'X'); })()")
        self.wait(lambda: self.js("App.editingIndex") == 1)
        self.js("App.bridge.loadBlocks(() => {window.__done = true})")
        self.wait(lambda: self.js("window.__done === true"))
        self.assertEqual(self.doc.get_text(), "abc\nX")
        self.assertEqual(self.js("App.editingRaw()"), "X")

    def test_table_input_syncs_without_blur(self):
        self.load("| A | B |\n| :--- | ---: |\n| one | two |")
        self.js("(() => { const b=document.querySelector('.block-table');"
                "const c=b.querySelector('td'); App.attachTableEditor(b,0,c);"
                "c.textContent='changed'; c.dispatchEvent(new InputEvent('input',{bubbles:true})); })()")
        self.js("App.bridge.loadBlocks(() => {window.__done = true})")
        self.wait(lambda: self.js("window.__done === true"))
        self.assertIn("changed", self.doc.get_text())
        self.assertIn(":---", self.doc.get_text())
        self.assertIn("---:", self.doc.get_text())

    def test_paragraph_to_table_keeps_both_edits(self):
        self.load("old\n\n| A |\n| --- |\n| cell |")
        self.js("App.startEdit(0,null,0); document.activeElement.textContent='changed paragraph'; App.syncDraft()")
        self.js("document.querySelector('td').dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("document.activeElement.tagName") == "TD")
        self.js("document.activeElement.textContent='changed cell'; document.activeElement.dispatchEvent(new InputEvent('input',{bubbles:true}))")
        self.js("App.bridge.loadBlocks(() => {window.__done = true})")
        self.wait(lambda: self.js("window.__done === true"))
        self.assertIn("changed paragraph", self.doc.get_text())
        self.assertIn("changed cell", self.doc.get_text())
        self.assertIn("changed paragraph", self.doc.text)
        self.assertEqual(self.js("App.editingIndex"), -1)

    def test_multiline_paste_replaces_selection(self):
        self.edit("before after")
        self.select(7, 12)
        self.js("(() => {const dt=new DataTransfer(); dt.setData('text/plain','甲\\n乙');"
                "document.activeElement.dispatchEvent(new ClipboardEvent('paste',{clipboardData:dt,bubbles:true,cancelable:true})); })()")
        self.js("App.bridge.loadBlocks(() => {window.__done = true})")
        self.wait(lambda: self.js("window.__done === true"))
        self.assertEqual(self.doc.get_text(), "before 甲\n乙")

    def test_new_input_invalidates_redo(self):
        self.edit("first")
        self.doc.commit(0, "first")
        self.assertTrue(self.doc.undo())
        self.doc.update_draft(0, "replacement")
        self.assertFalse(self.doc.redo())
        self.assertEqual(self.doc.get_text(), "replacement")

    def test_enter_renders_latest_text_and_focuses_empty_block(self):
        self.edit("edited **bold**")
        self.enter()
        self.assertEqual(self.doc.get_text(), "edited **bold**\n")
        self.assertEqual(self.js("document.querySelector('.block strong').textContent"), "bold")
        self.assertTrue(self.js("document.activeElement.classList.contains('is-editing')"))
        self.assertTrue(self.js("document.activeElement.contains(getSelection().anchorNode)"))
        self.assertEqual(self.js("App.editingIndex"), 1)

    def test_input_is_available_to_save_without_blur(self):
        self.edit("unsaved 中文")
        self.assertTrue(self.changes)
        self.assertEqual(self.doc.get_text(), "unsaved 中文")
        self.assertEqual(self.js("App.editingIndex"), 0)

    def test_heading_enter_updates_block_type(self):
        self.doc.set_text("# old")
        self.view.reload_blocks()
        self.wait(lambda: self.js("App.blocks[0].type") == "heading")
        self.edit("# 标题")
        self.enter()
        self.assertEqual(self.js("document.querySelector('h1').textContent"), "标题")
        self.assertEqual(self.js("App.blocks[App.editingIndex].type"), "paragraph")

    def test_reload_uses_array_and_updates_screen(self):
        self.doc.set_text("new document")
        self.view.reload_blocks()
        self.wait(lambda: self.js("App.blocks[0].raw") == "new document")
        self.assertEqual(self.js("document.querySelector('.block').textContent.trim()"), "new document")

    def test_list_continuation(self):
        self.doc.set_text("- item")
        self.view.reload_blocks()
        self.wait(lambda: self.js("App.blocks[0].type") == "list")
        self.edit("- edited")
        self.enter()
        self.assertEqual(self.doc.get_text(), "- edited\n- ")
        self.assertEqual(self.js("App.editingRaw()"), "- edited\n- ")

    def test_draft_undo_redo(self):
        self.edit("changed")
        self.assertTrue(self.doc.undo())
        self.assertEqual(self.doc.get_text(), "old")
        self.assertTrue(self.doc.redo())
        self.assertEqual(self.doc.get_text(), "changed")

    def test_whitespace_roundtrip(self):
        self.doc.set_text("\n\n  text\n\n")
        self.assertEqual(self.doc.get_text(), "\n\n  text\n\n")

    def test_save_autosave_and_mode_switch_with_focused_input(self):
        from mdnote.ui.main_window import MainWindow
        from mdnote.core.settings import settings_service
        with patch.object(MainWindow, "_restore_session"), \
                patch.object(settings_service(), "patch"), tempfile.TemporaryDirectory() as tmp:
            window = MainWindow()
            original_view, original_doc = self.view, self.doc
            try:
                self.view, self.doc = window._preview, window._doc
                self.doc.set_text("old")
                self.wait(lambda: self.js("typeof App !== 'undefined' && App.blocks.length > 0"))
                target = Path(tmp) / "saved.md"
                window._file_path = str(target)
                self.edit("save without blur")
                self.assertTrue(window._do_save(False))
                self.assertEqual(target.read_text(encoding="utf-8"), "save without blur")
                self.edit("autosave without blur")
                window._autosave()
                self.assertEqual(target.read_text(encoding="utf-8"), "autosave without blur")
                window.toggle_mode()
                self.assertEqual(window._source.get_text(), "autosave without blur")
                window._source.set_text("source change")
                window.toggle_mode()
                self.wait(lambda: self.js("App.blocks[0].raw") == "source change")
                window._set_dirty(False)
                window.new_file()
                self.wait(lambda: self.js("App.blocks.length === 1 && App.blocks[0].raw === ''"))
            finally:
                window._set_dirty(False)
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.view, self.doc = original_view, original_doc


if __name__ == "__main__":
    unittest.main()
