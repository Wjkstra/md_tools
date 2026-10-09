"""Focused regressions for table preservation, virtualized navigation and source input."""
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtWidgets import QApplication
from mdnote.core.settings import AppSettings
from mdnote.editor.source_editor import SourceEditor
from mdnote.editor.transforms import indent_line
import test_live_editor as live_helpers


class SourceReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def editor(self):
        prefs = SimpleNamespace(current=AppSettings())
        patcher = patch("mdnote.editor.source_editor.settings_service", return_value=prefs)
        patcher.start()
        self.addCleanup(patcher.stop)
        editor = SourceEditor()
        self.addCleanup(editor.deleteLater)
        return editor, prefs

    def test_outdent_only_removes_configured_leading_indentation(self):
        self.assertEqual(indent_line("    a\tb\tc", 7, 2, True).text, "  a\tb\tc")
        self.assertEqual(indent_line("        text", 8, 8, True).text, "text")
        self.assertEqual(indent_line("\t\ta\tb", 2, 2, True).text, "\ta\tb")
        self.assertEqual(indent_line("a\tb", 1, 8, True).text, "a\tb")

    def test_goto_line_uses_logical_lines_despite_wrapping(self):
        editor, _ = self.editor()
        editor.resize(180, 200)
        editor.show()
        editor.set_text("long " * 80 + "\nsecond\nthird")
        self.app.processEvents()
        editor.goto_line(2)
        self.assertEqual(editor.textCursor().blockNumber(), 1)
        self.assertEqual(editor.textCursor().positionInBlock(), 0)
        editor.goto_line(999)
        self.assertEqual(editor.textCursor().blockNumber(), 2)

    def test_non_visual_preferences_do_not_rehighlight_source(self):
        editor, prefs = self.editor()
        editor.set_text("# heading\n" * 100)
        with patch.object(editor._highlighter, "set_palette") as update:
            prefs.current.auto_bracket = False
            prefs.current.mermaid = False
            editor.apply_prefs()
            editor.apply_prefs()
            update.assert_not_called()
            prefs.current.theme = "github-dark"
            editor.apply_prefs()
            update.assert_called_once()


class LiveReviewTests(unittest.TestCase):
    setUpClass = classmethod(live_helpers.LiveEditorTests.setUpClass.__func__)
    wait = live_helpers.LiveEditorTests.wait
    js = live_helpers.LiveEditorTests.js
    load = live_helpers.LiveEditorTests.load
    key = live_helpers.LiveEditorTests.key

    def setUp(self):
        self.prefs = SimpleNamespace(current=AppSettings())
        patcher = patch("mdnote.editor.webview.settings_service", return_value=self.prefs)
        patcher.start()
        self.addCleanup(patcher.stop)
        live_helpers.LiveEditorTests.setUp(self)

    tearDown = live_helpers.LiveEditorTests.tearDown

    def test_unchanged_table_focus_and_blur_do_not_rewrite_markdown(self):
        text = "| **Header** | Link |\n| --- | --- |\n| **bold** | [website](https://example.com) |"
        self.load(text)
        self.changes.clear()
        self.js("App.switchTo(0,{cell:0})")
        self.js("document.activeElement.blur()")
        self.wait(lambda: self.js("!App.pendingTransform"))
        self.assertEqual(self.doc.get_text(), text)
        self.assertEqual(self.changes, [])

    def test_editing_one_table_cell_preserves_other_markdown_cells(self):
        text = "| **Header** | Link |\n| --- | --- |\n| **bold** | [website](https://example.com) |"
        self.load(text)
        self.js("App.switchTo(0,{cell:0}); document.activeElement.textContent='Updated'; document.activeElement.dispatchEvent(new InputEvent('input',{bubbles:true}))")
        self.wait(lambda: self.js("!App.pendingTransform"))
        self.assertIn("| Updated | Link |", self.doc.get_text())
        self.assertIn("| **bold** | [website](https://example.com) |", self.doc.get_text())
        self.js("document.activeElement.blur()")
        self.wait(lambda: self.js("!App.pendingTransform"))
        self.assertIn("[website](https://example.com)", self.doc.get_text())

    def test_editing_a_link_cell_keeps_its_href_after_serialization(self):
        text = "| name | link |\n| --- | --- |\n| item | [site](https://example.com) |"
        self.load(text)
        self.js(
            "App.switchTo(0,{cell:3});"
            "const el=document.activeElement;"
            "el.querySelector('a').textContent='renamed';"
            "el.dispatchEvent(new InputEvent('input',{bubbles:true}))"
        )
        self.wait(lambda: self.js("!App.pendingTransform"))
        self.assertIn("[renamed](https://example.com)", self.doc.get_text())

    def test_second_task_checkbox_changes_second_task_and_uppercase_unchecks(self):
        self.load("- [ ] first\n- [X] second")
        self.js("document.querySelectorAll('input.task-checkbox')[1].dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("!App.pendingTransform"))
        self.assertEqual(self.doc.get_text(), "- [ ] first\n- [ ] second")

    def test_find_sees_unmounted_content_and_keeps_current_draft(self):
        text = "\n\n".join(["first"] + ["paragraph " + str(i) for i in range(450)] + ["unique-marker"])
        self.load(text)
        self.js("App.startEdit(0,null,0); document.activeElement.textContent='changed first'; App.syncDraft()")
        result = json.loads(self.js("JSON.stringify(App.findDocument('unique-marker',true))"))
        self.assertEqual(result, {"found": True, "total": 1, "active": 1})
        self.wait(lambda: self.js("!App.pendingTransform"))
        self.assertTrue(self.doc.get_text().startswith("changed first"))
        # Scroll-triggered viewport remount re-applies the find selection asynchronously.
        self.wait(lambda: self.js("getSelection().toString()") == "unique-marker")
        self.assertEqual(self.js("document.activeElement.classList.contains('block-placeholder')"), False)

    def test_directory_target_is_mounted_before_jump(self):
        text = "# start\n\n" + "\n\n".join("paragraph " + str(i) for i in range(450)) + "\n\n# far-target"
        self.load(text)
        self.js("App.jumpToId('far-target')")
        self.wait(lambda: self.js("document.activeElement.textContent.includes('far-target')"))
        self.assertEqual(self.js("document.activeElement.classList.contains('block-placeholder')"), False)

    def test_code_line_numbers_and_mermaid_follow_preferences(self):
        fence = chr(96) * 3
        self.load(fence + "python\nprint(1)\nprint(2)\n" + fence)
        self.js("window.__codeLineNumbers=true; App.applyRenderPrefs()")
        self.assertEqual(self.js("document.querySelector('.code-line-gutter').textContent"), "1\n2")
        self.js("window.__codeLineNumbers=false; App.applyRenderPrefs()")
        self.assertEqual(self.js("document.querySelectorAll('.code-line-gutter').length"), 0)
        self.load(fence + "mermaid\ngraph TD; A-->B\n" + fence)
        self.js("window.__mermaid=false; App.applyRenderPrefs()")
        self.assertEqual(self.js("document.querySelectorAll('.mermaid').length"), 0)
        self.assertTrue(self.js("document.querySelector('pre').textContent.includes('graph TD')"))
        self.js("window.__mermaid=true; App.applyRenderPrefs()")
        self.assertEqual(self.js("document.querySelectorAll('.mermaid').length"), 1)


if __name__ == "__main__":
    unittest.main()
