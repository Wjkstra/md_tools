"""Composition and startup regressions exercised in a real WebEngine page."""
import json
import test_live_editor as live
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QInputMethodEvent
from PySide6.QtTest import QTest


class ImeStartupTests(live.LiveEditorTests):
    def test_native_preedit_replaces_pinyin_in_new_markdown_blocks(self):
        for marker, selector in (("# ", "h1"), ("- ", "ul li"),
                                 ("1. ", "ol li"), ("> ", "blockquote p")):
            with self.subTest(marker=marker):
                self.load("")
                self.js("""(() => {
                  const doc=document.getElementById('doc');
                  doc.focus();
                  App.restoreCaret(doc.querySelector('p'),0);
                  document.execCommand('insertText',false,""" + json.dumps(marker) + """);
                })()""")
                self.assertTrue(self.js(f"!!document.querySelector('#doc {selector}')"))
                target = self.view.focusProxy()
                for preedit in ("n", "ni", "nihao"):
                    cursor = QInputMethodEvent.Attribute(
                        QInputMethodEvent.AttributeType.Cursor, len(preedit), 1, 0)
                    QCoreApplication.sendEvent(target, QInputMethodEvent(preedit, [cursor]))
                    self.wait(lambda: self.js(f"document.querySelector('#doc {selector}').textContent")
                              .endswith(preedit))
                    self.assertEqual(self.js(f"document.querySelector('#doc {selector}').textContent"), preedit)
                QTest.qWait(160)
                self.assertNotIn("nihao", self.doc.get_text())

                commit = QInputMethodEvent()
                commit.setCommitString("你好")
                QCoreApplication.sendEvent(target, commit)
                self.wait(lambda: "你好" in self.doc.get_text())
                self.assertEqual(self.js(f"document.querySelector('#doc {selector}').textContent"), "你好")
                self.assertEqual(self.doc.get_text().strip(), marker + "你好")

    def test_composition_does_not_reformat_until_after_commit(self):
        for source in ('**粗体** ', '- 列表 ', '# 标题 '):
            with self.subTest(source=source):
                self.load(source)
                result = self.js(r'''(() => {
                  const d=document.getElementById('doc');
                  const host=d.querySelector('li,h1,p');
                  const r=document.createRange();r.selectNodeContents(host);r.collapse(false);
                  const s=getSelection();s.removeAllRanges();s.addRange(r);
                  let calls=0; const old=App.formatCurrentBlock;
                  App.formatCurrentBlock=function(){calls++;};
                  d.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
                  // Some IMEs deliver a final input with isComposing=false before compositionend.
                  d.dispatchEvent(new InputEvent('input',{bubbles:true,data:'中文',isComposing:false}));
                  const same=calls === 0;
                  d.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'中文'}));
                  App.formatCurrentBlock=old;
                  return JSON.stringify({same});
                })()''')
                self.assertTrue(json.loads(result)['same'])

    def test_deferred_inline_format_does_not_run_during_composition(self):
        self.load('**粗体**')
        result = self.js(r'''(() => {
          const d=document.getElementById('doc'), p=d.querySelector('p');
          let calls=0; const old=App.liveFormat;
          App.liveFormat=function(){calls++;};
          const r=document.createRange();r.selectNodeContents(p);r.collapse(false);
          const s=getSelection();s.removeAllRanges();s.addRange(r);
          // Exercise the same deferred path used when skipping a paired closer.
          const t=document.createTextNode(']');p.appendChild(t);r.setStart(t,0);r.collapse(true);
          s.removeAllRanges();s.addRange(r);
          App.onBeforeInput(new InputEvent('beforeinput',{bubbles:true,cancelable:true,inputType:'insertText',data:']'}));
          d.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
          window.__imeProbe=()=>{App.liveFormat=old;return calls;};
          return true;
        })()''')
        self.assertTrue(result)
        import time
        deadline = time.monotonic() + .15
        while time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.005)
        self.assertEqual(self.js('window.__imeProbe()'), 0)

    def test_unmarked_events_do_not_capture_ime_keys_or_pairing(self):
        self.load('- 列表')
        result = self.js(r'''(() => {
          const d=document.getElementById('doc');
          const host=d.querySelector('li');
          const r=document.createRange();r.selectNodeContents(host);r.collapse(false);
          const s=getSelection();s.removeAllRanges();s.addRange(r);
          d.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
          const key=new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'Enter'});
          const input=new InputEvent('beforeinput',{bubbles:true,cancelable:true,inputType:'insertText',data:'('});
          d.dispatchEvent(key); d.dispatchEvent(input);
          const result={key:key.defaultPrevented,input:input.defaultPrevented};
          d.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:'中文'}));
          return JSON.stringify(result);
        })()''')
        self.assertEqual(json.loads(result), {'key': False, 'input': False})

    def test_native_background_follows_theme_without_transparency(self):
        self.assertNotIn('transparent', self.view.styleSheet())
        self.assertIn(self.view._theme_background(), self.view.styleSheet())
        self.assertFalse(self.js("!!document.querySelector('meta[name=color-scheme]')"))
