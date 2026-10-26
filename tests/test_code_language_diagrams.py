"""Code fence completion and persistent Mermaid editing in real WebEngine."""
import json
import unittest

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
import test_code_table_experience as code_helpers


class LanguageDiagramTests(unittest.TestCase):
    setUpClass = classmethod(code_helpers.CodeTableExperienceTests.setUpClass.__func__)
    setUp = code_helpers.CodeTableExperienceTests.setUp
    tearDown = code_helpers.CodeTableExperienceTests.tearDown
    wait = code_helpers.CodeTableExperienceTests.wait
    js = code_helpers.CodeTableExperienceTests.js
    load = code_helpers.CodeTableExperienceTests.load
    code = code_helpers.CodeTableExperienceTests.code
    code_text = code_helpers.CodeTableExperienceTests.code_text
    code_focus = code_helpers.CodeTableExperienceTests.code_focus
    key = code_helpers.CodeTableExperienceTests.key
    type = code_helpers.CodeTableExperienceTests.type
    _await_input = code_helpers.CodeTableExperienceTests._await_input
    caret_at_end = code_helpers.CodeTableExperienceTests.caret_at_end

    def diagram(self, source='flowchart TB\n  A[开始] --> B[完成]'):
        self.load('```mermaid\n' + source + '\n```\n\n后文')
        self.wait(lambda: self.js("!!document.querySelector('.md-diagram-preview svg')"))

    def edit_diagram(self):
        self.js("document.querySelector('.md-diagram-preview').click()")
        self.code_focus()

    def replace_source(self, source):
        self.js("""(()=>{const a=document.querySelector('.md-code-area');
          App.selectOffsets(a,0,HtmlToMd.codeText(a).length);
          App.applyCodeEdit(a,{start:0,end:HtmlToMd.codeText(a).length,
          text:SOURCE,caret:SOURCE.length});})()""".replace('SOURCE', json.dumps(source)))

    def test_language_focus_opens_full_scrollable_unclipped_catalog(self):
        self.code('short')
        self.js("document.querySelector('.md-code-language').focus()")
        data = json.loads(self.js("""JSON.stringify((()=>{
          const list=document.querySelector('.md-code-lang-list');
          const rect=list.getBoundingClientRect(), block=list.closest('.md-code').getBoundingClientRect();
          const p=document.elementFromPoint(rect.left+30,Math.min(rect.bottom-10,block.bottom+35));
          return {count:list.children.length,scrolls:list.scrollHeight>list.clientHeight,
            visible:!!p?.closest('.md-code-lang-list'),expanded:document.querySelector('.md-code-language').getAttribute('aria-expanded')};
        })())"""))
        self.assertGreater(data['count'], 100)
        self.assertTrue(data['scrolls'])
        self.assertTrue(data['visible'])
        self.assertEqual(data['expanded'], 'true')

    def test_language_keyboard_keeps_input_focus_and_selects_cpp(self):
        self.code('int n;', '')
        self.js("""(()=>{const i=document.querySelector('.md-code-language');i.focus();
          i.value='c++';i.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        self.key(Qt.Key.Key_Down)
        self.assertTrue(self.js("document.activeElement.matches('.md-code-language')"))
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.js("document.querySelector('.md-code').dataset.lang"), 'cpp')
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), '```cpp\nint n;\n```')

    def test_fence_typing_shows_m_suggestions_and_mouse_inserts_mermaid(self):
        self.caret_at_end('')
        self.type('```m')
        labels = json.loads(self.js("JSON.stringify([...document.querySelectorAll('.md-fence-lang-list button')].map(b=>b.dataset.value))"))
        for name in ('makefile', 'mariadb', 'markdown', 'math', 'mathematica', 'matlab', 'mermaid'):
            self.assertIn(name, labels)
        self.js("""[...document.querySelectorAll('.md-fence-lang-list button')].find(b=>b.dataset.value==='mermaid')
          .dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}))""")
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertEqual(self.code_text(), '')
        self.assertTrue(self.js("document.activeElement.matches('.md-code-area')"))
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), '```mermaid\n\n```')

    def test_fence_arrow_keys_choose_language_before_enter(self):
        self.caret_at_end('')
        self.type('```c')
        self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Down)
        chosen = self.js("document.querySelector('.md-fence-lang-list [aria-selected=true]').dataset.value")
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertEqual(self.js("document.querySelector('.md-code').dataset.lang"), chosen)
        self.assertFalse(self.js("!!document.querySelector('.md-fence-lang-list')"))

    def test_fence_enter_completes_mermaid_prefix_and_focuses_new_source(self):
        self.caret_at_end('')
        self.type('```mer')
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("document.querySelector('.md-code')?.dataset.lang==='mermaid'"))
        self.assertTrue(self.js("document.activeElement.matches('.md-code-area')"))

    def test_click_diagram_then_outside_restores_preview_without_rebuilding(self):
        self.diagram()
        original = self.doc.get_text()
        self.js("window.originalArea=document.querySelector('.md-code-area')")
        for _ in range(2):
            self.edit_diagram()
            self.assertEqual(self.js("getComputedStyle(document.querySelector('.md-code-scroll')).display"), 'block')
            self.js("""document.querySelector('#doc > p:last-child').dispatchEvent(
              new MouseEvent('mousedown',{bubbles:true}))""")
            self.assertEqual(self.js("getComputedStyle(document.querySelector('.md-code-scroll')).display"), 'none')
            self.assertTrue(self.js("!!document.querySelector('.md-diagram-preview svg')"))
        self.assertTrue(self.js("originalArea===document.querySelector('.md-code-area')"))
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), original)

    def test_real_mouse_clicks_restore_diagram_and_copy_hidden_source(self):
        self.diagram('graph TD; A-->B;')
        def click(selector):
            point=json.loads(self.js("""JSON.stringify((()=>{const r=document.querySelector(SELECTOR).getBoundingClientRect();
              return [r.left+r.width/2,r.top+r.height/2];})())""".replace('SELECTOR',json.dumps(selector))))
            QTest.mouseClick(self.view.focusProxy() or self.view,Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier,QPoint(round(point[0]),round(point[1])))
        click('.md-diagram-preview')
        self.wait(lambda: self.js("document.querySelector('.md-code').classList.contains('is-diagram-editing')"))
        click('#doc > p:last-child')
        self.wait(lambda: self.js("getComputedStyle(document.querySelector('.md-code-scroll')).display==='none'"))
        click('.md-code-copy')
        self.wait(lambda: self.app.clipboard().text()=='graph TD; A-->B;')

    def test_live_source_updates_preview_and_ctrl_enter_saves_it(self):
        self.diagram()
        self.edit_diagram()
        source='flowchart TB\n U[运维人员 / 告警事件] --> W[运维工作台 / API 网关]\n W --> O[Agent 编排与任务状态管理]\n O <--> P[任务规划与决策 LLM]\n O --> A[监控分析 Agent]\n A --> T[工具网关: 权限 / 参数 / 审计]\n T --> D[Prometheus / 日志系统]'
        self.replace_source(source)
        self.wait(lambda: self.js("document.querySelector('.md-diagram-preview svg')?.textContent.includes('Prometheus')"))
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.js("getComputedStyle(document.querySelector('.md-code-scroll')).display"), 'none')
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), '```mermaid\n'+source+'\n```\n\n后文')
        self.js('App.loadSurface()')
        self.wait(lambda: self.js("!!document.querySelector('.md-diagram-preview svg')"))

    def test_escape_keeps_edits_and_native_undo_still_works(self):
        self.diagram('graph TD; A-->B;')
        self.edit_diagram()
        self.type(' ')
        self.key(Qt.Key.Key_Escape)
        self.edit_diagram()
        self.js('App.undo()')
        self.assertEqual(self.code_text(), 'graph TD; A-->B;')

    def test_invalid_diagram_shows_source_and_recovers_after_correction(self):
        self.code('flowchart TB\n A[broken', 'mermaid')
        self.wait(lambda: self.js("!!document.querySelector('.diagram-error')"))
        self.assertNotEqual(self.js("getComputedStyle(document.querySelector('.md-code-scroll')).display"), 'none')
        self.edit_diagram()
        self.replace_source('sequenceDiagram\n Alice->>Bob: Hello')
        self.wait(lambda: self.js("document.querySelector('.md-diagram-preview svg')?.textContent.includes('Hello')"))
        self.assertFalse(self.js("!!document.querySelector('.diagram-error')"))

    def test_changing_plain_code_language_to_mermaid_renders_in_place(self):
        self.code('classDiagram\n Animal <|-- Duck', '')
        self.js("""(()=>{const i=document.querySelector('.md-code-language');i.focus();
          i.value='mermaid';i.dispatchEvent(new Event('change'));})()""")
        self.wait(lambda: self.js("!!document.querySelector('.md-diagram-preview svg')"))
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), '```mermaid\nclassDiagram\n Animal <|-- Duck\n```')
        self.js("""(()=>{const i=document.querySelector('.md-code-language');i.value='text';
          i.dispatchEvent(new Event('change'));})()""")
        self.assertFalse(self.js("!!document.querySelector('.md-diagram-preview svg')"))
        self.assertNotEqual(self.js("getComputedStyle(document.querySelector('.md-code-scroll')).display"), 'none')

    def test_mermaid_preference_off_on_restores_source_then_svg(self):
        self.diagram()
        self.js('window.__mermaid=false;App.applyCodePrefs()')
        self.assertFalse(self.js("!!document.querySelector('.md-diagram-preview svg')"))
        self.assertNotEqual(self.js("getComputedStyle(document.querySelector('.md-code-scroll')).display"), 'none')
        self.js('window.__mermaid=true;App.applyCodePrefs()')
        self.wait(lambda: self.js("!!document.querySelector('.md-diagram-preview svg')"))

    def test_late_render_cannot_overwrite_newer_source(self):
        self.diagram()
        self.edit_diagram()
        self.js("""(()=>{const render=mermaid.render.bind(mermaid);
          mermaid.render=(id,source)=>render(id,source).then(result=>source.includes('Old')?
            new Promise(resolve=>window.releaseOld=()=>resolve(result)):result);})()""")
        self.replace_source('graph TD; A[Old]-->B;')
        self.wait(lambda: self.js("typeof window.releaseOld==='function'"))
        self.replace_source('graph TD; A[New]-->B;')
        self.wait(lambda: self.js("document.querySelector('.md-diagram-preview svg')?.textContent.includes('New')"))
        self.js('window.releaseOld()')
        self.wait(lambda: self.js("document.querySelector('.md-code').dataset.rendered==='1'"))
        self.assertTrue(self.js("document.querySelector('.md-diagram-preview svg').textContent.includes('New')"))


if __name__ == '__main__':
    unittest.main()
