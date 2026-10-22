"""Regressions for the 2026-10-22 review (P1/P2 findings)."""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QFileDialog
from mdnote.editor.block_model import build_model
from mdnote.services import exporter
from mdnote.services.image_service import (
    _inline_image_destinations,
    prepare_images_for_save,
)
from mdnote.services.markdown_engine import MarkdownEngine
from mdnote.services.surface import surface_html
import test_live_editor as live
import test_input_workflow as workflow


class BlockModelReviewTests(unittest.TestCase):
    def test_lazy_continuation_stays_in_quote_and_list(self):
        quote = build_model("> first\ncontinuation\n\nAfter")
        self.assertEqual(quote.blocks[0].type, "blockquote")
        self.assertEqual(quote.blocks[0].raw, "> first\ncontinuation")
        listing = build_model("- first\ncontinuation\n\nAfter")
        self.assertEqual(listing.blocks[0].type, "list")
        self.assertEqual(listing.blocks[0].raw, "- first\ncontinuation")

    def test_interrupting_blocks_split_lazy_continuation(self):
        quote = build_model("> first\n# Heading\n\nAfter")
        self.assertEqual(quote.blocks[0].type, "blockquote")
        self.assertEqual(quote.blocks[0].raw, "> first")
        listing = build_model("- first\n## Heading")
        self.assertEqual(listing.blocks[0].type, "list")
        self.assertEqual(listing.blocks[0].raw, "- first")

    def test_indented_code_is_a_code_block_with_verbatim_raw(self):
        source = "    ```\n    inner\n    ```"
        model = build_model(source)
        self.assertEqual(model.blocks[0].type, "code")
        self.assertEqual(model.blocks[0].raw, source)


class SurfaceReviewTests(unittest.TestCase):
    def test_indented_code_round_trips_verbatim_via_data_md(self):
        source = "    ```\n    inner\n    ```"
        html = surface_html(source)
        self.assertIn('class="md-code"', html)
        self.assertIn("data-md=\"    ```\n    inner\n    ```\"", html)

    def test_heading_authored_id_is_carried_for_serialization(self):
        import re
        html = surface_html("# Heading {#custom}")
        self.assertIn('data-md-attr-id="custom"', html)
        self.assertIsNone(re.search(r'\sid="custom"', html))

    def test_abbreviation_definition_is_preserved_as_atom(self):
        html = surface_html("The HTML spec.\n\n*[HTML]: Hyper Text Markup Language")
        self.assertIn("atom-abbr-def", html)
        self.assertIn("*[HTML]: Hyper Text Markup Language", html)

    def test_toc_mode_does_not_emit_authored_attr_ids(self):
        html = surface_html("[TOC]\n\n# Heading {#custom}")
        self.assertNotIn("data-md-attr-id", html)


class ImageSaveReviewTests(unittest.TestCase):
    def test_destination_parser_handles_balanced_parens_and_angles(self):
        spans = list(_inline_image_destinations("![x](a(b).png)"))
        self.assertEqual(len(spans), 1)
        ds, de = spans[0]
        # The first ')' must not terminate the destination.
        self.assertEqual("![x](a(b).png)"[ds:de], "a(b).png")
        angled = list(_inline_image_destinations("![p](<a(b.png>)"))
        self.assertEqual("![p](<a(b.png>)"[angled[0][0]:angled[0][1]], "<a(b.png>")

    def test_indented_code_image_is_not_rewritten_or_copied(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "old", Path(folder) / "new"
            old.mkdir(); new.mkdir()
            (old / "x.png").write_bytes(b"img")
            prepared = prepare_images_for_save(
                "    ![](x.png)\n\n![](x.png)", str(old), str(new / "note.md"))
            self.assertEqual(prepared.text, "    ![](x.png)\n\n![](assets/x.png)")
            self.assertEqual(len(prepared.created_paths), 1)

    def test_balanced_paren_path_is_copied_with_a_valid_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "old", Path(folder) / "new"
            old.mkdir(); new.mkdir()
            (old / "a(b).png").write_bytes(b"paren")
            prepared = prepare_images_for_save(
                "![x](a(b).png)", str(old), str(new / "note.md"))
            self.assertEqual(prepared.text, "![x](assets/a(b).png)")
            self.assertTrue((new / "assets" / "a(b).png").is_file())


class ExporterCleanupReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition, seconds=8):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(.005)
        self.fail("condition timed out")

    def test_cleanup_permission_error_still_finishes_once(self):
        import tempfile as tempfile_module
        with tempfile.TemporaryDirectory() as folder:
            job = exporter.export_image(
                '<html><body>never ready</body></html>',
                str(Path(folder) / "none.png"), timeout_ms=120)
            results = []
            job.finished.connect(lambda *args: results.append(args))
            original = tempfile_module.TemporaryDirectory.cleanup
            calls = {"n": 0}

            def flaky_cleanup(self):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise PermissionError("simulated Windows sharing violation")
                return original(self)

            with patch.object(tempfile_module.TemporaryDirectory, "cleanup", flaky_cleanup):
                self.wait(lambda: bool(results))
                # Signal delivered before cleanup ran; job is terminal already.
                self.assertEqual(len(results), 1)
                self.assertTrue(job._done)
                self.assertIsNone(job._temporary)
                job.cancel()
                # Let the deferred retry run while the patch is still active.
                self.wait(lambda: calls["n"] >= 2, seconds=4)
            self.assertEqual(len(results), 1)
            job.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()


