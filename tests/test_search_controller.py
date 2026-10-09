"""Cancellation, latest-request ordering and Qt thread lifecycle regressions."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QEvent, QThread
from PySide6.QtWidgets import QApplication
from mdnote.services.search_service import SearchController, SearchHit, search
from mdnote.ui.sidebar import Sidebar


class SearchControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            time.sleep(.002)
        self.fail("Timed out waiting for search")

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_latest_request_only_and_gui_thread_delivery(self):
        controller = SearchController()
        entered = threading.Event()
        release = threading.Event()
        calls = []
        delivered = []
        threads = []

        def fake_search(root, query, **kwargs):
            calls.append(query)
            if query == "first":
                entered.set()
                release.wait(2)
            return [SearchHit(Path(root) / "note.md", "content", 1, query)]

        def receive(payload):
            delivered.append(payload[0]["text"])
            threads.append(QThread.currentThread())

        controller.results.connect(receive)
        try:
            with patch("mdnote.services.search_service.search", side_effect=fake_search):
                controller.request(".", "first")
                self.assertTrue(entered.wait(1))
                controller.request(".", "second")
                controller.request(".", "latest")
                release.set()
                self.wait_for(lambda: bool(delivered) and controller._worker is None)
            self.assertEqual(calls, ["first", "latest"])
            self.assertEqual(delivered, ["latest"])
            self.assertEqual(threads, [self.app.thread()])
        finally:
            release.set()
            self.assertTrue(controller.shutdown())
            controller.deleteLater()

    def test_shutdown_cancels_active_work_and_discards_queued_results(self):
        controller = SearchController()
        entered = threading.Event()
        stopped = threading.Event()
        delivered = []

        def fake_search(root, query, cancelled, **kwargs):
            entered.set()
            while not cancelled():
                time.sleep(.002)
            stopped.set()
            return []

        controller.results.connect(delivered.append)
        try:
            with patch("mdnote.services.search_service.search", side_effect=fake_search):
                controller.request(".", "query")
                self.assertTrue(entered.wait(1))
                self.assertTrue(controller.shutdown())
                self.assertTrue(stopped.is_set())
                self.app.processEvents()
            self.assertEqual(delivered, [])
            self.assertIsNone(controller._worker)
        finally:
            controller.shutdown()
            controller.deleteLater()

    def test_shutdown_timeout_keeps_worker_alive_until_it_stops(self):
        controller = SearchController()
        entered = threading.Event()
        release = threading.Event()

        def fake_search(*args, **kwargs):
            entered.set()
            release.wait(2)
            return []

        try:
            with patch("mdnote.services.search_service.search", side_effect=fake_search):
                controller.request(".", "query")
                self.assertTrue(entered.wait(1))
                self.assertFalse(controller.shutdown(1))
                self.assertIsNotNone(controller._worker)
                release.set()
                self.assertTrue(controller.shutdown())
        finally:
            release.set()
            controller.shutdown()
            controller.deleteLater()

    def test_folder_change_and_query_edit_clear_previous_results(self):
        sidebar = Sidebar()
        try:
            with tempfile.TemporaryDirectory() as folder:
                (Path(folder) / "note.md").write_text("needle", encoding="utf-8")
                sidebar.open_folder(folder)
                sidebar._search_box.setText("needle")
                sidebar._run_search()
                self.wait_for(lambda: sidebar._search_results.count() == 1)
                sidebar._search_box.clear()
                self.assertEqual(sidebar._search_results.count(), 0)
                self.assertEqual(sidebar._search_status.text(), "")
                sidebar._search_box.setText("needle")
                sidebar._run_search()
                self.wait_for(lambda: sidebar._search_results.count() == 1)
                sidebar.open_folder(folder)
                self.assertEqual(sidebar._search_results.count(), 0)
        finally:
            self.assertTrue(sidebar.shutdown_search())
            sidebar.deleteLater()

    def test_search_checks_cancellation_between_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "note.md").write_text("needle\n" * 100, encoding="utf-8")
            checks = 0

            def cancelled():
                nonlocal checks
                checks += 1
                return checks >= 5

            hits = search(folder, "needle", cancelled=cancelled)
            self.assertGreater(len(hits), 0)
            self.assertLess(len(hits), 100)
            self.assertEqual(search(folder, "needle", cancelled=lambda: True), [])


if __name__ == "__main__":
    unittest.main()
