"""Regressions for the 2026-10-27 review.

P1-01: image relocation must not rewrite examples inside tab-indented or
quoted code (including quoted fences and list-indented code).
P2-01/P2-02/P2-03/P3-01: heading levels 4-6 in lists, plain tildes, safe
inline HTML, heading attr_list and empty inline code survive round trips.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

from PySide6.QtWidgets import QFileDialog

from mdnote.services.image_service import prepare_images_for_save
from mdnote.services.surface import (
    surface_html,
    _heading_attrs,
    _heading_attr_id,
)
import test_live_editor as live
import test_input_workflow as workflow


# ------------------------------------------------------------ P1-01 service

class ImageCodeContextTests(unittest.TestCase):
    def _prepare(self, text):
        folder_obj = tempfile.TemporaryDirectory()
        self.addCleanup(folder_obj.cleanup)
        old, new = Path(folder_obj.name) / "old", Path(folder_obj.name) / "new"
        old.mkdir()
        new.mkdir()
        (old / "x.png").write_bytes(b"img")
        return prepare_images_for_save(text, str(old), str(new / "note.md")), new

    def _assert_protected(self, name, text):
        prepared, new = self._prepare(text)
        self.assertEqual(prepared.text, text, name)
        self.assertEqual(prepared.created_paths, [], name)
        self.assertFalse((new / "assets").exists(), name)

    def test_tab_indented_code_is_protected(self):
        self._assert_protected("tab", "\t![](x.png)")

    def test_quote_indented_code_is_protected(self):
        self._assert_protected("quote", ">     ![](x.png)")
        self._assert_protected("nested", "> >     ![](x.png)")

    def test_quoted_fence_is_protected(self):
        self._assert_protected(
            "quoted fence", "> ```\n> ![](x.png)\n> ```")

    def test_list_indented_code_and_tab_stops_are_protected(self):
        self._assert_protected("list 8", "- item\n\n        ![](x.png)")
        self._assert_protected("3sp+tab", "   \t![](x.png)")

    def test_plain_prose_and_lazy_continuation_still_relocate(self):
        prepared, new = self._prepare("see ![](x.png)")
        self.assertIn("assets/x.png", prepared.text)
        self.assertEqual(len(prepared.created_paths), 1)
        # Six spaces without a preceding blank line stay lazy prose.
        prepared, new = self._prepare("- item\n      ![](x.png)")
        self.assertIn("![](assets/x.png)", prepared.text)
        self.assertEqual(len(prepared.created_paths), 1)


# ------------------------------------------------------------ P2-03 surface

class SurfaceHeadingAttrsTests(unittest.TestCase):
    def test_full_attr_list_is_carried(self):
        html = surface_html("# Heading {.special}")
        self.assertIn('data-md-attrs=".special"', html)
        html = surface_html('## T {#custom .special title="hint"}')
        self.assertIn('data-md-attrs="#custom .special title=&quot;hint&quot;"',
                      html)
        self.assertIn('data-md-attr-id="custom"', html)

    def test_colon_form_is_accepted(self):
        html = surface_html("# Heading {: #custom}")
        self.assertIn('data-md-attrs="#custom"', html)
        self.assertEqual(_heading_attr_id("# Heading {: #custom}"), "custom")

    def test_helpers_parse_and_ignore_brace_prose(self):
        self.assertEqual(_heading_attrs("# H {.a #b k='v'}"), ".a #b k='v'")
        self.assertIsNone(_heading_attrs("# H{x}"))       # no space before brace
        self.assertIsNone(_heading_attrs("# no braces"))
        self.assertEqual(_heading_attr_id("# H {.a #b}"), "b")

    def test_toc_mode_drops_carried_attrs(self):
        html = surface_html("[TOC]\n\n# Heading {.special #x}")
        self.assertNotIn("data-md-attrs", html)
        self.assertNotIn("data-md-attr-id", html)


# ------------------------------------------------------------ live round trips

class LiveRoundTripTests(unittest.TestCase):
    setUpClass = classmethod(live.LiveEditorTests.setUpClass.__func__)
    setUp = live.LiveEditorTests.setUp
    tearDown = live.LiveEditorTests.tearDown
    wait = live.LiveEditorTests.wait
    js = live.LiveEditorTests.js
    load = live.LiveEditorTests.load

    def capture(self):
        self.js("App.pushSurface()")
        return self.js("App.captureMarkdown()")

    def test_plain_tildes_round_trip_without_backslashes(self):
        self.load("one ~ two ~~three")
        self.assertEqual(self.capture(), "one ~ two ~~three")
        self.load("a ~~b~~ c")
        self.assertEqual(self.capture(), "a ~~b~~ c")

    def test_h4_to_h6_in_lists_keep_their_marks(self):
        for level in range(4, 7):
            hashes = "#" * level
            source = f"- parent\n\n    {hashes} subheading\n\n    after"
            self.load(source)
            self.assertEqual(self.capture(), source, level)

    def test_kbd_and_safe_inline_html_survive(self):
        source = "Press <kbd>Ctrl</kbd> and <samp>out</samp> now"
        self.load(source)
        self.assertEqual(self.capture(), source)

    def test_heading_attr_list_survives(self):
        source = "# Heading {.special}"
        self.load(source)
        self.assertEqual(self.capture(), source)
        source2 = '## T {#custom .special title="hint"}'
        self.load(source2)
        self.assertEqual(self.capture(), source2)

    def test_empty_inline_code_becomes_a_valid_empty_span_and_is_stable(self):
        self.load("`   `")
        first = self.capture()
        self.assertEqual(first, "`` ``")
        self.load(first)
        self.assertEqual(self.capture(), "`` ``")


# ------------------------------------------------------------ real save-as

class SaveAsCodeContextTests(unittest.TestCase):
    setUpClass = classmethod(workflow.InputWorkflowTests.setUpClass.__func__)
    window = workflow.InputWorkflowTests.window
    js = workflow.InputWorkflowTests.js
    wait = workflow.InputWorkflowTests.wait

    def _save_as(self, window, target):
        with patch.object(QFileDialog, "getSaveFileName",
                          return_value=(str(target), "Markdown (*.md)")):
            return window.current.do_save(True)

    def _source_save_as(self, name, source):
        with self.window() as (window, _svc, folder):
            old, new = folder / "old", folder / "new"
            old.mkdir()
            new.mkdir()
            (old / "x.png").write_bytes(b"img")
            target = old / name
            target.write_text(source, encoding="utf-8")
            window.open_file(str(target))
            session = window.current
            self.wait(lambda: self.js(window, "App.surfaceReady === true"))
            session.toggle_mode()
            self.assertEqual(session.mode, "source")
            save_target = new / ("copy-" + name)
            self.assertTrue(self._save_as(window, save_target))
            self.assertEqual(
                save_target.read_text(encoding="utf-8"), source, name)
            self.assertFalse((new / "assets").exists(), name)

    def test_source_save_as_keeps_tab_code_example(self):
        self._source_save_as("tab.md", "\t![](x.png)")

    def test_source_save_as_keeps_quote_code_example(self):
        self._source_save_as("quote.md", ">     ![](x.png)")

    def test_live_save_as_keeps_tab_code_example_verbatim(self):
        with self.window() as (window, _svc, folder):
            old, new = folder / "old", folder / "new"
            old.mkdir()
            new.mkdir()
            (old / "x.png").write_bytes(b"img")
            target = old / "live.md"
            source = "\t![](x.png)"
            target.write_text(source, encoding="utf-8")
            window.open_file(str(target))
            self.wait(lambda: self.js(window, "App.surfaceReady === true"))
            save_target = new / "copy-live.md"
            self.assertTrue(self._save_as(window, save_target))
            self.assertEqual(
                save_target.read_text(encoding="utf-8"), source)
            self.assertFalse((new / "assets").exists())


if __name__ == "__main__":
    unittest.main()