ROUNDTRIP_CASES = {
    "code_backticks": "    ```\n    inner\n    ```",
    "code_in_list": "- parent\n\n        ```\n        inner\n        ```\n\n- sibling",
    "entity_stars": "Text &#42;literal&#42; end",
    "entity_brackets": "Text &#91;site&#93;(https://example.invalid/) end",
    "image_alt": r"![a\]b](x.png)",
    "image_paren": "![photo](<assets/a(b.png>)",
    "inline_html": "Text <mark>highlight</mark> and <sup>2</sup> end",
    "heading_attrs": "# Heading {#custom}\n\n[go](#custom)",
    "abbr": "The HTML spec.\n\n*[HTML]: Hyper Text Markup Language",
    "lazy_quote": "> first\ncontinuation\n\nAfter",
    "lazy_list": "- first\ncontinuation\n\nAfter",
}
# All cases must survive a render-equivalent round trip; a subset is also
# byte-identical after an untouched open/save.
EXACT_CASES = {"code_backticks", "image_alt", "image_paren",
               "inline_html", "heading_attrs", "abbr"}


class LivePageReviewTests(unittest.TestCase):
    setUpClass = classmethod(live.LiveEditorTests.setUpClass.__func__)
    setUp = live.LiveEditorTests.setUp
    tearDown = live.LiveEditorTests.tearDown
    wait = live.LiveEditorTests.wait
    js = live.LiveEditorTests.js
    load = live.LiveEditorTests.load

    def test_atom_input_syncs_to_model_without_commit(self):
        self.load("$$\nx=1\n$$\n\nBefore")
        self.js("""(() => {
            const atom = document.querySelector('.atom-math');
            App.editAtom(atom);
            const range = document.createRange();
            range.selectNodeContents(atom); range.collapse(false);
            const s = getSelection(); s.removeAllRanges(); s.addRange(range);
            document.execCommand('insertText', false, 'REVIEWATOM123');
        })()""")
        # Debounced surface sync must carry the uncommitted atom source.
        self.wait(lambda: "REVIEWATOM123" in self.doc.get_text())

    def test_atom_cancel_reverts_live_synced_edits(self):
        source = "$$\nx=1\n$$\n\nBefore"
        self.load(source)
        self.js("""(() => {
            const atom = document.querySelector('.atom-math');
            App.editAtom(atom);
            const range = document.createRange();
            range.selectNodeContents(atom); range.collapse(false);
            const s = getSelection(); s.removeAllRanges(); s.addRange(range);
            document.execCommand('insertText', false, 'CANCELLED');
        })()""")
        self.wait(lambda: "CANCELLED" in self.doc.get_text())
        self.js("App.commitAtom(false)")
        self.wait(lambda: self.js("App.surfaceReady === true"))
        self.assertEqual(self.doc.get_text(), source)

    def test_reload_after_commit_clears_active_atom_and_prose_keeps_syncing(self):
        self.load("$$\nx=1\n$$\n\nBefore")
        self.js("""(() => {
            const atom = document.querySelector('.atom-math');
            App.editAtom(atom);
            App.commitAtom(true);
        })()""")
        self.wait(lambda: self.js("App.surfaceReady === true"))
        self.assertTrue(self.js("App.activeAtom === null"))
        self.js("""(() => {
            const p = [...document.querySelectorAll('#doc p')].find(n => n.textContent === 'Before');
            const range = document.createRange();
            range.selectNodeContents(p); range.collapse(false);
            const s = getSelection(); s.removeAllRanges(); s.addRange(range);
            document.execCommand('insertText', false, ' LATEST');
        })()""")
        self.js("App.pushSurface()")
        self.wait(lambda: self.doc.get_text().endswith("Before LATEST"))

    def test_page_command_contract(self):
        for name in ("jumpToLine", "switchTo", "toggleCurrentTask", "clearDocumentFind"):
            self.assertEqual(self.js(f"typeof App.{name}"), "function", name)
        self.load("- [ ] task")
        self.js("""(() => {
            const li = document.querySelector('#doc li');
            const range = document.createRange();
            range.setStart(li, 0); range.collapse(true);
            const s = getSelection(); s.removeAllRanges(); s.addRange(range);
            App.toggleCurrentTask();
        })()""")
        self.assertIn("- [x] task", self.js("App.captureMarkdown()"))
        self.load("$$\nx^2\n$$")
        self.js("App.switchTo(0, {raw:true, caret:0})")
        state = json.loads(self.js(
            "JSON.stringify({active:!!App.editingAtom(),connected:!!(App.editingAtom()&&App.editingAtom().isConnected)})"))
        self.assertTrue(state["active"] and state["connected"])
        self.load("# Heading\n\nBody")
        self.js("App.jumpToLine(1,0)")
        self.assertEqual(self.js("getSelection().anchorNode.textContent"), "Body")
        self.js("App.clearDocumentFind()")
        self.assertEqual(self.js("getSelection().rangeCount"), 0)

    def test_2026_10_22_roundtrips(self):
        from html import unescape
        engine = MarkdownEngine()
        for name, source in ROUNDTRIP_CASES.items():
            with self.subTest(name=name):
                self.load(source)
                self.assertTrue(self.view.flush_surface())
                saved = self.doc.get_text()
                # Browser-decoded entities (e.g. &#42;) compare equal to the
                # backslash-escaped form once the HTML is displayed.
                self.assertEqual(
                    unescape(engine.render(saved)), unescape(engine.render(source)),
                    f"{name}:\n{saved!r}")
                if name in EXACT_CASES:
                    self.assertEqual(saved, source, f"{name}:\n{saved!r}")
                self.load(saved)
                self.assertTrue(self.view.flush_surface())
                self.assertEqual(self.doc.get_text(), saved)


