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

    def test_blank_update_url_is_normalized_to_empty(self):
        # Whitespace-only sources must not bypass the default-URL fallback and
        # later fail HTTPS validation with "更新地址必须是有效的 HTTPS URL".
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            for raw in ('{"update_url": "   "}', '{"update_url": "\\n"}',
                        '{"update_url": " https://x.com "}'):
                target.write_text(raw, encoding="utf-8")
                with patch("mdnote.core.settings.settings_file", return_value=target):
                    current = SettingsService().current
                if "x.com" in raw:
                    self.assertEqual(current.update_url, "https://x.com")
                else:
                    self.assertEqual(current.update_url, "")

    def test_empty_query_and_nonpositive_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "note.md").write_text("hello", encoding="utf-8")
            self.assertEqual(search(folder, ""), [])
            self.assertEqual(search(folder, "hello", max_hits=0), [])

    def test_surface_text_roundtrip_rebuilds_model(self):
        from mdnote.services.surface import surface_html

        text = "# 标题\n\n普通段落文字\n\n- 甲\n- 乙\n"
        html = surface_html(text)
        self.assertIn("<h1", html)
        self.assertIn(">标题</h1>", html)
        self.assertIn("普通段落文字", html)
        self.assertIn("<li>甲</li>", html)

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
