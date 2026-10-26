"""Heading shortcut / Enter / IME regressions on the continuous surface.

Covers the report where, after Ctrl+1 turned a line into a heading:
- pressing Enter left a bare Chromium <div> where block shortcuts no longer
  worked (Ctrl+number silently failed on that line);
- repeatedly stripping/recreating the heading eventually left the surface in
  a state where neither shortcuts nor "# " markers converted anything;
- typing through an IME right after the conversion dropped the first letters
  raw, because composing input rebuilt the DOM mid-composition.
"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_live_editor as live
from mdnote.core.settings import AppSettings

FIRE = r"""
((init)=>{
  const el=App.selectionElement();
  el.dispatchEvent(new KeyboardEvent('keydown',
    Object.assign({bubbles:true,cancelable:true},init)));
})
"""


class HeadingShortcutTests(live.LiveEditorTests):
    def setUp(self):
        self.prefs = SimpleNamespace(current=AppSettings())
        patcher = patch("mdnote.editor.webview.settings_service",
                        return_value=self.prefs)
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()

    def load(self, text):
        self.doc.set_surface_text(text)
        self.js("App.loadSurface()")
        self.wait(lambda: self.js("App.surfaceReady === true"))

    def caret(self, selector):
        return self.js(
            "var e=document.querySelector(%s);"
            "App.caretOffsetIn(e)" % _js(selector))

    def place_caret(self, selector, offset):
        self.js(r"""
((sel,off)=>{const e=document.querySelector(sel);
 const r=App.caretRange(e,off);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);})
""" + "(" + _js(selector) + "," + str(offset) + ")")

    def markdown(self):
        return self.js("App.captureMarkdown()")

    # ------------------------------------------------------------ fixtures

    def make_heading(self, level=1, text="标题"):
        self.load(text + "\n")
        self.js(r"""
((level)=>{const p=document.querySelector('#doc p');
 const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 p.dispatchEvent(new KeyboardEvent('keydown',
   {key:String(level),ctrlKey:true,bubbles:true,cancelable:true}));
})""" + "(" + str(level) + ")")
        self.wait(lambda: self.js(
            "!!document.querySelector('#doc h%d')" % level))

    # --------------------------------------------------------------- tests

    def test_enter_at_heading_end_starts_paragraph_where_ctrl_number_works(self):
        self.make_heading(1)
        self.js(
            "App.selectionElement().dispatchEvent("
            "new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))")
        # The new line is a real paragraph, not a bare <div>.
        self.assertEqual(
            self.js("App.selectionElement().closest('h1,h2,p,div').tagName"), "P")
        self.js(
            "App.selectionElement().dispatchEvent("
            "new KeyboardEvent('keydown',{key:'2',ctrlKey:true,bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js(
            "document.querySelectorAll('#doc h2').length===1 && "
            "App.selectionElement().closest('h2')!==null"))
        self.assertIn("# 标题", self.markdown())

    def test_enter_in_middle_splits_heading_from_paragraph(self):
        self.make_heading(1, "甲乙丙")
        self.place_caret("#doc h1", 2)
        self.js(
            "document.querySelector('#doc h1').dispatchEvent("
            "new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))")
        self.assertEqual(
            self.js("document.querySelector('#doc h1').textContent"), "甲乙")
        self.assertEqual(
            self.js("document.querySelector('#doc h1+p').textContent"), "丙")
        self.assertEqual(self.caret("#doc h1+p"), 0)

    def test_enter_at_heading_start_inserts_paragraph_before(self):
        self.make_heading(1, "甲乙丙")
        self.place_caret("#doc h1", 0)
        self.js(
            "document.querySelector('#doc h1').dispatchEvent("
            "new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))")
        self.assertEqual(self.js("""
(()=>{const [a,b]=document.querySelector('#doc').children;
 return JSON.stringify([a.tagName,b.tagName,b.textContent]);})()"""),
            '["P","H1","甲乙丙"]')
        self.assertEqual(
            self.js("App.selectionElement().tagName"), "P")

    def test_enter_in_empty_heading_demotes_it_to_paragraph(self):
        self.make_heading(1, "")
        self.assertTrue(self.js("!!document.querySelector('#doc h1')"))
        self.js(
            "document.querySelector('#doc h1').dispatchEvent("
            "new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("!document.querySelector('#doc h1')"))
        self.assertEqual(
            self.js("App.selectionElement().tagName"), "P")

    def test_ctrl_number_works_on_bare_div_left_by_browser(self):
        # Exact DOM Chromium leaves when Enter exits a list/heading.
        self.load("前文\n")
        self.js("""
(()=>{const d=document.getElementById('doc');
 const div=document.createElement('div');div.innerHTML='<br>';
 d.insertBefore(div,d.querySelector('.surface-end'));
 const r=document.createRange();r.selectNodeContents(div);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 div.dispatchEvent(new KeyboardEvent('keydown',
   {key:'3',ctrlKey:true,bubbles:true,cancelable:true}));
})()""")
        self.wait(lambda: self.js("!!document.querySelector('#doc h3')"))

    def test_ctrl_number_converts_every_selected_block_and_collapses(self):
        self.load("甲\n\n乙\n\n丙\n")
        result = self.js(r"""
