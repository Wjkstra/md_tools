"""Composition and startup regressions exercised in a real WebEngine page."""
import json
import test_live_editor as live


class ImeStartupTests(live.LiveEditorTests):
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
