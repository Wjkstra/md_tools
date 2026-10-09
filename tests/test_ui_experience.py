"""Regressions for visible multi-tab, theme and find interactions."""
import os
import tempfile
import unittest
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from mdnote.core.settings import AppSettings, settings_service
from mdnote.services import markdown_engine
from mdnote.ui.main_window import MainWindow


class UIExperienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @contextmanager
    def window(self):
        svc = settings_service()
        with patch.object(svc, "current", AppSettings(auto_check_updates=False)), \
                patch.object(svc, "patch"), patch.object(MainWindow, "_restore_session"):
            window = MainWindow()
            window.show()
            self.app.processEvents()
            try:
                yield window
            finally:
                for i in range(window.tabs.count()):
                    window.tabs.widget(i).dirty = False
                window.close()
                svc.off_change(window._on_settings_changed)
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()

    def test_mode_switch_does_not_mark_clean_document_dirty(self):
        with self.window() as window:
            window.current.load_text("# Document")
            window.current.set_dirty(False)
            QTest.mouseClick(window.statusbar._mode, Qt.LeftButton)
            self.assertEqual(window.current.mode, "source")
            self.assertFalse(window.current.dirty)
            window.toggle_mode()
            self.assertFalse(window.current.dirty)

    def test_tab_switch_restores_outline_and_background_changes_do_not_replace_it(self):
        with self.window() as window:
            first = window.current
            first.load_text("# Alpha")
            second = window.add_session("# Beta", "beta.md")
            first.on_content_changed()
            first.refresh_outline()
            self.assertEqual(window.sidebar._outline.item(0).text(), "Beta")
            self.assertTrue(window.tabs.tabText(0).startswith("• "))
            window.tabs.setCurrentWidget(first)
            self.assertEqual(window.sidebar._outline.item(0).text(), "Alpha")
            window.tabs.setCurrentWidget(second)
            self.assertEqual(window.tabs.tabToolTip(1), "beta.md")

    def test_find_wrap_and_missing_query_preserve_cursor(self):
        with self.window() as window:
            window.toggle_mode()
            source = window.current.source
            source.set_text("needle and text")
            cursor = source.textCursor()
            cursor.setPosition(len(source.get_text()))
            source.setTextCursor(cursor)
            window.findbar.open()
            window.findbar._find.setText("needle")
            window.find_text("needle", True)
            self.assertEqual(window.findbar._feedback.text(), "已回到文档开头")
            cursor = source.textCursor()
            window.findbar._find.setText("absent")
            window.find_text("absent", True)
            self.assertEqual(window.findbar._feedback.text(), "未找到匹配")
            self.assertEqual(source.textCursor().position(), cursor.position())
            self.assertEqual(source.textCursor().anchor(), cursor.anchor())

    def test_replace_matches_case_insensitive_find_and_updates_feedback(self):
        with self.window() as window:
            window.toggle_mode()
            source = window.current.source
            source.set_text("HELLO hello")
            window.findbar._find.setText("hello")
            window.find_text("hello", True)
            self.assertEqual(source.textCursor().selectedText(), "HELLO")
            window.replace_text("hello", "hi")
            self.assertEqual(source.get_text(), "hi hello")
            self.assertEqual(window.findbar._feedback.text(), "找到匹配")
            window.replace_text("", "oops")
            self.assertEqual(source.get_text(), "hi hello")

    def test_rendered_find_reports_missing_and_matching_text(self):
        with self.window() as window:
            window.current.load_text("# Heading\n\nneedle in body")
            deadline = time.monotonic() + 5
            ready = []
            while time.monotonic() < deadline:
                ready.clear()
                window.current.preview.page().runJavaScript(
                    "typeof App !== 'undefined' && App.blocks.length > 2",
                    lambda value: ready.append(value))
                while not ready and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.002)
                if ready and ready[0]:
                    break
            self.assertTrue(ready and ready[0])
            window.findbar.open()
            for query, expected in (("no-match-123", "未找到匹配"), ("needle", "1 / 1 处匹配")):
                window.findbar._find.setText(query)
                window.find_text(query, True)
                deadline = time.monotonic() + 3
                while not window.findbar._feedback.text() and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.002)
                self.assertEqual(window.findbar._feedback.text(), expected)

    def test_broken_enabled_plugin_enters_recovery_instead_of_blocking_startup(self):
        broken = '''
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor
class P(Preprocessor):
    def run(self, lines): return ["BROKEN"]
class E(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(P(md), "broken", 40)
        raise RuntimeError("registration failed")
def makeExtension(**kwargs): return E()
'''
        svc = settings_service()
        with tempfile.TemporaryDirectory() as plugin_folder_name:
            plugin_folder = Path(plugin_folder_name)
            (plugin_folder / "broken.py").write_text(broken, encoding="utf-8")
            settings_data = AppSettings(auto_check_updates=False, enabled_plugins=["broken"])
            with patch.object(svc, "current", settings_data), patch.object(svc, "patch"), \
                    patch.object(MainWindow, "_restore_session"), \
                    patch("mdnote.services.plugin_loader.plugins_dir", return_value=plugin_folder), \
                    patch.object(MainWindow, "alert") as alert:
                window = MainWindow()
                window.show()
                self.app.processEvents()
                # The deferred plugin-failure notice fires via QTimer.singleShot(0).
                deadline = time.monotonic() + 3
                while not alert.called and time.monotonic() < deadline:
                    self.app.processEvents(); time.sleep(.005)
                self.assertTrue(alert.called)
                self.assertIn("broken", alert.call_args[0][0])
                # Engine is usable; broken extension's mutation is absent.
                self.assertNotIn("BROKEN",
                                 markdown_engine.markdown_engine().render("plain text"))
                for i in range(window.tabs.count()):
                    window.tabs.widget(i).dirty = False
                window.close()
                svc.off_change(window._on_settings_changed)
                window.deleteLater()

    def test_theme_applies_to_existing_and_new_tabs_and_new_tab_button_works(self):
        with self.window() as window:
            first = window.current
            second = window.add_session()
            svc = settings_service()
            svc.current.theme = "dark"
            window._on_settings_changed(svc.current)
            for session in (first, second):
                self.assertEqual(session.source.palette().color(QPalette.Base).name(), "#0d1117")
                self.assertEqual(session.source.palette().color(QPalette.Text).name(), "#c9d1d9")
                self.assertNotEqual(session.source._gutter_bg.name(), "#f6f8fa")
            count = window.tabs.count()
            QTest.mouseClick(window._new_tab_button, Qt.LeftButton)
            self.assertEqual(window.tabs.count(), count + 1)
            self.assertEqual(window.current.source.palette().color(QPalette.Base).name(), "#0d1117")
            self.assertEqual(window.statusbar._state.text(), "未命名")
            window.toggle_mode()
            self.app.processEvents()
            viewport = window.current.source.viewport()
            image = viewport.grab().toImage()
            self.assertEqual(image.pixelColor(50, image.height() - 20).name(), "#0d1117")


if __name__ == "__main__":
    unittest.main()
