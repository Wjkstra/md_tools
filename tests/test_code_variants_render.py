# -*- coding: utf-8 -*-
"""代码块变体渲染、语法支持与保存保真交叉验证。

覆盖：反引号 / 波浪号围栏、缩进代码、引用与列表内围栏、未闭合围栏、
内嵌围栏、信息串附加内容、未知语言回退、多语言 Pygments 高亮、
Mermaid 渲染与报错、代码块与表格 / Front Matter 相邻组合。
"""
import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_live_editor as helpers
from mdnote.editor.block_model import build_model
from mdnote.services.surface import _contains_nested_fence, surface_html

F = "`" * 3
T = "~" * 3


class CodeVariantRenderTests(unittest.TestCase):
    setUpClass = classmethod(helpers.LiveEditorTests.setUpClass.__func__)
    setUp = helpers.LiveEditorTests.setUp
    tearDown = helpers.LiveEditorTests.tearDown
    wait = helpers.LiveEditorTests.wait
    js = helpers.LiveEditorTests.js
    load = helpers.LiveEditorTests.load

    def flush(self):
        self.assertTrue(self.view.flush_surface())
        return self.doc.get_text()

    def body_text(self, index=0):
        return self.js(
            f"HtmlToMd.codeText(document.querySelectorAll('.md-code-area')[{index}])")

    # ----------------------------------------------------- 围栏种类
    def test_three_consecutive_fences_stay_separate(self):
        src = "\n\n".join([f"{F}c\na\n{F}", f"{F}python\nb\n{F}", f"{F}js\nc\n{F}"]) + "\n"
        self.load(src)
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 3)
        labels = json.loads(self.js(
            "JSON.stringify([...document.querySelectorAll('.md-code-lang')]"
            ".map(n=>n.textContent))"))
        self.assertEqual(labels, ["c", "python", "js"])
        self.assertEqual(self.flush(), src.rstrip("\n"))
        types = [b.type for b in build_model(src).blocks if b.type != "paragraph"]
        self.assertEqual(types, ["code", "code", "code"])

    def test_tilde_fence_renders_persistent_editor(self):
        src = f"{T}python\nx=1\n{T}\n"
        self.load(src)
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)
        self.assertEqual(
            self.js("document.querySelector('.md-code').dataset.lang"), "python")
        self.assertEqual(self.body_text(), "x=1")
        self.assertEqual(self.flush(), src.rstrip("\n"))

    def test_indented_code_uses_editor_with_deindented_body(self):
        src = "para\n\n    def f():\n        pass\n"
        self.load(src)
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)
        self.assertEqual(self.body_text(), "def f():\n    pass")
        # 未编辑时逐字保留四空格源码
        self.assertEqual(self.flush(), src.rstrip("\n"))
        block = build_model(src).blocks
        self.assertIn("code", [b.type for b in block])

    def test_unclosed_tilde_fence_keeps_last_line(self):
        src = f"{T}python\nfirst=1\nlast=2"
        self.load(src)
        self.assertIn("last=2", self.body_text())
        self.assertEqual(self.flush(), src)

    def test_embedded_backtick_fence_in_tilde_block_preserved(self):
        body = "\n" + F + 'inside\n' + F
        src = f"{T}\n{body}\n{T}\n"
        self.load(src)
        self.assertEqual(self.body_text(), "\n" + F + "inside\n" + F)
        self.assertEqual(self.flush(), src.rstrip("\n"))

    def test_info_string_extra_text_kept_verbatim_untouched(self):
        src = f"{F}python title='x'\nx=1\n{F}\n"
        self.load(src)
        # 语言只取首个 token，附加信息存在逐字 data-md 中
        self.assertEqual(
            self.js("document.querySelector('.md-code').dataset.lang"), "python")
        self.assertEqual(self.flush(), src.rstrip("\n"))

    def test_unknown_language_falls_back_to_plain_text(self):
        src = f"{F}zz-no-such-lang\nx=1\n{F}\n"
        self.load(src)
        self.assertEqual(
            self.js("document.querySelector('.md-code').dataset.lang"),
            "zz-no-such-lang")
        # 纯文本镜像立即可见，不报错
        self.assertEqual(self.body_text(), "x=1")
        self.assertEqual(self.flush(), src.rstrip("\n"))

    def test_html_in_code_is_escaped_not_live(self):
        src = f"{F}html\n<script>alert(1)</script>\n{F}\n"
        self.load(src)
        self.assertEqual(self.js(
            "document.querySelectorAll('.md-code script').length"), 0)
        self.assertIn("<script>alert(1)</script>", self.body_text())
        self.assertEqual(self.flush(), src.rstrip("\n"))

    # ----------------------------------------------------- 嵌套场景
    def test_quoted_fence_is_verbatim_atom(self):
        src = "> qian\n>\n> " + F + "py\n> x=1\n> " + F
        self.load(src)
        self.assertTrue(self.js("!!document.querySelector('.atom-code-structure')"))
        self.assertEqual(self.flush(), src)
        # 点击原子进入源码编辑
        self.js("""(()=>{document.querySelector('.md-atom').dispatchEvent(
 new MouseEvent('click',{bubbles:true,cancelable:true}));})()""")
        self.assertTrue(self.js("!!App.editingAtom()"))

    def test_quoted_tilde_fence_is_verbatim_atom(self):
        src = "> ~~~py\n> x=1\n> ~~~"
        self.load(src)
        self.assertTrue(self.js("!!document.querySelector('.atom-code-structure')"))
        self.assertEqual(self.flush(), src)

    def test_list_fence_atomized_at_indent_2_and_4(self):
        for indent in ("  ", "    "):
            src = f"- a\n\n{indent}{F}py\n{indent}x=1\n{indent}{F}"
            self.load(src)
            self.assertTrue(self.js("!!document.querySelector('.atom-code-structure')"),
                            f"indent={indent!r}")
            self.assertEqual(self.flush(), src)

    def test_nested_quote_fence_atomized(self):
        src = "> > " + F + "\n> > x\n> > " + F
        self.assertTrue(_contains_nested_fence(src, "blockquote"))
        html = surface_html(src)
        self.assertIn("atom-code-structure", html)

    def test_list_indented_code_at_8_spaces_renders_and_roundtrips(self):
        src = "- a\n\n        x=1"
        self.load(src)
        self.assertEqual(self.flush(), src)
        self.assertEqual(self.js("document.querySelectorAll('#doc ul pre').length"), 1)

    def test_nested_list_fence_atomized(self):
        src = f"- a\n    - b\n\n      {F}py\n      x\n      {F}"
        self.assertTrue(_contains_nested_fence(src, "list"))
        self.load(src)
        self.assertTrue(self.js("!!document.querySelector('.atom-code-structure')"))
        self.assertEqual(self.flush(), src)

    # ----------------------------------------------------- 组合相邻
    def test_code_then_table_and_table_then_code(self):
        code = f"{F}c\nx\n{F}"
        table = "| A |\n| - |\n| 1 |"
        for src, first in ((f"{code}\n\n{table}\n", "md-code"),
                           (f"{table}\n\n{code}\n", "table")):
            self.load(src)
            self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)
            self.assertEqual(self.js("document.querySelectorAll('table').length"), 1)
            md = self.flush()
            self.assertIn(code, md)
            # 表格分隔符被规范化，其余结构保持
            self.assertIn("| A |", md)

    def test_frontmatter_then_code_roundtrips(self):
        src = "---\ntitle: t\n---\n\n# H\n\n" + F + "c\nx\n" + F + "\n"
        self.load(src)
        self.assertTrue(self.js("!!document.querySelector('.atom-frontmatter')"))
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)
        self.assertEqual(self.flush(), src.rstrip("\n"))

    # ----------------------------------------------------- 高亮 / 图表
    def test_pygments_highlight_for_c_python_javascript(self):
        src = "\n\n".join([
            f"{F}c\nint x = 1;\n{F}",
            f"{F}python\ndef f():\n    pass\n{F}",
            f"{F}javascript\nconst y=2;\n{F}",
        ])
        self.load(src)
        self.wait(lambda: self.js(
            "document.querySelectorAll('.md-code-highlight .k,.md-code-highlight .kt',"
            ").length>=3"))

    def test_mermaid_renders_svg_and_invalid_source_shows_error(self):
        self.load(f"{F}mermaid\ngraph TD; A-->B;\n{F}\n")
        self.wait(lambda: self.js("!!document.querySelector('.atom-diagram svg')"))
        self.load(f"{F}mermaid\nthis is not mermaid !!!\n{F}\n")
        # 点击进入编辑态后，空 / 非法源显示错误提示
        self.js("""(()=>{document.querySelector('.md-diagram-preview').dispatchEvent(
 new MouseEvent('click',{bubbles:true,cancelable:true}));})()""")
        area = "document.querySelector('.md-code-area')"
        self.wait(lambda: self.js(f"document.activeElement==={area}"))
        self.js(f"(()=>{{const a={area};App.selectOffsets(a,0,a.textContent.length);}})()")
        self.js("document.execCommand('insertText',false,'')")
        self.wait(lambda: self.js(
            "!!document.querySelector('.diagram-error')"))


if __name__ == "__main__":
    unittest.main()
