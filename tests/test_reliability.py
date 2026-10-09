"""Regression coverage for file preservation and malformed settings."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mdnote.core.file_io import atomic_write_text
from mdnote.core.settings import SettingsService
from mdnote.services.search_service import search


class ReliabilityTests(unittest.TestCase):
    def test_failed_replace_preserves_original_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "note.md"
            target.write_text("original", encoding="utf-8")
            with patch("mdnote.core.file_io.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "new content")
            self.assertEqual(target.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_atomic_save_roundtrips_unicode(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "note.md"
            atomic_write_text(target, "中文\n😀")
            self.assertEqual(target.read_text(encoding="utf-8"), "中文\n😀")

    def test_non_object_settings_use_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            for raw in ("[]", "null", "42", '"text"'):
                target.write_text(raw, encoding="utf-8")
                with patch("mdnote.core.settings.settings_file", return_value=target):
                    self.assertEqual(SettingsService().current.font_size, 16)

    def test_invalid_setting_types_and_out_of_range_values(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            target.write_text('{"font_size": "huge", "auto_bracket": "false", "tab_size": 100, "recent_files": [null, "ok.md", 5]}', encoding="utf-8")
            with patch("mdnote.core.settings.settings_file", return_value=target):
                current = SettingsService().current
            self.assertEqual(current.font_size, 16)
            self.assertTrue(current.auto_bracket)
            self.assertEqual(current.tab_size, 8)
            self.assertEqual(current.recent_files, ["ok.md"])

    def test_empty_query_and_nonpositive_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "note.md").write_text("hello", encoding="utf-8")
            self.assertEqual(search(folder, ""), [])
            self.assertEqual(search(folder, "hello", max_hits=0), [])

    def test_single_block_commit_reuses_every_other_rendered_block(self):
        from mdnote.editor.webview import LiveDocument

        lines = []
        for i in range(200):
            lines.append(f"paragraph number {i} with text")
            lines.append("")
        doc = LiveDocument(lambda: None)
        doc.set_text("\n".join(lines))
        before = doc.payload()
        changed = doc.commit(0, before[0]["raw"] + " appended change")
        differing = [i for i in range(len(before))
                     if (before[i]["raw"], before[i]["html"])
                     != (changed[i]["raw"], changed[i]["html"])]
        # Only the edited block (and any structurally shifted blocks) may change;
        # every other rendered block must be reused from cache byte-for-byte.
        self.assertEqual(differing, [0])
        rendered_blocks = sum(1 for item in before if not item.get("trailing"))
        self.assertEqual(len(doc._render_cache), rendered_blocks)

    def test_directory_alias_is_only_searched_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "note.md").write_text("needle", encoding="utf-8")
            alias = root / "alias"
            try:
                alias.symlink_to(root, target_is_directory=True)
            except OSError:
                self.skipTest("Directory symlinks unavailable")
            self.assertEqual(len(search(folder, "needle")), 1)