(()=>{const d=document.getElementById('doc');
 const ps=d.querySelectorAll('p:not(.surface-end)');
 const r=document.createRange();
 r.setStart(ps[0].firstChild,0);
 r.setEnd(ps[2].firstChild,ps[2].textContent.length);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 ps[0].dispatchEvent(new KeyboardEvent('keydown',
   {key:'2',ctrlKey:true,bubbles:true,cancelable:true}));
 const heads=d.querySelectorAll('h2');
 // Typing now must insert text, not replace the selected headings.
 document.execCommand('insertText',false,'x');
 return JSON.stringify({h2:heads.length,collapsed:s.isCollapsed,
   md:HtmlToMd.serialize(d)});
})()""")
        import json as _json
        data = _json.loads(result)
        self.assertEqual(data["h2"], 3)
        self.assertTrue(data["collapsed"])
        # The caret collapsed to the start of the first heading: typing
        # prepends there instead of replacing all selected blocks.
        self.assertTrue(data["md"].startswith("## x甲"))
        self.assertIn("## 乙", data["md"])
        self.assertIn("## 丙", data["md"])

    def test_ime_composition_defers_conversion_until_compositionend(self):
        self.load("前文\n")
        converted_during = self.js(r"""
(()=>{const p=document.querySelector('#doc p');
 const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 p.textContent='# 标题';
 const at=App.caretRange(p,p.textContent.length);at.collapse(true);
 s.removeAllRanges();s.addRange(at);
 p.dispatchEvent(new InputEvent('input',{bubbles:true,
   inputType:'insertCompositionText',data:'# 标题',isComposing:true}));
 const converted=!!document.querySelector('#doc h1');
 p.dispatchEvent(new CompositionEvent('compositionend',
   {bubbles:true,cancelable:true,data:'# 标题'}));
 return JSON.stringify({during:converted,
   after:!!document.querySelector('#doc h1'),
   text:document.querySelector('#doc h1')?.textContent||null});
})()""")
        import json as _json
        data = _json.loads(converted_during)
        self.assertFalse(data["during"])
        self.assertTrue(data["after"])
        self.assertEqual(data["text"], "标题")

    def test_repeated_strip_create_and_enter_keeps_everything_working(self):
        self.make_heading(1)
        for _ in range(15):
            # Backspace at the heading start strips it to a paragraph.
            self.place_caret("#doc h1", 0)
            self.js(
                "App.selectionElement().dispatchEvent("
                "new KeyboardEvent('keydown',"
                "{key:'Backspace',bubbles:true,cancelable:true}))")
            self.assertTrue(self.js(
                "!document.querySelector('#doc h1')"))
            # Ctrl+1 recreates it; the caret must still sit at offset 0.
            self.js(
                "App.selectionElement().dispatchEvent("
                "new KeyboardEvent('keydown',"
                "{key:'1',ctrlKey:true,bubbles:true,cancelable:true}))")
            self.assertTrue(self.js(
                "!!document.querySelector('#doc h1')"))
        # The full user loop: heading -> Enter -> shortcut on the new line.
        self.js("""
(()=>{const h=document.querySelector('#doc h1');
 const r=document.createRange();r.selectNodeContents(h);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 h.dispatchEvent(new KeyboardEvent('keydown',
   {key:'Enter',bubbles:true,cancelable:true}));
 App.selectionElement().dispatchEvent(new KeyboardEvent('keydown',
   {key:'3',ctrlKey:true,bubbles:true,cancelable:true}));
})()""")
        self.assertTrue(self.js("!!document.querySelector('#doc h3')"))
        # The "# " marker still converts on the trailing paragraph.
        end = self.js(r"""
(()=>{const e=document.querySelector('.surface-end');
 const r=document.createRange();r.selectNodeContents(e);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.execCommand('insertText',false,'# 哈希标题');
 return !!document.querySelector('#doc h1');})()""")
        self.assertTrue(end)

    def test_ctrl_heading_in_blockquote_lifts_out_of_quote(self):
        self.load("> 引用文字\n")
        self.assertTrue(self.js("""
(()=>{const p=document.querySelector('blockquote p');
 const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 p.dispatchEvent(new KeyboardEvent('keydown',
   {key:'2',ctrlKey:true,bubbles:true,cancelable:true}));
 return !document.querySelector('blockquote') &&
        !!document.querySelector('#doc h2');
})()"""))
        self.assertIn("## 引用文字", self.markdown())

    def test_ctrl_heading_keeps_caret_offset_and_inline_content(self):
        self.load("ab**cd**ef\n")
        self.place_caret("#doc p", 4)
        self.js(
            "document.querySelector('#doc p').dispatchEvent("
            "new KeyboardEvent('keydown',"
            "{key:'1',ctrlKey:true,bubbles:true,cancelable:true}))")
        self.wait(lambda: self.js("!!document.querySelector('#doc h1 strong')"))
        self.assertEqual(self.caret("#doc h1"), 4)


def _js(value):
    import json
    return json.dumps(value)


if __name__ == "__main__":
    unittest.main()
