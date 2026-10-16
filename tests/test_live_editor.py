"""Continuous-surface WebEngine regression base and core interaction tests.

The live surface is one contenteditable element, so these tests drive the real
page: typing, Enter/blank lines, block crossing, undo and large documents.
"""
import json
import os
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from mdnote.editor.block_model import build_model
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
        self.view = WebPreview(self.doc)
        self.view.resize(900, 700)
        self.view.show()
        self.wait(lambda: self.js(
            "typeof App !== 'undefined' && App.surfaceReady === true"))

    def load(self, text):
        self.doc.set_surface_text(text)
        self.js("App.loadSurface()")
        self.wait(lambda: self.js("App.surfaceReady === true"))

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    # ------------------------------------------------ core ------------------

    def test_native_background_is_opaque_and_not_black(self):
        # Startup must not flash a black native WebEngine rectangle.
        color = self.view.page().backgroundColor()
        self.assertEqual(color.alpha(), 255)
        self.assertFalse(color.red() == 0 and color.green() == 0 and color.blue() == 0)

    def test_typing_appends_and_syncs_markdown(self):
        self.load("开头")
        self.js(r"""
(()=>{
  const d=document.getElementById("doc");
  const p=d.querySelector("p");           // append inside the first paragraph
  const range=document.createRange();
  range.setStart(p.firstChild, p.textContent.length);
  range.collapse(true);
  getSelection().removeAllRanges(); getSelection().addRange(range);
  document.execCommand("insertText", false, "文字");
})()""")
        self.js("App.pushSurface()")
        self.wait(lambda: self.doc.get_text().startswith("开头文字"))

    def test_arrows_and_selection_cross_blocks_natively(self):
        self.load("第一段\n\n第二段\n")
        result = self.js(r"""
(()=>{
  const d=document.getElementById("doc");
  // selection spanning both paragraphs (a range across two editable elements)
  const firstP=d.querySelector("p");
  const lastP=d.querySelectorAll("p")[d.querySelectorAll("p").length-1];
  const range=document.createRange();
  range.setStart(firstP.firstChild||firstP,0);
  range.setEnd(lastP.firstChild||lastP,(lastP.textContent||"").length);
  getSelection().removeAllRanges(); getSelection().addRange(range);
  const text=getSelection().toString();
  return JSON.stringify({crosses:text.includes("第一段")&&text.includes("第二段")});
})()""")
        self.assertTrue(json.loads(result)["crosses"])

    def test_consecutive_enters_create_multiple_blank_lines(self):
        self.load("x\n")
        self.js(r"""
(()=>{
  const d=document.getElementById("doc");
  const range=document.createRange();
  range.selectNodeContents(d); range.collapse(false);
  getSelection().removeAllRanges(); getSelection().addRange(range);
  document.execCommand("insertParagraph");
  document.execCommand("insertParagraph");
  document.execCommand("insertParagraph");
  document.execCommand("insertText",false,"y");
})()""")
        self.js("App.pushSurface()")
        # Three enters => x and y separated by blank lines.
        self.wait(lambda: self.doc.get_text().count("\n") >= 3 and
                  self.doc.get_text().endswith("y"))


if __name__ == "__main__":
    unittest.main()
