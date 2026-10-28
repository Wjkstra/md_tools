"""Geometry and round-trip checks for prose, lists, tasks and export layout."""
import json
import unittest

from mdnote.services.exporter import build_standalone_html
from mdnote.services.html_service import safe_html
from mdnote.services.surface import surface_html
import test_live_editor as live


class TypographyTests(unittest.TestCase):
    setUpClass = classmethod(live.LiveEditorTests.setUpClass.__func__)
    setUp = live.LiveEditorTests.setUp
    tearDown = live.LiveEditorTests.tearDown
    wait = live.LiveEditorTests.wait
    js = live.LiveEditorTests.js
    load = live.LiveEditorTests.load

    def test_root_lists_extend_past_prose_indent_at_different_sizes(self):
        self.load("# 标题\n\n功能介绍：\n\n- 普通列表\n\n1. 有序列表\n\n- [ ] 任务列表")
        for width, size in [(900, 16), (420, 20), (900, 24)]:
            with self.subTest(width=width, size=size):
                self.view.resize(width, 700)
                result = json.loads(self.js("""(()=>{
                  const d=document.getElementById('doc');
                  d.style.fontSize='%dpx';
                  const p=d.querySelector(':scope > p');
                  const start=p.getBoundingClientRect().left+parseFloat(getComputedStyle(p).textIndent);
                  return JSON.stringify([...d.querySelectorAll(':scope > ul,:scope > ol')].map(list=>{
                    const li=list.firstElementChild;
                    return {text:li.getBoundingClientRect().left-start,
                      marker:li.getBoundingClientRect().left-1.4*%d-start};
                  }));
                })()""" % (size, size)))
                self.assertEqual(len(result), 3)
                for item in result:
                    self.assertGreater(item["text"], size)
                    self.assertGreater(item["marker"], 0)

    def test_nested_and_quoted_lists_keep_local_indent(self):
        self.load("说明：\n\n- 父列表\n    - 子列表\n\n> 引用\n>\n> - 引用列表\n\n[toc]\n\n## 小节")
        result = json.loads(self.js("""(()=>{
          const d=document.getElementById('doc');
          return JSON.stringify([...d.querySelectorAll('li > ul,blockquote ul,.atom-toc ul')].map(n=>{
            const c=getComputedStyle(n);return parseFloat(c.paddingInlineStart)/parseFloat(c.fontSize);
          }));
        })()"""))
        self.assertGreaterEqual(len(result), 3)
        for indent in result:
            self.assertAlmostEqual(indent, 1.8, places=2)
        self.assertEqual(self.js("getComputedStyle(document.querySelector('blockquote p')).textIndent"), "0px")

    def test_loose_tasks_wrap_and_stack_blocks_and_roundtrip(self):
        source = "- [ ] **加粗** " + "长任务说明" * 35 + "\n\n    后续段落\n\n    - 子列表"
        self.load(source)
        self.view.resize(420, 700)
        result = json.loads(self.js("""(()=>{
          const li=document.querySelector('#doc > ul > li'), ps=li.querySelectorAll(':scope > p');
          const cb=li.querySelector(':scope > input');
          return JSON.stringify({checkbox:!!cb, display:getComputedStyle(li).display,
            secondBelow:ps[1].getBoundingClientRect().top>=ps[0].getBoundingClientRect().bottom,
            nestedBelow:li.querySelector('ul').getBoundingClientRect().top>=ps[1].getBoundingClientRect().bottom,
            aligned:Math.abs(ps[0].getBoundingClientRect().left-ps[1].getBoundingClientRect().left)<1,
            overflow:document.documentElement.scrollWidth>innerWidth});
        })()"""))
        self.assertTrue(result["checkbox"])
        self.assertEqual(result["display"], "list-item")
        for key in ["secondBelow", "nestedBelow", "aligned"]:
            self.assertTrue(result[key], key)
        self.assertFalse(result["overflow"])
        self.js("App.pushSurface()")
        self.assertIn("- [ ] **加粗**", self.doc.get_text())
        self.assertIn("后续段落", self.doc.get_text())
        self.assertIn("    - 子列表", self.doc.get_text())

    def test_task_shortcut_affects_parent_instead_of_nested_checkbox(self):
        self.load("- 父任务\n    - [x] 子任务")
        self.js("""(()=>{
          const li=document.querySelector('#doc > ul > li');
          const r=document.createRange();r.setStart(li.firstChild,1);r.collapse(true);
          getSelection().removeAllRanges();getSelection().addRange(r);App.toggleCurrentTask();
        })()""")
        self.assertTrue(self.js("document.querySelector('#doc > ul > li').classList.contains('task-list-item')"))
        self.assertTrue(self.js("!!document.querySelector('#doc > ul > li > input.task-checkbox')"))
        self.assertTrue(self.js("document.querySelector('#doc li li input').hasAttribute('checked')"))
        self.js("App.pushSurface()")
        self.assertIn("- [ ] 父任务", self.doc.get_text())
        self.assertIn("- [x] 子任务", self.doc.get_text())

    def test_typed_list_preserves_start_number_and_caret(self):
        for source, start in [("5. 内容", 5), ("- 内容", None)]:
            self.load("正文")
            result = json.loads(self.js("""(()=>{
              const p=document.querySelector('#doc > p');p.textContent=%s;
              App.restoreCaret(p,p.textContent.length);App.tryConvertBlock(p);
              const li=document.querySelector('#doc li');
              return JSON.stringify({text:li.textContent,caret:App.caretOffsetIn(li),
                start:li.parentElement.tagName==='OL'?li.parentElement.start:null});
            })()""" % json.dumps(source)))
            self.assertEqual(result, {"text": "内容", "caret": 2, "start": start})
            self.js("App.pushSurface()")
            self.assertIn(source, self.doc.get_text())

    def test_list_conversion_preserves_preceding_structures_and_undo(self):
        for prefix in ["# 标题", "> 引用", "```python\nprint(1)\n```",
                       "| 列 |\n| --- |\n| 内容 |", "正文\n\n\n", "$$\nx^2\n$$"]:
            with self.subTest(prefix=prefix):
                self.load(prefix + "\n\n- 第一项\n- **第二项**\n\n后文")
                before = self.js("App.captureMarkdown()")
                self.js("""(()=>{
                  const li=document.querySelector('#doc > ul > li:nth-child(2)');
                  App.restoreCaret(li,0);App.setHeadingLevel(2);
                })()""")
                after = self.js("App.captureMarkdown()")
                self.assertIn("## **第二项**", after)
                self.assertIn("后文", after)
                self.js("App.undo()")
                self.assertEqual(self.js("App.captureMarkdown()"), before)
                self.js("App.redo()")
                self.assertEqual(self.js("App.captureMarkdown()"), after)

    def test_native_prose_div_and_image_paragraph_use_appropriate_indent(self):
        self.load("正文\n\n![图片](data:image/png;base64,AA==)")
        self.js("document.getElementById('doc').insertAdjacentHTML('beforeend','<div>新段落</div>')")
        self.assertEqual(self.js("getComputedStyle(document.querySelector('#doc > div:not([class])')).textIndent"), "32px")
        self.assertEqual(self.js("getComputedStyle(document.querySelector('#doc > p:has(img)')).textIndent"), "0px")

    def test_export_shares_geometry_and_preserves_ordered_start(self):
        html = build_standalone_html("正文\n\n5. 第一项\n6. 第二项\n\n- [ ] **任务**\n\n    后续说明")
        self.assertIn('<ol start="5">', html)
        self.view.setHtml(html)
        self.wait(lambda: self.js("!!document.querySelector('.md-document > ol')"))
        result = json.loads(self.js("""(()=>{
          const d=document.querySelector('.md-document'), p=d.querySelector(':scope > p');
          const list=d.querySelector('ol'), c=getComputedStyle(list);
          return JSON.stringify({indent:parseFloat(c.paddingInlineStart)/parseFloat(c.fontSize),
            prose:parseFloat(getComputedStyle(p).textIndent)/parseFloat(c.fontSize),
            task:!!d.querySelector('.task-list-item > input'),start:list.start});
        })()"""))
        self.assertAlmostEqual(result["indent"], 3.8, places=2)
        self.assertEqual(result["prose"], 2)
        self.assertTrue(result["task"])
        self.assertEqual(result["start"], 5)

    def test_list_attributes_and_loose_task_markup_survive_sanitizers(self):
        self.assertIn('start="5"', safe_html('<ol start="5"><li value="8">项目</li></ol>'))
        self.assertIn('value="8"', safe_html('<ol start="5"><li value="8">项目</li></ol>'))
        for source in ["- [ ] 任务", "- [x] 任务\n\n    后续段落"]:
            self.assertIn('class="task-list-item"', surface_html(source))
            self.assertIn('class="task-checkbox"', surface_html(source))