class WorkflowReviewTests(unittest.TestCase):
    setUpClass = classmethod(workflow.InputWorkflowTests.setUpClass.__func__)
    window = workflow.InputWorkflowTests.window
    js = workflow.InputWorkflowTests.js
    wait = workflow.InputWorkflowTests.wait

    def _edit_atom_insert(self, window, marker):
        return self.js(window, f"""(() => {{
            const atom = document.querySelector('.atom-math');
            App.editAtom(atom);
            const range = document.createRange();
            range.selectNodeContents(atom); range.collapse(false);
            const s = getSelection(); s.removeAllRanges(); s.addRange(range);
            document.execCommand('insertText', false, {json.dumps(marker)});
        }})()""")

    def test_external_change_confirms_before_overwriting_pending_atom_input(self):
        with self.window() as (window, _, folder):
            target = folder / "atom.md"
            source = "$$\nx=1\n$$\n\nBefore"
            target.write_text(source, encoding="utf-8")
            window.open_file(str(target))
            session = window.current
            self.wait(lambda: self.js(window, "App.surfaceReady === true"))
            self._edit_atom_insert(window, "REVIEWEXTERNAL1")
            with patch.object(window, "confirm", return_value=False) as ask:
                target.write_text("External replacement", encoding="utf-8")
                window._on_external_change(str(target))
                self.assertEqual(ask.call_count, 1)
            self.assertIn("REVIEWEXTERNAL1", session.doc.get_text())
            self.assertTrue(session.dirty)
            # Accepting the prompt on the next notice loads the disk version.
            with patch.object(window, "confirm", return_value=True):
                window._on_external_change(str(target), force=True)
            self.assertEqual(session.doc.get_text(), "External replacement")

    def test_export_html_captures_pending_atom_input(self):
        with self.window() as (window, _, folder):
            window.current.load_text("$$\nx=1\n$$\n\nBefore")
            self.wait(lambda: self.js(window, "App.surfaceReady === true"))
            self._edit_atom_insert(window, "REVIEWEXPORT1")
            target = folder / "out.html"
            with patch.object(QFileDialog, "getSaveFileName",
                              return_value=(str(target), "HTML (*.html)")):
                window.export_html()
            self.assertIn("REVIEWEXPORT1", target.read_text(encoding="utf-8"))

    def test_source_save_as_keeps_indented_code_image_example_verbatim(self):
        with self.window() as (window, _, folder):
            old, new = folder / "old", folder / "new"
            old.mkdir(); new.mkdir()
            (old / "x.png").write_bytes(b"img")
            target = old / "note.md"
            target.write_text("    ![](x.png)", encoding="utf-8")
            window.open_file(str(target))
            session = window.current
            self.wait(lambda: self.js(window, "App.surfaceReady === true"))
            session.toggle_mode()
            self.assertEqual(session.mode, "source")
            save_target = new / "copy.md"
            with patch.object(QFileDialog, "getSaveFileName",
                              return_value=(str(save_target), "Markdown (*.md)")):
                self.assertTrue(session.do_save(True))
            self.assertEqual(save_target.read_text(encoding="utf-8"), "    ![](x.png)")
            self.assertFalse((new / "assets").exists())


if __name__ == "__main__":
    unittest.main()
