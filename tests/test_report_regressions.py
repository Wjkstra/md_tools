"""Content-preservation and save-safety regressions from the 2026-10-21 report."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QCloseEvent
from mdnote.services.markdown_engine import MarkdownEngine
from mdnote.services.surface import surface_html
import test_live_editor as live
import test_input_workflow as workflow


CASES = {
    "multiple_nested_lists": "- parent\n\n    - first nested\n\n    1. second nested\n\n- sibling",
    "loose_list": "- first paragraph\n\n    second paragraph\n\n- next item",
    "list_with_quote": "- parent\n\n    > quoted\n\n    continuation\n\n- sibling",
    "inline_code": r"Use `\*literal\*` here",
    "indented_code": '    x = "\\*literal\\*"',
    "pipe_table": "| A | B |\n| --- | --- |\n| a\\|b | c |",
    "code_pipe_table": "| A | B |\n| --- | --- |\n| `a\\|b` | c |",
    "html_text": "&lt;em&gt;literal&lt;/em&gt;",
    "entity_text": "&amp;copy; and &lt;img src=x&gt;",
    "link_title": '[site](https://example.invalid/ "Helpful title")',
    "definition_list": "Term\n: Definition",
    "raw_html": "<p><mark>highlight</mark> and <sup>2</sup></p>",
    "reference": '[website][ref]\n\n[ref]: https://example.invalid/ "Title"',
    "footnote": "A footnote[^n].\n\n[^n]: Footnote body.",
    "toc_upper": "[TOC]\n\n# First\n\n## Second",
}


class ReportSurfaceTests(unittest.TestCase):
    def test_special_text_and_code_are_literal(self):
        for source in ["literal \ue0010\ue002", "literal \ue001999\ue002 and \\*"]:
            self.assertIn("literal", surface_html(source))
        for source in [CASES["inline_code"], CASES["indented_code"]]:
            html = surface_html(source)
            self.assertIn(r"\*literal\*", html)
            self.assertNotIn("md-literal", html)

    def test_encoded_local_images_keep_original_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            for filename, reference in [("space name.png", "space%20name.png"),
                                        ("中文.png", "%E4%B8%AD%E6%96%87.png"),
                                        ("a&b.png", "a&b.png"),
                                        ("test.png", "test.png?rev=1")]:
                target = Path(folder) / filename
                target.write_bytes(b"image")
                html = surface_html(f"![test]({reference})", folder)
                self.assertIn('src="' + target.as_uri() + '"', html)
                from html import escape
                self.assertIn('data-md-src="' + escape(reference, quote=True) + '"', html)

    def test_contextual_structures_are_rendered_with_source(self):
        html = surface_html(CASES["reference"])
        self.assertIn('href="https://example.invalid/"', html)
        html = surface_html(CASES["footnote"])
        self.assertIn('href="#fn:n"', html)
        self.assertIn("Footnote body.", html)
        html = surface_html("[toc]\n\n# Repeat\n\n# Repeat")
        for fragment in ['href="#repeat"', 'href="#repeat_1"', 'id="repeat"', 'id="repeat_1"']:
            self.assertIn(fragment, html)
        self.assertIn('data-md="[toc]"', html)

    def test_batch_keeps_adjacent_lists_and_model_indices_separate(self):
        source = "- one\n\nparagraph\n\n- two\n\n" + "\n\n".join(f"段落 {i}" for i in range(260))
        html = surface_html(source)
        self.assertEqual(html.count("<ul"), 2)
        self.assertEqual(html.count("data-model-index="), 263)
        self.assertNotIn("<hr", html)


class ReportLiveTests(unittest.TestCase):
    setUpClass = classmethod(live.LiveEditorTests.setUpClass.__func__)
    setUp = live.LiveEditorTests.setUp
    tearDown = live.LiveEditorTests.tearDown
    wait = live.LiveEditorTests.wait
    js = live.LiveEditorTests.js
    load = live.LiveEditorTests.load

    def test_report_roundtrips_remain_stable_after_reopen(self):
        engine = MarkdownEngine()
        for name, source in CASES.items():
            with self.subTest(name=name):
                self.load(source)
                self.assertTrue(self.view.flush_surface())
                saved = self.doc.get_text()
                self.assertEqual(engine.render(saved), engine.render(source))
                self.load(saved)
                self.assertTrue(self.view.flush_surface())
                self.assertEqual(self.doc.get_text(), saved)

    def test_list_conversion_keeps_position_rich_text_numbering_and_undo(self):
        for action in ["App.setHeadingLevel(2)", "App.backspaceStripFormat()"]:
            for source in ["Before\n\n- first\n- **second**\n- third\n\nAfter",
                           "Before\n\n5. first\n6. **second**\n7. third\n\nAfter",
                           "Before\n\n- parent\n    - first\n    - **second**\n    - third\n- sibling\n\nAfter"]:
                with self.subTest(action=action, source=source):
                    self.load(source)
                    self.js("""(()=>{const li=[...document.querySelectorAll('#doc li')]
                        .find(li=>li.querySelector(':scope > strong'));
                        const r=document.createRange();r.setStart(li,0);r.collapse(true);
                        getSelection().removeAllRanges();getSelection().addRange(r);})()""")
                    before = self.js("App.captureMarkdown()")
                    self.js(action)
                    after = self.js("App.captureMarkdown()")
                    self.assertIn("**second**", after, self.js("document.getElementById('doc').innerHTML"))
                    self.assertLess(after.index("Before"), after.index("first"))
                    self.assertLess(after.index("first"), after.index("**second**"))
                    self.assertLess(after.index("**second**"), after.index("third"))
                    self.assertLess(after.index("third"), after.index("After"))
                    if source.startswith("Before\n\n5."):
                        self.assertIn("7. third", after)
                    self.js("App.undo()")
                    self.assertEqual(self.js("App.captureMarkdown()"), before)
                    self.js("App.redo()")
                    self.assertEqual(self.js("App.captureMarkdown()"), after)

    def test_list_conversion_at_document_start_is_undoable(self):
        for source, selector in [("- only", "li"), ("- first\n- second\n- third", "li:nth-child(2)")]:
            self.load(source)
            self.js("""(()=>{const li=document.querySelector('#doc """ + selector + """');
                const r=document.createRange();r.setStart(li.firstChild,0);r.collapse(true);
                getSelection().removeAllRanges();getSelection().addRange(r);
                App.backspaceStripFormat();})()""")
            result = self.js("App.captureMarkdown()")
            self.assertIn("only" if source == "- only" else "second", result,
                          self.js("document.getElementById('doc').innerHTML"))
            self.js("App.undo()")
            self.assertEqual(self.js("App.captureMarkdown()"), source)
            self.js("App.redo()")
            self.assertEqual(self.js("App.captureMarkdown()"), result)


class ReportSaveTests(unittest.TestCase):
    setUpClass = classmethod(workflow.InputWorkflowTests.setUpClass.__func__)
    window = workflow.InputWorkflowTests.window
    js = workflow.InputWorkflowTests.js
    wait = workflow.InputWorkflowTests.wait

    def test_unready_or_throwing_capture_cannot_save_reset_close_or_exit(self):
        with self.window() as (window, _, folder), patch.object(window, "alert"):
            session = window.current
            target = folder / "important.md"
            original = "# Important saved content"
            target.write_text(original, encoding="utf-8")
            session.file_path = str(target)
            session._disk_text = original
            session.load_text(original)
            self.wait(lambda: self.js(window, "typeof App!=='undefined' && App.surfaceReady"))
            self.js(window, "App.surfaceReady=false")
            self.assertFalse(session.do_save(False))
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            self.assertEqual(session.doc.get_text(), original)
            window.new_file()
            self.assertEqual(session.file_path, str(target))
            count = window.tabs.count()
            window.close_tab(window.tabs.currentIndex())
            self.assertEqual(window.tabs.count(), count)
            event = QCloseEvent()
            window.closeEvent(event)
            self.assertFalse(event.isAccepted())
            self.js(window, "App.surfaceReady=true; App.captureMarkdown=()=>{throw Error('capture failed')}")
            self.assertFalse(session.do_save(False))
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_empty_document_is_a_valid_capture(self):
        with self.window() as (window, _, folder):
            target = folder / "empty.md"
            target.write_text("old", encoding="utf-8")
            session = window.current
            session.file_path = str(target)
            session._disk_text = "old"
            session.load_text("")
            self.assertTrue(session.do_save(False))
            self.assertEqual(target.read_text(encoding="utf-8"), "")

    def test_capture_timeout_ignores_late_callback_and_invalid_payload(self):
        with self.window() as (window, _, folder), patch.object(window, "alert"):
            session = window.current
            session.load_text("keep me")
            self.wait(lambda: self.js(window, "typeof App!=='undefined' && App.surfaceReady"))
            callbacks = []
            page = session.preview.page()
            with patch.object(page, "runJavaScript", side_effect=lambda script, callback: callbacks.append(callback)):
                self.assertFalse(session.preview.flush_surface())
            callbacks[0](json.dumps({"ready": True, "text": "stale result"}))
            self.assertEqual(session.doc.get_text(), "keep me")
            for payload in ["", "null", '""', '{"ready":true,"text":null}']:
                with patch.object(page, "runJavaScript", side_effect=lambda script, callback: callback(payload)):
                    self.assertFalse(session.preview.flush_surface())
                self.assertEqual(session.doc.get_text(), "keep me")

    def test_report_cases_save_to_disk_without_content_loss(self):
        with self.window() as (window, _, folder):
            engine = MarkdownEngine()
            session = window.current
            target = folder / "roundtrip.md"
            session.file_path = str(target)
            for name, source in CASES.items():
                with self.subTest(name=name):
                    target.write_text(source, encoding="utf-8")
                    session._disk_text = source
                    session.load_text(source)
                    self.assertTrue(session.do_save(False))
                    self.assertEqual(engine.render(target.read_text(encoding="utf-8")), engine.render(source))
