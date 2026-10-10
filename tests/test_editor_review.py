"""Source-editor regressions and continuous-surface live regressions."""
import json
import os
import sys
import time
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
    """Regressions on the single continuous contenteditable surface."""
    setUpClass = classmethod(live_helpers.LiveEditorTests.setUpClass.__func__)
    wait = live_helpers.LiveEditorTests.wait
    js = live_helpers.LiveEditorTests.js

    def setUp(self):
        self.prefs = SimpleNamespace(current=AppSettings())
        patcher = patch("mdnote.editor.webview.settings_service", return_value=self.prefs)
        patcher.start()
        self.addCleanup(patcher.stop)
        live_helpers.LiveEditorTests.setUp(self)

    tearDown = live_helpers.LiveEditorTests.tearDown

    def _load(self, text):
        self.doc.set_surface_text(text)
        self.js("App.loadSurface()")
        self.wait(lambda: self.js("App.surfaceReady"))

    def test_one_contenteditable_with_no_inner_edit_blocks(self):
        self._load("# 标题\n\n普通**加粗**。\n\n- 甲\n- 乙\n")
        result = self.js(r"""
(()=>{
  const d = document.getElementById("doc");
  const innerEditable = [...d.querySelectorAll("[contenteditable]")].length;
  return JSON.stringify({
    self: d.getAttribute("contenteditable"),
    inner: innerEditable,
    heading: d.querySelector("h1").textContent,
  });
})()""")
        data = json.loads(result)
        self.assertEqual(data, {"self": "true", "inner": 0, "heading": "标题"})

    def test_native_select_all_covers_whole_document(self):
        text = "# 标题\n\n第一段。\n\n第二段。\n\n- 末项\n"
        self._load(text)
        result = self.js(r"""
(()=>{
  const d = document.getElementById("doc");
  d.focus(); document.execCommand("selectAll");
  const text = getSelection().toString();
  return JSON.stringify({
    heading: text.includes("标题"),
    second: text.includes("第二段"),
    item: text.includes("末项"),
  });
})()""")
        data = json.loads(result)
        self.assertTrue(all(data.values()))

    def test_blank_line_via_enter_is_serialized(self):
        self._load("起始段\n")
        self.js(r"""
(()=>{
  const d = document.getElementById("doc");
  const range = document.createRange();
  range.selectNodeContents(d); range.collapse(false);
  getSelection().removeAllRanges(); getSelection().addRange(range);
  document.execCommand("insertParagraph");
  document.execCommand("insertParagraph");
  document.execCommand("insertText", false, "空行后的文字");
})()""")
        self.js("App.pushSurface()")
        self.wait(lambda: "\n\n\n空行后的文字" in self.doc.get_text())

    def test_find_text_and_atom_presence(self):
        text = ("普通含目标词文字。\n\n```python\nprint(1)\n```\n\n"
                "$$\nx^2\n$$\n")
        self._load(text)
        result = self.js(r"""
(()=>{
  const d = document.getElementById("doc");
  const found = JSON.parse(App.findText("目标词", true));
  return JSON.stringify({
    found: found.found, total: found.total,
    codeAtoms: d.querySelectorAll(".atom-code").length,
    mathAtoms: d.querySelectorAll(".atom-math").length,
  });
})()""")
        data = json.loads(result)
        self.assertEqual(data, {"found": True, "total": 1,
                                "codeAtoms": 1, "mathAtoms": 1})

    def test_atom_source_edit_then_commit(self):
        self._load("```python\nold = 1\n```\n")
        # Click the atom to open its plaintext source editor, change, commit.
        self.js(r"""
(()=>{
  const atom = document.querySelector(".atom-code");
  App.editAtom(atom);
  atom.textContent = "```python\nnew = 2\n```";
  App.commitAtom(true);
})()""")
        self.wait(lambda: self.js("App.surfaceReady"))
        self.assertIn("new = 2", self.doc.get_text())


if __name__ == "__main__":
    unittest.main()
