"""Real WebEngine and QTest coverage for code and table interaction."""
import json
import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
import test_live_editor as helpers
F = "\x60" * 3


class CodeTableExperienceTests(unittest.TestCase):
    setUpClass = classmethod(helpers.LiveEditorTests.setUpClass.__func__)
    setUp = helpers.LiveEditorTests.setUp
    tearDown = helpers.LiveEditorTests.tearDown
    wait = helpers.LiveEditorTests.wait
    js = helpers.LiveEditorTests.js
    load = helpers.LiveEditorTests.load

    def code(self, body="", language="c"):
        self.load(F + language + "\n" + body + "\n" + F)

    def code_focus(self, start=None, end=None):
        self.view.setFocus()
        start = self.js("document.querySelector('.md-code-area').textContent.length") if start is None else start
        self.js("(()=>{const a=document.querySelector('.md-code-area');a.focus();"
                f"App.selectOffsets(a,{start},{start if end is None else end});" + "})()")

    def code_text(self):
        return self.js("document.querySelector('.md-code-area').textContent")

    def key(self, key, modifiers=Qt.KeyboardModifier.NoModifier):
        QTest.keyClick(self.view.focusProxy() or self.view, key, modifiers)
        QTest.qWait(30)

    def type(self, text):
        QTest.keyClicks(self.view.focusProxy() or self.view, text)
        QTest.qWait(30)

    def test_fences_hidden_literal_body_and_safe_highlight(self):
        body = '#include <stdio.h>\nprintf("**literal**");'
        self.code(body)
        self.assertEqual(self.code_text(), body)
        self.assertFalse(self.js(f"document.querySelector('.md-code').innerText.includes({json.dumps(F)})"))
        self.wait(lambda: self.js("!!document.querySelector('.md-code-highlight span')"))
        self.assertEqual(self.js("document.querySelector('.md-code-highlight').textContent.trimEnd()"), body)
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), F+"c\n"+body+"\n"+F)

    def test_multiple_languages_get_highlight_and_labels(self):
        self.load("```c\nint x;\n```\n\n```python\ndef f():\n    pass\n```\n")
        labels = self.js("JSON.stringify([...document.querySelectorAll('.md-code-lang')]"
                         ".map(e=>e.textContent))")
        self.assertEqual(json.loads(labels), ["c", "python"])
        self.wait(lambda: self.js(
            "document.querySelectorAll('.md-code-highlight .k,.md-code-highlight .kt').length>=2"))

    def test_mermaid_atom_renders_svg(self):
        self.load(F + "mermaid\ngraph TD; A-->B;\n" + F)
        # The Mermaid atom carries the source and postProcess renders an SVG.
        self.assertTrue(self.js("!!document.querySelector('.atom-diagram')"))
        self.wait(lambda: self.js("!!document.querySelector('.atom-diagram svg')"), )

    def test_disabled_mermaid_preference_keeps_source_without_svg(self):
        # P2 regression: turning the Mermaid setting off must suppress SVG.
        self.js("window.__mermaid=false; App.applyCodePrefs();")
        self.load(F + "mermaid\ngraph TD; A-->B;\n" + F)
        self.assertTrue(self.js("!!document.querySelector('.atom-diagram')"))
        # Give async rendering a chance; an SVG must never appear.
        self.app.processEvents()
        import time as _t
        _t.sleep(0.3)
        self.app.processEvents()
        self.assertFalse(self.js("!!document.querySelector('.atom-diagram svg')"))
        self.js("window.__mermaid=true;")

    def test_unclosed_code_keeps_last_line_and_original_fence(self):
        source = '~~~python\nfirst = 1\nlast = 2'
        self.load(source)
        self.assertIn('last = 2', self.code_text())
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), source)

    def test_c_enter_pair_and_continuation_keep_indent(self):
        self.code()
        self.code_focus(0)
        self.type('if (x) {')
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.code_text(), 'if (x) {\n    \n}')
        self.type('run();')
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.code_text(), 'if (x) {\n    run();\n    \n}')

    def test_python_colon_uses_four_space_indent(self):
        self.code('if ready:', 'python')
        self.code_focus()
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.code_text(), 'if ready:\n    ')

    def test_quote_skip_and_empty_pair_backspace(self):
        self.code()
        self.code_focus(0)
        self.type('"')
        self.assertEqual(self.code_text(), '""')
        self.type('"')
        self.assertEqual(self.code_text(), '""')
        self.js("App.selectOffsets(document.querySelector('.md-code-area'),1)")
        self.key(Qt.Key.Key_Backspace)
        self.assertEqual(self.code_text(), '')

    def test_shift_tab_preserves_body_and_native_undo(self):
        self.code('    return value;')
        self.code_focus()
        self.key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.code_text(), 'return value;')
        self.js("App.undo()")
        self.assertEqual(self.code_text(), '    return value;')

    def test_multiline_tab_and_outdent(self):
        self.code('a\nb', 'javascript')
        self.code_focus(0, 3)
        self.key(Qt.Key.Key_Tab)
        self.assertEqual(self.code_text(), '  a\n  b')
        self.key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.code_text(), 'a\nb')

    def test_highlight_keeps_editable_dom_caret_and_undo(self):
        self.code('int x;')
        self.code_focus()
        self.js("window.savedArea=document.querySelector('.md-code-area')")
        self.type('a')
        self.wait(lambda: self.js("!!document.querySelector('.md-code-highlight .kt')"))
        self.assertTrue(self.js("savedArea===document.querySelector('.md-code-area')"))
        self.assertEqual(self.js("App.textOffset(savedArea)"), len('int x;a'))
        self.js("App.undo()")
        self.assertEqual(self.code_text(), 'int x;')

    def test_ime_input_is_not_auto_paired(self):
        self.code()
        self.code_focus(0)
        self.assertFalse(self.js("""(()=>{const a=document.querySelector('.md-code-area');
        const e=new InputEvent('beforeinput',{bubbles:true,cancelable:true,
          inputType:'insertText',data:'(',isComposing:true});
        a.dispatchEvent(e);return e.defaultPrevented;})()"""))
        self.assertEqual(self.code_text(), '')

    def test_language_selection_is_saved_and_applies_preset(self):
        self.code('if (ok) {', '')
        self.js("""(()=>{const s=document.querySelector('.md-code-language');
        s.value='cpp';s.dispatchEvent(new Event('change'));})()""")
        self.code_focus()
        self.key(Qt.Key.Key_Return)
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), F+'cpp\nif (ok) {\n    \n'+F)

    def test_language_autocomplete_filters_and_pick_applies(self):
        self.code('x = 1', '')
        # Typing "c" filters to C-family and related languages.
        self.js("""(()=>{const i=document.querySelector('input.md-code-language');
        i.value='c';i.dispatchEvent(new Event('input',{bubbles:true}));})()""")
        labels = json.loads(self.js(
            "JSON.stringify([...document.querySelectorAll('.md-code-lang-item')]"
            ".map(b=>b.dataset.value))"))
        self.assertIn("c", labels)
        self.assertIn("cpp", labels)
        self.assertIn("csharp", labels)
        # Mouse (mousedown) on the C# suggestion applies it.
        self.js("""(()=>{const b=[...document.querySelectorAll('.md-code-lang-item')]
                 .find(x=>x.dataset.value==='csharp');
                 b.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,cancelable:true}));})()""")
        self.assertEqual(
            self.js("document.querySelector('.md-code').dataset.lang"), "csharp")
        self.assertTrue(self.view.flush_surface())
        self.assertIn(F+"csharp\n", self.doc.get_text())

    def test_immediate_flush_captures_last_input_and_blank_code_line(self):
        self.code('x;')
        self.code_focus()
        self.js("document.execCommand('insertText',false,'\\nlast;\\n')")
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), F+'c\nx;\nlast;\n\n'+F)

    def test_code_select_all_is_local_and_ctrl_enter_exits(self):
        self.load('前文\n\n'+F+'c\nx;\n'+F+'\n\n后文')
        self.code_focus()
        self.key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.js("getSelection().toString()"), 'x;')
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.js("App.selectionElement().closest('p').textContent"), '后文')

    def table(self):
        self.load('| A | B |\n| :--- | ---: |\n| one | two |')
        self.view.activateWindow()
        self.view.setFocus()
        self.js("App.focusCell(document.querySelectorAll('tbody td')[1])")
        self.wait(lambda: self.js("document.hasFocus() && document.activeElement.id==='doc'"))

    def test_table_ctrl_enter_adds_row_focus_and_alignment_with_undo(self):
        self.table()
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        data = json.loads(self.js("""JSON.stringify({
        rows:document.querySelector('table').rows.length,
        column:App.selectionElement().closest('td').cellIndex,
        row:App.selectionElement().closest('tr').rowIndex,
        align:App.selectionElement().closest('td').style.textAlign})"""))
        self.assertEqual(data, {'rows':3,'column':1,'row':2,'align':'right'})
        self.assertTrue(self.view.flush_surface())
        self.assertNotIn('<br>', self.doc.get_text())
        self.js("App.undo()")
        self.assertEqual(self.js("document.querySelector('table').rows.length"), 2)

    def test_table_alt_enter_adds_column_and_moves_caret(self):
        self.table()
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.AltModifier)
        self.assertEqual(self.js("document.querySelector('table').rows[0].cells.length"), 3)
        self.assertEqual(self.js("App.selectionElement().closest('td').cellIndex"), 2)
        self.assertEqual(self.js("App.selectionElement().closest('td').style.textAlign"), 'right')
        self.wait(lambda: self.js("document.hasFocus() && document.activeElement.id==='doc' && "
                                 "App.selectionElement().closest('td')?.cellIndex===2"))
        self.type('new')
        self.assertTrue(self.view.flush_surface())
        self.assertIn('| one | two | new |', self.doc.get_text())

    def test_table_tab_at_end_creates_row_and_returns_to_first_column(self):
        self.table()
        self.key(Qt.Key.Key_Tab)
        self.assertEqual(self.js("document.querySelector('table').rows.length"), 3)
        self.assertEqual(self.js("App.selectionElement().closest('td').cellIndex"), 0)
        self.key(Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(self.js("App.selectionElement().closest('tr').rowIndex"), 1)

    def test_table_header_shortcut_and_menu_actions(self):
        self.table()
        self.js("App.focusCell(document.querySelectorAll('th')[1])")
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(self.js("App.selectionElement().closest('tr').rowIndex"), 1)
        self.js("App.tableCommand('column');App.tableCommand('center')")
        self.assertEqual(self.js("document.querySelector('table').rows[0].cells[2].style.textAlign"), 'center')
        self.js("App.tableCommand('deleteColumn')")
        self.assertEqual(self.js("document.querySelector('table').rows[0].cells.length"), 2)

    def test_insert_menu_creates_body_editor_instead_of_raw_fences(self):
        self.load('正文')
        source = '\n\n'+F+'c\n\n'+F+'\n\n'
        self.js("App.focusEditor();App.insertMarkdown("+json.dumps(source)+")")
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertFalse(self.js("document.getElementById('doc').innerText.includes("+json.dumps(F)+")"))
        self.assertTrue(self.js("document.activeElement.classList.contains('md-code-area')"))
        self.type('int x;')
        self.assertTrue(self.view.flush_surface())
        self.assertIn(F+'c\nint x;\n'+F, self.doc.get_text())

    def test_typed_fence_enter_converts_to_code(self):
        self.load('plain')
        self.js("""(()=>{const p=document.querySelector('p');p.textContent='\u0060\u0060\u0060c';
        const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
        const s=getSelection();s.removeAllRanges();s.addRange(r);
        document.getElementById('doc').focus();})()""")
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertEqual(self.code_text(), '')
        self.assertEqual(self.code_lang(), 'c')

    # ------------------------------------------------ typed fences ----------
    #
    # Regression: auto-pairing turned a typed ``` into ``````|``` (six marks), so the
    # Enter rule never matched and the literal fence stayed while an empty,
    # language-less block appeared below it. These drive real keystrokes.

    def caret_at_end(self, text):
        self.load(text)
        self.js("""(()=>{const ps=document.querySelectorAll('#doc p');
        const p=ps[ps.length-1];
        const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
        const s=getSelection();s.removeAllRanges();s.addRange(r);
        document.getElementById('doc').focus();})()""")
        self.view.setFocus()

    def code_lang(self):
        return self.js("(()=>{const b=document.querySelector('.md-code');"
                       "return b?b.dataset.lang:null})()")

    def test_typed_fence_is_not_doubled_by_auto_pairing(self):
        self.caret_at_end('')
        self.type(F + 'python')
        self.assertEqual(self.js("document.querySelector('#doc p').textContent"),
                         F + 'python')

    def test_typed_fence_enter_creates_block_with_typed_language(self):
        self.caret_at_end('')
        self.type(F + 'python')
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertEqual(self.code_lang(), 'python')
        self.assertEqual(self.js("document.querySelector('.md-code-language').value"),
                         'python')
        self.assertFalse(self.js("document.getElementById('doc').innerText.includes("
                                 + json.dumps(F) + ")"))
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), F + 'python\n\n' + F)

    def test_typed_bare_fence_enter_creates_plain_block(self):
        self.caret_at_end('')
        self.type(F)
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertEqual(self.code_lang(), '')
        self.assertFalse(self.js("document.getElementById('doc').innerText.includes("
                                 + json.dumps(F) + ")"))
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), F + '\n\n' + F)

    def test_typed_fence_keeps_leading_text_and_markup(self):
        self.caret_at_end('**粗体** 说明')
        self.type(F + 'python')
        self.key(Qt.Key.Key_Return)
        self.wait(lambda: self.js("!!document.querySelector('.md-code-area')"))
        self.assertEqual(self.code_lang(), 'python')
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(),
                         '**粗体** 说明\n\n' + F + 'python\n\n' + F)

    def test_typed_inline_code_closer_renders_without_doubling(self):
        # Immediate rendering: `a` becomes inline <code>; closer stepped over,
        # serialized Markdown stays exact (not doubled).
        self.caret_at_end('')
        self.type('`a`')
        self.wait(lambda: self.js("!!document.querySelector('#doc p code')"))
        self.assertEqual(self.js("document.querySelector('#doc p code').textContent"), 'a')
        self.assertEqual(self.js("HtmlToMd.serialize(document.getElementById('doc'))"), '`a`')

    def test_fluid_width_no_focus_border_and_line_number_preference(self):
        self.code('int x;')
        self.view.resize(1680, 900)
        self.wait(lambda: self.js("window.innerWidth>=1600"))
        metrics = json.loads(self.js("""JSON.stringify({
        width:document.getElementById('doc').getBoundingClientRect().width,
        padding:parseFloat(getComputedStyle(document.getElementById('doc')).paddingLeft),
        border:getComputedStyle(document.querySelector('.md-code-area')).borderTopWidth,
        outline:getComputedStyle(document.querySelector('.md-code-area')).outlineStyle})"""))
        self.assertGreater(metrics['width']-2*metrics['padding'], 1500)
        self.assertEqual((metrics['border'],metrics['outline']), ('0px','none'))
        self.view.resize(600, 700)
        self.wait(lambda: self.js("window.innerWidth<=600"))
        self.assertEqual(self.js("getComputedStyle(document.getElementById('doc')).paddingLeft"), '16px')
        self.js("window.__codeLineNumbers=false;App.applyCodePrefs()")
        self.assertEqual(self.js("getComputedStyle(document.querySelector('.md-code-numbers')).display"), 'none')

    def test_return_to_editor_preserves_undo(self):
        self.code('x;')
        self.code_focus()
        self.type('a')
        self.view.focus_editor()
        self.js("App.undo()")
        self.assertEqual(self.code_text(), 'x;')

    def test_code_preserves_leading_empty_line_and_embedded_fence(self):
        body = '\nconst example = "' + F + '";\n'
        self.load(F+'~custom\n'+body+'\n'+F)
        self.assertEqual(self.code_text(), body)
        self.assertTrue(self.view.flush_surface())
        self.assertEqual(self.doc.get_text(), F+'~custom\n'+body+'\n'+F)
        self.code_focus()
        self.type('x')
        self.assertTrue(self.view.flush_surface())
        self.assertTrue(self.doc.get_text().startswith('\x60'*4+'~custom\n'))

    def test_multiline_paste_remains_plain_code_and_undoable(self):
        self.code('old')
        self.code_focus(0,3)
        source='<script>unsafe()</script>\n    next;\n'
        result=self.js("""(()=>{const a=document.querySelector('.md-code-area');
        const data=new DataTransfer();data.setData('text/plain',SOURCE);
        const e=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});
        a.dispatchEvent(e);return e.defaultPrevented;})()""".replace('SOURCE',json.dumps(source)))
        self.assertTrue(result)
        self.assertEqual(self.code_text(), source)
        self.assertFalse(self.js("!!document.querySelector('.md-code-area script')"))
        self.assertTrue(self.view.flush_surface())
        self.assertIn(source,self.doc.get_text())
        self.js("App.undo()")
        self.assertEqual(self.code_text(),'old')

    def test_auto_bracket_preference_can_disable_pairing(self):
        self.code()
        self.code_focus(0)
        self.js("window.__autoBracket=false")
        self.type('(')
        self.assertEqual(self.code_text(),'(')


if __name__ == '__main__':
    unittest.main()
