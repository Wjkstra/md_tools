"""Real keyboard and file workflow regressions."""
import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog
from mdnote.core import settings as settings_module
from mdnote.core.settings import SettingsService
from mdnote.editor.source_editor import SourceEditor
from mdnote.ui.main_window import MainWindow


class InputWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @contextmanager
    def window(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(settings_module, "settings_file", return_value=Path(folder) / "settings.json"):
                svc = SettingsService()
            svc.current.auto_check_updates = False
            with patch.object(settings_module, "_svc", svc), patch.object(MainWindow, "_restore_session"):
                window = MainWindow()
                window.show()
                self.app.processEvents()
                try:
                    yield window, svc, Path(folder)
                finally:
                    for index in range(window.tabs.count()):
                        window.tabs.widget(index).dirty = False
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    self.app.processEvents()

    def js(self, window, code):
        result = []
        window.current.preview.page().runJavaScript(code, result.append)
        deadline = time.monotonic() + 3
        while not result and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertTrue(result, "JavaScript did not return")
        return result[0]

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.002)
        self.fail("Timed out waiting for editor")

    def test_source_pair_is_single_undo_and_supports_delete_and_skip(self):
        with self.window() as (window, svc, folder):
            window.toggle_mode()
            editor = window.current.source
            QTest.keyClicks(editor, "[")
            self.assertEqual(editor.get_text(), "[]")
            editor.undo()
            self.assertEqual(editor.get_text(), "")
            QTest.keyClicks(editor, "[")
            QTest.keyClick(editor, Qt.Key_Backspace)
            self.assertEqual(editor.get_text(), "")
            QTest.keyClicks(editor, "[]")
            self.assertEqual(editor.get_text(), "[]")
            self.assertEqual(editor.get_offset(), 2)
            svc.patch(auto_bracket=False)
            editor.set_text("")
            QTest.keyClicks(editor, "[")
            self.assertEqual(editor.get_text(), "[")

    def test_configured_indentation_and_unicode_selection_wrap(self):
        with self.window() as (window, svc, folder):
            window.toggle_mode()
            editor = window.current.source
            svc.patch(tab_size=4, font_size=20)
            QTest.keyClick(editor, Qt.Key_Tab)
            self.assertEqual(editor.get_text(), "    ")
            self.assertEqual(editor.font().pixelSize(), 20)
            editor.set_text("one\ntwo")
            editor.selectAll()
            QTest.keyClick(editor, Qt.Key_Tab)
            self.assertEqual(editor.get_text(), "    one\n    two")
            QTest.keyClick(editor, Qt.Key_Backtab)
            self.assertEqual(editor.get_text(), "one\ntwo")
            editor.set_text("😀中文", offset=4)
            self.assertEqual(editor.get_offset(), 4)
            editor.selectAll()
            QTest.keyClicks(editor, "(")
            self.assertEqual(editor.get_text(), "(😀中文)")
            self.assertEqual(editor.textCursor().selectedText(), "😀中文")

    def test_source_roundtrip_preserves_cursor_and_undo(self):
        with self.window() as (window, svc, folder):
            window.current.load_text("original")
            window.toggle_mode()
            source = window.current.source
            source.insertPlainText("X")
            position = source.get_offset()
            self.assertTrue(source.document().isUndoAvailable())
            window.toggle_mode()
            window.toggle_mode()
            self.assertEqual(source.get_offset(), position)
            self.assertTrue(source.document().isUndoAvailable())
            source.undo()
            self.assertEqual(source.get_text(), "original")

    def test_open_bom_recent_menu_and_open_failures(self):
        with self.window() as (window, svc, folder):
            target = folder / "bom.md"
            target.write_bytes(b"\xef\xbb\xbf# Title")
            session = window.open_file(str(target))
            self.assertIsNotNone(session)
            self.assertEqual(session.current_text(), "# Title")
            self.assertEqual(svc.current.recent_files, [str(target.resolve())])
            window._refresh_recent_menu()
            count = window.tabs.count()
            window._recent_menu.actions()[0].trigger()
            self.assertEqual(window.tabs.count(), count)
            invalid = folder / "invalid.md"
            invalid.write_bytes(b"\xff\xfe\x00")
            with patch.object(window, "alert") as alert:
                self.assertIsNone(window.open_file(str(invalid)))
                self.assertIsNone(window.open_file(str(folder / "missing.md")))
                self.assertEqual(alert.call_count, 2)
            self.assertEqual(window.tabs.count(), count)
            self.assertIs(window.current, session)

    def test_save_as_updates_watch_and_recent_and_blocks_open_tab_collision(self):
        with self.window() as (window, svc, folder):
            window.toggle_mode()
            first = window.current
            first.source.set_text("new text")
            target = folder / "new.md"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")):
                self.assertTrue(first.do_save(True))
            self.assertEqual(target.read_text(encoding="utf-8"), "new text")
            self.assertIn(target, [Path(p) for p in window._file_watcher.files()])
            self.assertEqual(svc.current.recent_files[0], str(target.resolve()))
            other = folder / "other.md"
            other.write_text("original", encoding="utf-8")
            window.open_file(str(other))
            window.tabs.setCurrentWidget(first)
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(other), "")), \
                    patch.object(window, "alert") as alert:
                self.assertFalse(first.do_save(True))
                alert.assert_called_once()
            self.assertEqual(other.read_text(encoding="utf-8"), "original")
            self.assertEqual(first.file_path, str(target))

    def test_own_save_notification_does_not_reload_new_edits(self):
        with self.window() as (window, svc, folder):
            window.toggle_mode()
            session = window.current
            target = folder / "watched.md"
            session.file_path = str(target)
            session.source.set_text("saved text")
            self.assertTrue(session.do_save(False))
            session.source.insertPlainText(" new edit")
            current = session.current_text()
            with patch.object(window, "confirm", return_value=True) as confirm:
                window._on_external_change(str(target))
                confirm.assert_not_called()
                self.assertEqual(session.current_text(), current)
                target.write_text("external text", encoding="utf-8")
                window._on_external_change(str(target))
                confirm.assert_called_once()
            self.assertEqual(session.current_text(), "external text")
            self.assertFalse(session.dirty)

    def test_background_autosave_does_not_overwrite_external_change(self):
        with self.window() as (window, svc, folder):
            svc.current.auto_save = True
            pathA, pathB = folder / "a.md", folder / "b.md"
            pathA.write_text("A original", encoding="utf-8")
            pathB.write_text("B original", encoding="utf-8")
            A = window.open_file(str(pathA))
            B = window.open_file(str(pathB))

            # Edit A, then switch to B; A's autosave timer remains independently armed.
            window.tabs.setCurrentWidget(A)
            A.toggle_mode()
            A.source.set_text("A edited")
            window.tabs.setCurrentWidget(B)

            # Another program changes A before its autosave fires.
            pathA.write_text("A external", encoding="utf-8")
            with patch.object(window, "alert") as alert:
                A.autosave()
                alert.assert_called_once()
            self.assertEqual(pathA.read_text(encoding="utf-8"), "A external")
            self.assertTrue(A.dirty)
            self.assertEqual(A.current_text(), "A edited")

            # Returning to A rechecks the disk baseline: declining keeps local text,
            # accepting reloads the external version.
            with patch.object(window, "confirm", return_value=False) as confirm:
                window.tabs.setCurrentWidget(A)
                confirm.assert_called_once()
            self.assertEqual(A.current_text(), "A edited")
            with patch.object(window, "confirm", return_value=True):
                window._on_external_change(str(pathA))
            self.assertEqual(A.current_text(), "A external")
            self.assertFalse(A.dirty)
            self.assertEqual(A._disk_text, "A external")

    def test_dismissing_unsaved_confirmation_keeps_tab_and_window(self):
        with self.window() as (window, svc, folder):
            window.current.set_dirty(True)
            count = window.tabs.count()
            QTimer.singleShot(0, lambda: self.app.activeModalWidget().reject())
            window.close_tab(0)
            self.assertEqual(window.tabs.count(), count)
            self.assertTrue(window.current.dirty)
            QTimer.singleShot(0, lambda: self.app.activeModalWidget().reject())
            window.close()
            self.assertTrue(window.isVisible())
            self.assertTrue(window.current.dirty)

    def test_preference_switch_updates_surface(self):
        with self.window() as (window, svc, folder):
            window.current.load_text("ABC")
            self.wait(lambda: self.js(window, "App.surfaceReady === true"))
            # Toggle auto-bracket off and font size; prefs reach the surface.
            svc.patch(auto_bracket=False, font_size=22)
            self.wait(lambda: self.js(window,
                "window.__autoBracket === false && "
                "document.body.style.fontSize === '22px'"))
            svc.patch(auto_bracket=True)
            self.wait(lambda: self.js(window, "window.__autoBracket === true"))


if __name__ == "__main__":
    unittest.main()
