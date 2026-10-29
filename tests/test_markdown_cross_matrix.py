# -*- coding: utf-8 -*-
"""Markdown 全语法交叉组合矩阵。

- 复合文档（frontmatter / 标题 / 列表 / 任务 / 引用 / 表格 / 三种代码块 /
  公式 / 分隔线 / TOC / 引用定义 / 行内 HTML / 行内公式）往返保真且二次渲染幂等。
- 引用定义只原子化真正引用标签的段落（普通行内链接仍可编辑、行内公式正常渲染）。
- 表格后插代码块、公式与代码相邻等交互链。
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
from mdnote.services.surface import (
    _contains_nested_fence,
    _definition_labels,
    _uses_definition,
    surface_html,
)

F = "`" * 3

COMPOSITE = """---
title: demo
---

# 标题一

## 小标题

正文 **加粗** *斜体* `代码` [链接](https://example.com) ~~删除~~ $a+b$。

- 无序 1
- 无序 2
    - 嵌套

1. 有序一
2. 有序二

- [x] 已完成
- [ ] 未完成

> 引用段落
> 续行

| 列一 | 列二 |
| --- | ---: |
| a | b |

```python
def f():
    pass
```

~~~js
let x = 1;
~~~

    indented = 1
        more

$$
E = mc^2
$$

---

[toc]

行内 <kbd>Ctrl</kbd> 与 <mark>标记</mark>。

[ref]: https://x.example "标题"

参见 [ref]。
"""


class CompositeMatrixTests(unittest.TestCase):
    setUpClass = classmethod(helpers.LiveEditorTests.setUpClass.__func__)
    setUp = helpers.LiveEditorTests.setUp
    tearDown = helpers.LiveEditorTests.tearDown
    wait = helpers.LiveEditorTests.wait
    js = helpers.LiveEditorTests.js
    load = helpers.LiveEditorTests.load

    def test_composite_roundtrip_render_and_idempotence(self):
        self.load(COMPOSITE)
        counts = json.loads(self.js(r"""JSON.stringify({
 codes:document.querySelectorAll('.md-code').length,
 frontmatter:document.querySelectorAll('.atom-frontmatter').length,
 mathBlocks:document.querySelectorAll('.atom-math').length,
 toc:document.querySelectorAll('.atom-toc').length,
 refDef:document.querySelectorAll('.atom-reference-def').length,
 refUse:document.querySelectorAll('.atom-reference').length,
 tables:document.querySelectorAll('table').length,
 tasks:document.querySelectorAll('.task-checkbox').length,
 hrs:document.querySelectorAll('hr').length,
 lists:document.querySelectorAll('ul,ol').length,
 headings:document.querySelectorAll('h1,h2').length,
 mathInline:document.querySelectorAll('.math-inline').length,
 katexInline:document.querySelectorAll('.math-inline .katex').length})"""))
        self.assertEqual(counts["codes"], 3)           # python / js / indented
        self.assertEqual(counts["frontmatter"], 1)
        self.assertEqual(counts["mathBlocks"], 1)
        self.assertEqual(counts["toc"], 1)
        self.assertEqual(counts["refDef"], 1)
        self.assertEqual(counts["refUse"], 1)
        self.assertEqual(counts["tables"], 1)
        self.assertEqual(counts["tasks"], 2)
        self.assertEqual(counts["hrs"], 1)
        self.assertGreaterEqual(counts["lists"], 5)
        self.assertEqual(counts["headings"], 2)
        # 行内公式在含普通行内链接的段落中必须照常包装 / 渲染
        self.assertEqual(counts["mathInline"], 1)
        self.assertEqual(counts["katexInline"], 1)
        # 含普通行内链接的段落不被误判为引用原子
        self.assertEqual(self.js(
            "document.querySelectorAll('.atom-reference').length"), 1)

        self.assertTrue(self.view.flush_surface())
        md1 = self.doc.get_text()
        self.assertEqual(md1, COMPOSITE.rstrip("\n"))

        # 二次渲染 -> 捕获，结果幂等
        self.js("App.loadSurface()")
        self.wait(lambda: self.js("App.surfaceReady === true"))
        self.assertTrue(self.view.flush_surface())
        md2 = self.doc.get_text()
        self.assertEqual(md2, md1)

        types = [b.type for b in build_model(md1).blocks]
        for expected in ("frontmatter", "heading", "list", "table", "code",
                         "math", "hr", "toc", "paragraph"):
            self.assertIn(expected, types)

    def test_fence_typed_after_table(self):
        self.load("| A |\n| - |\n| 1 |\n")
        self.js(r"""
(()=>{const p=document.querySelector('.surface-end')||document.querySelector('#doc p:last-child');
 const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
 const s=getSelection();s.removeAllRanges();s.addRange(r);
 document.getElementById('doc').focus();})()""")
        self.view.setFocus()
        before = self.js("window.__mdLastInput||0") or 0
        QTest.keyClicks(self.view.focusProxy() or self.view, F + "c")
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            self.app.processEvents()
            if (self.js("window.__mdLastInput||0") or 0) > before:
                break
            time.sleep(.002)
        QTest.keyClick(self.view.focusProxy() or self.view, Qt.Key.Key_Return)
        self.wait(lambda: self.js(
            "document.querySelectorAll('.md-code').length===1"))
        self.assertTrue(self.view.flush_surface())
        text = self.doc.get_text()
        self.assertIn("| A |", text)
        self.assertIn(F + "c\n\n" + F, text)

    def test_math_block_adjacent_to_code(self):
        src = "$$\nx\n$$\n\n" + F + "c\ny\n" + F + "\n"
        self.load(src)
        self.assertEqual(self.js("document.querySelectorAll('.atom-math').length"), 1)
        self.assertEqual(self.js("document.querySelectorAll('.md-code').length"), 1)
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), src.rstrip("\n"))

    def test_inline_link_paragraph_stays_editable_with_reference_doc(self):
        # 文档含引用定义时，普通行内链接段落必须保持可编辑并正常渲染行内公式
        src = ("[ref]: https://x.example\n\n"
               "see [site](https://example.com) and $x=1$\n\n"
               "use [ref] now\n")
        self.load(src)
        # 只有真正引用标签的段落被原子化（1 个 atom-reference）
        self.assertEqual(self.js(
            "document.querySelectorAll('.atom-reference').length"), 1)
        # 普通行内链接仍是可编辑段落里的 <a>；定义块自己 1 个
        site = self.js(
            "!!document.querySelector('#doc p a[href=\"https://example.com\"]')")
        self.assertTrue(site)
        self.wait(lambda: self.js(
            "document.querySelectorAll('.math-inline .katex').length===1"))


class DefinitionMatchingTests(unittest.TestCase):
    def setUp(self):
        from mdnote.editor.block_model import Block
        self.blocks = []
        for raw in ("[ref]: https://x", "[^1]: note", "*[HTML]: HyperText"):
            self.blocks.append(Block(id="x", type="paragraph", start=0, end=0, raw=raw))

    def test_labels_collected(self):
        labels, abbr = _definition_labels(self.blocks)
        self.assertEqual(labels, {"ref", "^1"})
        self.assertEqual(abbr, {"HTML"})

    def test_uses_definition_matches_only_real_references(self):
        labels, abbr = _definition_labels(self.blocks)
        self.assertTrue(_uses_definition("see [ref] here", labels, abbr))
        self.assertTrue(_uses_definition("see [^1] here", labels, abbr))
        self.assertTrue(_uses_definition("text [x][ref] end", labels, abbr))
        self.assertTrue(_uses_definition("plain HTML page", labels, abbr))
        # 普通行内链接 / 方括号文字不触发
        self.assertFalse(_uses_definition(
            "[site](https://example.com)", labels, abbr))
        self.assertFalse(_uses_definition("just [brackets]", labels, abbr))
        self.assertFalse(_uses_definition("HTML5 page", labels, abbr))

    def test_contains_nested_fence_detection(self):
        self.assertTrue(_contains_nested_fence("> a\n>\n> ```py\n> x\n> ```",
                                               "blockquote"))
        self.assertTrue(_contains_nested_fence("> > ~~~\n> > x\n> > ~~~",
                                               "blockquote"))
        self.assertTrue(_contains_nested_fence("- a\n\n  ```py\n  x\n  ```",
                                               "list"))
        self.assertTrue(_contains_nested_fence("- a\n  > ```\n  > x", "list"))
        self.assertFalse(_contains_nested_fence("普通段落\n```lang\nx\n```",
                                                "paragraph"))
        # 列表 8 空格缩进代码不是围栏，按普通渲染路径处理
        self.assertFalse(_contains_nested_fence("- a\n\n        x = 1", "list"))


if __name__ == "__main__":
    unittest.main()
