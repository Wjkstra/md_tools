# -*- coding: utf-8 -*-
"""代码块删除 / 边界删除行为回归。

- 空代码块内 Backspace 整块删除（前文/后文/文档首/相邻代码块/列表边界）。
- 删除后前后段落保持分离、光标落在正确位置，可撤销路径恢复代码块。
- 非空代码块 Backspace 不误删；代码块前 Delete 防护不吞正文。
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

F = "`" * 3


def dispatch(key, target_expr="document.activeElement", **mods):
    opts = ["bubbles:true", "cancelable:true", f"key:{json.dumps(key)}"]
    for name, value in mods.items():
        opts.append(f"{name}:{str(value).lower()}")
    return f"""(()=>{{const t={target_expr};
 t.dispatchEvent(new KeyboardEvent('keydown',{{{','.join(opts)}}}));}})()"""


class CodeDeletionTests(unittest.TestCase):
    setUpClass = classmethod(helpers.LiveEditorTests.setUpClass.__func__)
    setUp = helpers.LiveEditorTests.setUp
    tearDown = helpers.LiveEditorTests.tearDown
    wait = helpers.LiveEditorTests.wait
    js = helpers.LiveEditorTests.js
    load = helpers.LiveEditorTests.load

    def md(self):
        self.assertTrue(self.view.flush_surface())
        return self.doc.get_text()

    def focus_code(self, index=0, offset=0):
        area = f"document.querySelectorAll('.md-code-area')[{index}]"
        self.js(f"(()=>{{const a={area};a.focus();App.selectOffsets(a,{offset});}})()")
        self.wait(lambda: self.js(f"document.activeElement==={area}"))
        return area

    def backspace_in_code(self, index=0, offset=0):
        area = self.focus_code(index, offset)
        self.js("(()=>{const a=%s;a.dispatchEvent(new KeyboardEvent('keydown',"
                "{key:'Backspace',bubbles:true,cancelable:true}));})()" % area)
        self.app.processEvents()
        QTest.qWait(20)

    # -------------------------------------------------- 整块删除
    def test_empty_code_between_paragraphs_removed_and_blocks_stay_separate(self):
        self.load(f"before\n\n{F}python\n\n{F}\n\nafter")
        self.backspace_in_code()
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 0)
        # 两个段落必须仍以空行分隔（不能被合并成一段）
        self.assertEqual(self.md(), "before\n\nafter")
        # 光标落到前一段末尾
        self.assertEqual(self.js("""
(()=>{const e=App.selectionElement().closest('p');
 return JSON.stringify({text:e.textContent,offset:App.caretOffsetIn(e)});})()"""),
            json.dumps({"text": "before", "offset": 6},
                       separators=(",", ":"), ensure_ascii=False))

    def test_empty_code_at_document_start_removed_caret_in_next(self):
        self.load(f"{F}python\n\n{F}\n\nafter")
        self.backspace_in_code()
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 0)
        self.assertEqual(self.md(), "after")
        self.assertEqual(self.js("""
(()=>{const e=App.selectionElement().closest('p');
 return JSON.stringify({text:e.textContent,offset:App.caretOffsetIn(e)});})()"""),
            json.dumps({"text": "after", "offset": 0}, separators=(",", ":")))

    def test_only_empty_code_removed_leaves_blank_paragraph(self):
        self.load(f"{F}python\n\n{F}\n")
        self.backspace_in_code()
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 0)
        self.assertEqual(self.md(), "")
        self.assertTrue(self.js(
            "!!(App.selectionElement() && App.selectionElement().closest('p,div'))"))

    def test_empty_first_of_two_adjacent_codes_moves_focus_into_next(self):
        self.load(f"{F}python\n\n{F}\n\n{F}js\nx=1\n{F}\n")
        self.backspace_in_code(index=0)
        codes = self.js("document.querySelectorAll('.md-code').length")
        self.assertEqual(codes, 1)
        self.assertTrue(self.js(
            "document.activeElement.classList.contains('md-code-area')"))
        self.assertEqual(self.js("App.offsets(document.activeElement).start"), 0)
        self.assertEqual(self.md(), f"{F}js\nx=1\n{F}")

    def test_empty_code_before_list_puts_caret_in_last_item(self):
        self.load(f"- a\n- b\n\n{F}c\n\n{F}\n")
        self.backspace_in_code()
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 0)
        self.assertTrue(self.js("!!App.selectionElement().closest('li')"))
        self.assertIn("- a", self.md())

    def test_nonempty_code_backspace_at_start_does_not_remove(self):
        self.load(f"{F}python\nx=1\n{F}\n")
        self.backspace_in_code()
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)
        self.assertEqual(self.md(), f"{F}python\nx=1\n{F}")

    def test_empty_code_removal_before_paragraph_is_undoable(self):
        self.load(f"before\n\n{F}python\n\n{F}\n\nafter")
        self.backspace_in_code()
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 0)
        self.js("App.undo()")
        self.wait(lambda: self.js("document.querySelectorAll('.md-code').length===1"))
        self.assertEqual(self.md(), f"before\n\n{F}python\n\n{F}\n\nafter")

    def test_empty_mermaid_block_removed_like_normal_code(self):
        self.load(f"{F}mermaid\n\n{F}\n")
        # 空 Mermaid 块初始为预览态（区域隐藏），点击预览进入源码编辑
        self.js("""(()=>{document.querySelector('.md-diagram-preview')
 .dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));})()""")
        area = "document.querySelector('.md-code-area')"
        self.wait(lambda: self.js(f"document.activeElement==={area}"))
        self.js("(()=>{document.querySelector('.md-code-area').dispatchEvent("
                "new KeyboardEvent('keydown',{key:'Backspace',bubbles:true,cancelable:true}));})()")
        self.app.processEvents()
        QTest.qWait(20)
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 0)
        self.assertEqual(self.md(), "")

    # -------------------------------------------------- Delete 防护
    def delete_guard_setup(self, source, selector):
        self.load(source)
        self.js(r"""
