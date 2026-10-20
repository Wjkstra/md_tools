"""Pure-Python tests for the live surface renderer (no Qt WebEngine)."""

import tempfile
import unittest
from pathlib import Path

from mdnote.services.surface import surface_html


class SurfaceRenderTests(unittest.TestCase):
    def test_relative_image_resolves_to_file_uri_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "pic.png").write_bytes(b"\x89PNG" + b"0" * 32)
            html = surface_html("![alt](pic.png)", folder)
            normalized = html.replace("\\", "/")
            self.assertIn("file:///" + folder.replace("\\", "/"), normalized)
            # The original relative reference is preserved for saving.
            self.assertIn('data-md-src="pic.png"', html)

    def test_remote_image_is_not_rewritten(self):
        html = surface_html("![x](https://example.invalid/a.png)", None)
        self.assertIn('src="https://example.invalid/a.png"', html)
        self.assertNotIn("data-md-src", html)

    def test_blank_lines_between_headings_carry_no_model_index(self):
        html = surface_html("# First\n\n\n\n# Second")
        import re
        indices = re.findall(r'data-model-index="(\d+)"', html)
        self.assertEqual(indices, ["0", "1"])
        # jumpToBlock(1) targets the second heading despite blank paragraphs.
        second = html.index('data-model-index="1"')
        self.assertIn("<h1", html[second - 6:second])

    def test_reference_definition_is_preserved_as_atom(self):
        md = '[website][ref]\n\n[ref]: https://example.invalid/ "Title"'
        html = surface_html(md)
        self.assertIn("atom-reference-def", html)
        self.assertIn("[ref]: https://example.invalid/", html)

    def test_footnote_definition_is_preserved_as_atom(self):
        md = "A note[^n].\n\n[^n]: Footnote body."
        html = surface_html(md)
        self.assertIn("atom-footnote-def", html)
        self.assertIn("[^n]: Footnote body.", html)

    def test_block_math_carries_source_for_roundtrip(self):
        html = surface_html("$$\nx = 1\n$$")
        self.assertIn("atom-math", html)
        self.assertIn("math-render", html)
        self.assertIn("$$", html)

    def test_backslash_escape_is_preserved_as_literal_span(self):
        # literal \* must not become emphasis and keeps the backslash so a
        # surface -> Markdown round trip restores the source.
        html = surface_html(r"literal \*asterisk\* end")
        self.assertIn("md-literal", html)
        self.assertIn('data-md="\\*"', html)
        self.assertNotIn("<em>", html)
        self.assertNotIn("<strong>", html)



if __name__ == "__main__":
    unittest.main()
