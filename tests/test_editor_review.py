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

    def _type(self, text):
        """Insert text into the focused end paragraph and fire input."""
        return self.js(r"""
((typed)=>{
  const d=document.getElementById("doc");
  const end=d.querySelector(".surface-end") || (()=>{const p=document.createElement("p");d.appendChild(p);return p;})();
  end.innerHTML="<br>";
  const range=document.createRange(); range.selectNodeContents(end); range.collapse(true);
  const sel=getSelection(); sel.removeAllRanges(); sel.addRange(range);
  document.execCommand("insertText",false,typed);
  end.dispatchEvent(new InputEvent("input",{bubbles:true,inputType:"insertText",data:typed}));
  return true;
})(arguments[0])""".replace("arguments[0]", json.dumps(text)))

    def test_typed_inline_markdown_renders_live(self):
        self._load("")
        self._type("this is **bold** and `code`")
        self.wait(lambda: self.js(
            "document.querySelectorAll('#doc strong').length===1 && "
            "document.querySelectorAll('#doc code').length===1"))
        # Synchronously capture the surface into the Python model.
        self.assertTrue(self.view.flush_surface())
        self.assertIn("**bold**", self.doc.get_text())
        self.assertIn("`code`", self.doc.get_text())

    def test_typed_block_markdown_converts(self):
        self._load("")
        self._type("# Title")
        self.wait(lambda: self.js("!!document.querySelector('#doc h1')"))
        self._type("- item")
        self.wait(lambda: self.js("!!document.querySelector('#doc ul li')"))
        self._type("> quote")
        self.wait(lambda: self.js("!!document.querySelector('#doc blockquote p')"))
        self._type("---")
        self.wait(lambda: self.js("document.querySelectorAll('#doc hr').length>=1"))
        md = self.js("App.captureMarkdown()")
        self.assertIn("# Title", md)
        self.assertIn("- item", md)
        self.assertIn("> quote", md)

    def _select_start(self, selector):
        return self.js(r"""
((sel)=>{const el=document.querySelector(sel);
 if(!el) return false;
 const first=el.firstChild && el.firstChild.nodeType===3 ? el.firstChild : el;
 const r=document.createRange();r.setStart(first,0);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);return true;})
(arguments[0])""".replace("arguments[0]", json.dumps(selector)))

    def test_converting_one_list_item_keeps_sibling_items(self):
        # P1 regression: demoting/converting one item must not delete the
        # other items in the same list.
        for action, expected_middle in [
            ("App.backspaceStripFormat()", "second"),
            ("App.setHeadingLevel(2)", "## second"),
        ]:
            self._load("- first\n- second\n- third\n")
            result = self.js(r"""
((action)=>{const lis=document.querySelectorAll('#doc li');const li=lis[1];
 const r=document.createRange();r.setStart(li.firstChild,0);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 eval(action);
 return HtmlToMd.serialize(document.getElementById('doc'));})
(arguments[0])""".replace("arguments[0]", json.dumps(action)))
            self.assertIn("- first", result)
            self.assertIn(expected_middle, result)
            self.assertIn("- third", result)

    def test_heading_converts_after_exiting_list(self):
        # Exiting a list via Enter leaves a bare <div>; a heading marker typed
        # there must still convert (regression: only <p> hosts were recognised).
        self._load("- item\n")
        self.js(r"""
(()=>{const d=document.getElementById('doc');
 // Reproduce the exact DOM the browser produces after Enter exits a list.
 const div=document.createElement('div');div.appendChild(document.createElement('br'));
 const end=d.querySelector('.surface-end');
 d.insertBefore(div,end);
 const r=document.createRange();r.selectNodeContents(div);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.execCommand('insertText',false,'# Title');
 div.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:'e'}));
})()""")
        self.wait(lambda: self.js("!!document.querySelector('#doc h1')"))
        self.assertEqual(self.js("document.querySelector('#doc h1').textContent"), "Title")

    def test_ctrl_number_sets_heading_and_backspace_demotes(self):
        self._load("普通标题\n")
        self.assertTrue(self._select_start("#doc p"))
        self.js("document.querySelector('#doc p').dispatchEvent("
                "new KeyboardEvent('keydown',{key:'3',ctrlKey:true,bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("!!document.querySelector('#doc h3')"))
        self.assertEqual(self.js("document.querySelector('#doc h3').textContent"), "普通标题")
        # Backspace at the heading start strips it back to a paragraph.
        self.assertTrue(self._select_start("#doc h3"))
        self.js("document.querySelector('#doc h3').dispatchEvent("
                "new KeyboardEvent('keydown',{key:'Backspace',bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("!document.querySelector('#doc h3')"))
        self.assertEqual(self.js("document.querySelector('#doc p').textContent"), "普通标题")

    def test_backspace_at_list_start_demotes_to_paragraph(self):
        self._load("- 列表项\n")
        self.assertTrue(self._select_start("#doc li"))
        self.js("document.querySelector('#doc li').dispatchEvent("
                "new KeyboardEvent('keydown',{key:'Backspace',bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("!document.querySelector('#doc ul')"))
        self.assertEqual(self.js("HtmlToMd.serialize(document.getElementById('doc'))"), "列表项")

    def test_task_checkbox_mousedown_toggles(self):
        self._load("- [ ] 待办\n")
        self.wait(lambda: self.js("!!document.querySelector('.task-checkbox')"))

        def press():
            # Capture-phase mousedown is what flips it inside contenteditable.
            self.js("document.querySelector('.task-checkbox').dispatchEvent("
                    "new MouseEvent('mousedown',{bubbles:true,cancelable:true}))")

        press()
        self.wait(lambda: self.js(
            "document.querySelector('.task-checkbox').hasAttribute('checked')"))
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), "- [x] 待办")
        press()
        self.wait(lambda: self.js(
            "!document.querySelector('.task-checkbox').hasAttribute('checked')"))
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), "- [ ] 待办")

    def test_heading_hint_shown_at_start(self):
        self._load("# 标题\n")
        self.assertTrue(self._select_start("#doc h1"))
        self.js("document.dispatchEvent(new Event('selectionchange'))")
        self.wait(lambda: self.js(
            "(()=>{const e=document.getElementById('heading-hint');"
            "return e&&!e.hidden&&e.textContent==='H1';})()"))

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

    def test_find_text_and_code_presence(self):
        text = ("普通含目标词文字。\n\n```python\nprint(1)\n```\n\n"
                "$$\nx^2\n$$\n")
        self._load(text)
        result = self.js(r"""
(()=>{
  const d = document.getElementById("doc");
  const found = JSON.parse(App.findText("目标词", true));
  return JSON.stringify({
    found: found.found, total: found.total,
    codeBlocks: d.querySelectorAll(".md-code").length,
    codeLang: d.querySelector(".md-code-lang").textContent,
    mathAtoms: d.querySelectorAll(".atom-math").length,
  });
})()""")
        data = json.loads(result)
        self.assertEqual(data, {"found": True, "total": 1,
                                "codeBlocks": 1, "codeLang": "python",
                                "mathAtoms": 1})

    def test_code_block_inline_edit(self):
        self._load("```python\nold = 1\n```\n")
        # Click into the always-editable code area, replace text; it syncs.
        self.js(r"""
(()=>{
  const area = document.querySelector(".md-code-area");
  const range = document.createRange();
  range.selectNodeContents(area); range.collapse(false);
  const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
  document.execCommand("insertText", false, "\nnew = 2");
  App.pushSurface();
})()""")
        self.wait(lambda: "new = 2" in self.doc.get_text())
        self.assertIn("old = 1", self.doc.get_text())


if __name__ == "__main__":
    unittest.main()