((selector)=>{const e=document.querySelector(selector);
 const r=document.createRange();r.selectNodeContents(e);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.getElementById('doc').focus();
 e.dispatchEvent(new KeyboardEvent('keydown',
   {key:'Delete',bubbles:true,cancelable:true}));})""" + "(" + json.dumps(selector) + ")")
        self.app.processEvents()
        QTest.qWait(20)

    def test_delete_at_paragraph_end_before_code_keeps_text(self):
        self.delete_guard_setup(f"before\n\n{F}c\nx=1\n{F}\n", "#doc > p")
        self.assertEqual(self.js("document.querySelector('#doc > p').textContent"),
                         "before")
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)
        self.assertEqual(self.md(), f"before\n\n{F}c\nx=1\n{F}")

    def test_delete_at_heading_end_before_code_keeps_heading(self):
        self.delete_guard_setup(f"## title\n\n{F}c\nx=1\n{F}\n", "#doc h2")
        self.assertEqual(self.js("document.querySelector('#doc h2').textContent"),
                         "title")
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)

    def test_delete_at_quote_end_before_code_keeps_quote(self):
        self.delete_guard_setup(f"> quoted\n\n{F}c\nx=1\n{F}\n", "blockquote p")
        self.assertEqual(self.js("document.querySelector('blockquote p').textContent"),
                         "quoted")

    def test_delete_mid_paragraph_before_code_still_deletes_char(self):
        # 光标不在块末：防护不拦截，原生删除照常（删掉 'f' 和 'o' 之间的字符）
        self.load(f"before\n\n{F}c\nx=1\n{F}\n")
        self.js(r"""
(()=>{const e=document.querySelector('#doc > p');
 const r=App.caretRange(e,3);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 e.dispatchEvent(new KeyboardEvent('keydown',
   {key:'Delete',bubbles:true,cancelable:true}));})()""")
        # 合成事件只验证防护未误判：事件不应被 preventDefault
        prevented = self.js(r"""
(()=>{const e=document.querySelector('#doc > p');
 const r=App.caretRange(e,3);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 const ev=new KeyboardEvent('keydown',{key:'Delete',bubbles:true,cancelable:true});
 e.dispatchEvent(ev);return ev.defaultPrevented;})()""")
        self.assertFalse(prevented)
        self.assertEqual(self.js("document.querySelector('#doc > p').textContent"),
                         "before")

    def test_real_backspace_after_code_is_safe_noop(self):
        # 代码块后一段开头按 Backspace（真实键事件）：代码块保留
        self.load(f"{F}c\nx=1\n{F}\n\nafter")
        self.js(r"""
(()=>{const ps=document.querySelectorAll('#doc p');const p=ps[ps.length-1];
 const r=document.createRange();r.setStart(p.firstChild,0);r.collapse(true);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.getElementById('doc').focus();})()""")
        self.view.setFocus()
        QTest.keyClick(self.view.focusProxy() or self.view, Qt.Key.Key_Backspace)
        self.app.processEvents()
        QTest.qWait(20)
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)
        self.assertEqual(self.md(), f"{F}c\nx=1\n{F}\n\nafter")

    def test_real_backspace_in_only_empty_code_removes_block(self):
        # 真实键事件走一遍主路径（与合成事件互补）
        self.load(f"before\n\n{F}python\n\n{F}\n\nafter")
        area = self.focus_code()
        self.view.setFocus()
        QTest.keyClick(self.view.focusProxy() or self.view, Qt.Key.Key_Backspace)
        self.wait(lambda: self.js("document.querySelectorAll('.md-code').length===0"))
        self.assertEqual(self.md(), "before\n\nafter")


if __name__ == "__main__":
    unittest.main()
