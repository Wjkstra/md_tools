"""File-association startup, single-instance forwarding and sidebar defaults."""
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtNetwork import QLocalServer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mdnote import app as app_module
from mdnote.core import settings as settings_module
from mdnote.core.settings import AppSettings, SettingsService
from mdnote.ui.main_window import MainWindow, WELCOME


class StartupPathTests(unittest.TestCase):
    def test_filters_options_and_missing_files_dedupes_and_resolves_relative(self):
        with tempfile.TemporaryDirectory() as folder:
            old_cwd = Path.cwd()
            doc = Path(folder) / "note.md"
            doc.write_text("# hi", encoding="utf-8")
            try:
                os.chdir(folder)
                paths = app_module.requested_paths(
                    ["--debug", "note.md", str(doc), "../missing.md", ""])
            finally:
                os.chdir(old_cwd)
        self.assertEqual(paths, [str(doc.resolve())])

    def test_request_protocol_roundtrip(self):
        paths = [r"D:\我的文档\a.md", "D:/notes/b.md"]
        data = app_module.encode_open_request(paths)
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual(app_module.decode_open_request(data), paths)

    def test_decode_ignores_garbage_and_chunked_frames(self):
        data = b'not json\n' + app_module.encode_open_request(["a.md"]) + b'\xff\xfe'
        self.assertEqual(app_module.decode_open_request(data), ["a.md"])

    def test_parse_open_line_distinguishes_empty_ping_from_garbage(self):
        self.assertEqual(app_module.parse_open_line(b"[]"), [])
        self.assertEqual(app_module.parse_open_line(b'["a.md"]'), ["a.md"])
        self.assertIsNone(app_module.parse_open_line(b"not json"))
        self.assertIsNone(app_module.parse_open_line(b"123"))
        self.assertIsNone(app_module.parse_open_line(b'["a", 5]'))
        self.assertIsNone(app_module.parse_open_line(b"  "))


class SettingsMigrationTests(unittest.TestCase):
    @contextmanager
    def service_with(self, raw):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            if raw is not None:
                path.write_text(json.dumps(raw), encoding="utf-8")
            with patch.object(settings_module, "settings_file", return_value=path):
                yield SettingsService()

    def test_fresh_defaults_open_sidebar_on_outline_tab(self):
        with self.service_with(None) as svc:
            self.assertTrue(svc.current.sidebar_visible)
            self.assertEqual(svc.current.sidebar_tab, "outline")
            self.assertEqual(svc.current.settings_version, 1)

    def test_legacy_config_is_migrated_once(self):
        with self.service_with({"sidebar_visible": False, "sidebar_tab": "files"}) as svc:
            self.assertTrue(svc.current.sidebar_visible)
            self.assertEqual(svc.current.sidebar_tab, "outline")
            self.assertEqual(svc.current.settings_version, 1)

    def test_versioned_user_choice_to_hide_is_respected(self):
        raw = {"sidebar_visible": False, "sidebar_tab": "search", "settings_version": 1}
        with self.service_with(raw) as svc:
            self.assertFalse(svc.current.sidebar_visible)
            self.assertEqual(svc.current.sidebar_tab, "search")


class MainWindowStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    @contextmanager
    def window(self, open_paths=None):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(settings_module, "settings_file",
                              return_value=Path(folder) / "settings.json"):
                svc = SettingsService()
            svc.current.auto_check_updates = False
            with patch.object(settings_module, "_svc", svc), \
                    patch.object(MainWindow, "_restore_session"):
                window = MainWindow(open_paths=list(open_paths or []))
                window.show()
                self.app.processEvents()
                try:
                    yield window, svc, Path(folder)
                finally:
                    for index in range(window.tabs.count()):
                        window.tabs.widget(index).dirty = False
                    with patch(
                        "mdnote.ui.editor_session.EditorSession.flush_pending_edits",
                        lambda self: True,
                    ):
                        window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    self.app.processEvents()

    def test_startup_file_replaces_welcome_tab_and_roots_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            doc = Path(folder) / "opened.md"
            doc.write_text("# Startup doc", encoding="utf-8")
            with self.window(open_paths=[str(doc)]) as (window, svc, _):
                self.assertEqual(window.tabs.count(), 1)
                self.assertEqual(window.current.file_path, str(doc.resolve()))
                self.assertEqual(window.current._disk_text, "# Startup doc")
                self.assertNotIn(WELCOME[:20], window.tabs.widget(0)._disk_text)
                self.assertEqual(window.sidebar._folder, str(doc.resolve().parent))
                self.assertEqual(svc.current.last_folder, str(doc.resolve().parent))

    def test_tree_shows_only_markdown_files(self):
        with self.window() as (window, _svc, _folder):
            filters = window.sidebar._model.nameFilters()
            self.assertEqual(filters, ["*.md", "*.markdown"])
            self.assertFalse(window.sidebar._model.nameFilterDisables())

    def test_external_open_reuses_session_and_focuses_window(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "a.md"
            second = Path(folder) / "b.md"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")
            with self.window(open_paths=[str(first)]) as (window, _svc, _):
                raised = []
                window.raise_ = lambda: raised.append(True)
                window.activateWindow = lambda: None
                window.showNormal = lambda: None
                window.open_external_files([str(first), str(second)])
                self.assertEqual(window.tabs.count(), 2)
                self.assertEqual(window.current.file_path, str(second.resolve()))
                self.assertEqual(raised, [True])
                self.assertEqual(window.sidebar._folder, str(second.resolve().parent))

    def test_blank_startup_keeps_single_welcome_tab(self):
        with self.window() as (window, _svc, _folder):
            self.assertEqual(window.tabs.count(), 1)

    def test_opening_file_in_same_folder_keeps_tree_root_and_search(self):
        with tempfile.TemporaryDirectory() as folder:
            a = Path(folder) / "a.md"
            b = Path(folder) / "b.md"
            other = Path(folder) / "sub"
            other.mkdir()
            c = other / "c.md"
            for f in (a, b, c):
                f.write_text("x", encoding="utf-8")
            with self.window(open_paths=[str(a)]) as (window, _svc, _):
                calls = []
                original = window.sidebar.open_folder
                window.sidebar.open_folder = lambda folder, **kw: calls.append(folder)
                window.open_file(str(b))
                self.assertEqual(calls, [])  # 同目录：不重设根、不清搜索
                window.open_file(str(c))
                self.assertEqual(calls, [str(other.resolve())])
                window.sidebar.open_folder = original


class SingleInstanceForwardingTests(unittest.TestCase):
    """Windows 上 QLocalSocket 同进程配合阻塞 wait 会丢数据（Qt 已知限制），
    所以客户端用非阻塞连接，在事件循环中完成写入，贴近真实跨进程时序。"""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_second_instance_forwards_paths_to_running_window(self):
        from PySide6.QtNetwork import QLocalSocket

        # A unique pipe name keeps the test isolated from a real running
        # MdNote instance (Windows allows duplicate named-pipe servers).
        token = f"mdnote-test-{os.getpid()}-{id(self)}"
        server = QLocalServer()
        QLocalServer.removeServer(token)
        self.addCleanup(QLocalServer.removeServer, token)
        self.assertTrue(server.listen(token))

        received = []

        class FakeWindow:
            def open_external_files(self, paths):
                received.append(paths)

        fake = FakeWindow()
        server.newConnection.connect(
            lambda: app_module._serve_open_requests(server, fake))

        client = QLocalSocket()
        client.connectToServer(token)
        for _ in range(50):
            if client.state() == QLocalSocket.ConnectedState:
                break
            self.app.processEvents()
            QTest.qWait(10)
        self.assertEqual(client.state(), QLocalSocket.ConnectedState)

        with tempfile.TemporaryDirectory() as folder:
            doc = Path(folder) / "via-association.md"
            doc.write_text("x", encoding="utf-8")
            payload = app_module.encode_open_request([str(doc)])
            client.write(payload)
            client.flush()
            for _ in range(100):
                self.app.processEvents()
                if received:
                    break
                QTest.qWait(10)
        client.disconnectFromServer()
        server.close()
        self.assertEqual(received, [[str(doc.resolve())]])

    def test_empty_ping_reaches_window_but_garbage_does_not(self):
        from PySide6.QtNetwork import QLocalSocket

        token = f"mdnote-test-{os.getpid()}-{id(self)}-empty"
        server = QLocalServer()
        QLocalServer.removeServer(token)
        self.addCleanup(QLocalServer.removeServer, token)
        self.assertTrue(server.listen(token))

        received = []

        class FakeWindow:
            def open_external_files(self, paths):
                received.append(paths)

        fake = FakeWindow()
        server.newConnection.connect(
            lambda: app_module._serve_open_requests(server, fake))

        client = QLocalSocket()
        client.connectToServer(token)
        for _ in range(50):
            if client.state() == QLocalSocket.ConnectedState:
                break
            self.app.processEvents()
            QTest.qWait(10)
        # A valid empty array is a raise-window ping; garbage is dropped.
        client.write(b"[]\n")
        client.write(b"broken line\n")
        client.flush()
        for _ in range(50):
            self.app.processEvents()
            if received:
                break
            QTest.qWait(10)
        client.disconnectFromServer()
        server.close()
        self.assertEqual(received, [[]])


if __name__ == "__main__":
    unittest.main()
