"""Offline service regression tests; no production settings, network or installers."""

import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QUrl
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication

from mdnote import __version__
from mdnote.core.settings import SettingsService
from mdnote.services import markdown_engine as engine_module
from mdnote.services.plugin_loader import load_enabled
from mdnote.services.updater import ReleaseInfo, UpdateManager, parse_manifest
from scripts.prepare_installer import build_inventory, read_app_version
from scripts import make_manifest


class Event:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class Reply:
    def __init__(self, payload=b"", url="https://updates.invalid/package.exe"):
        self.payload = payload
        self.address = url
        self.readyRead = Event()
        self.finished = Event()
        self.downloadProgress = Event()
        self.aborted = False
        self.deleted = False
        self.failure = QNetworkReply.NetworkError.NoError

    def readAll(self):
        result, self.payload = self.payload, b""
        return result

    def bytesAvailable(self):
        return len(self.payload)

    def url(self):
        return QUrl(self.address)

    def error(self):
        return self.failure

    def errorString(self):
        return "simulated network failure"

    def abort(self):
        self.aborted = True
        self.failure = QNetworkReply.NetworkError.OperationCanceledError
        self.finished.emit()

    def deleteLater(self):
        self.deleted = True


class Network:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def get(self, request):
        self.requests.append(request)
        return self.replies.pop(0)


class UpdateSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        real_mkstemp = tempfile.mkstemp
        self.temp_patch = patch("mdnote.services.updater.tempfile.mkstemp",
                                side_effect=lambda **kwargs: real_mkstemp(dir=self.folder.name, **kwargs))
        self.temp_patch.start()
        self.addCleanup(self.temp_patch.stop)
        self.payload = b"verified installer bytes"
        self.release = ReleaseInfo("9.0.0", "", "https://updates.invalid/package.exe?sig=123",
                                   hashlib.sha256(self.payload).hexdigest())
        self.manager = UpdateManager("https://updates.invalid/latest.json")
        self.manager._release = self.release
        self.success = []
        self.failures = []
        self.manager.download_finished.connect(self.success.append)
        self.manager.download_failed.connect(self.failures.append)
        self.addCleanup(self.manager.shutdown)

    def test_download_reentry_and_stale_callbacks_do_not_touch_new_download(self):
        first, second = Reply(self.payload), Reply(self.payload)
        network = self.manager._nam = Network(first, second)
        self.manager.download()
        self.manager.download()
        self.assertEqual(len(network.requests), 1)
        self.assertEqual(Path(self.manager._tmp_path).suffix, ".exe")
        first.finished.emit()
        self.assertEqual(len(self.success), 1)
        self.assertEqual(Path(self.success[0]).read_bytes(), self.payload)
        self.manager.download()
        first.readyRead.emit()
        first.finished.emit()
        self.assertEqual(second.payload, self.payload)
        self.assertTrue(self.manager.busy)
        second.finished.emit()
        self.assertEqual(len(self.success), 2)
        self.assertEqual(self.failures, [])

    def test_download_uses_original_release_digest(self):
        reply = Reply(self.payload)
        self.manager._nam = Network(reply)
        self.manager.download()
        self.manager._release = ReleaseInfo("10.0.0", "", self.release.url, "0" * 64)
        reply.finished.emit()
        self.assertEqual(len(self.success), 1)
        self.assertEqual(self.failures, [])

    def test_disk_write_error_aborts_and_emits_failure_once(self):
        reply = Reply(self.payload)
        self.manager._nam = Network(reply)
        self.manager.download()
        stream = self.manager._file

        class BrokenStream:
            def write(self, _chunk):
                raise OSError("disk full")

            def close(self):
                stream.close()

        self.manager._file = BrokenStream()
        reply.readyRead.emit()
        reply.finished.emit()
        self.assertTrue(reply.aborted)
        self.assertFalse(self.manager.busy)
        self.assertEqual(self.success, [])
        self.assertEqual(len(self.failures), 1)
        self.assertIn("disk full", self.failures[0])
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_flush_failure_never_reports_success_and_removes_package(self):
        reply = Reply(self.payload)
        self.manager._nam = Network(reply)
        self.manager.download()
        with patch("mdnote.services.updater.os.fsync", side_effect=OSError("flush failed")):
            reply.finished.emit()
        self.assertEqual(self.success, [])
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_failure_opening_file_cleans_created_temp_file(self):
        self.manager._nam = Network(Reply(self.payload))
        with patch("mdnote.services.updater.os.fdopen", side_effect=OSError("cannot open")):
            self.manager.download()
        self.assertFalse(self.manager.busy)
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_digest_mismatch_and_insecure_redirect_fail_closed(self):
        for payload, url in ((b"modified", self.release.url),
                             (self.payload, "http://updates.invalid/package.exe")):
            with self.subTest(url=url):
                reply = Reply(payload, url)
                self.manager._nam = Network(reply)
                self.manager.download()
                reply.finished.emit()
                self.assertFalse(self.manager.busy)
                self.assertEqual(self.success, [])
                self.assertEqual(list(Path(self.folder.name).iterdir()), [])
        self.assertEqual(len(self.failures), 2)

    def test_programmatically_supplied_release_still_requires_digest(self):
        self.manager._release.sha256 = ""
        network = self.manager._nam = Network(Reply(self.payload))
        self.manager.download()
        self.assertEqual(network.requests, [])
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_changing_source_aborts_old_check_and_ignores_its_result(self):
        raw = json.dumps({"version": "9.0.0", "url": self.release.url,
                          "sha256": self.release.sha256}).encode()
        first, second = Reply(raw), Reply(raw)
        network = self.manager._nam = Network(first, second)
        releases, completed = [], []
        self.manager.update_available.connect(releases.append)
        self.manager.check_finished.connect(completed.append)
        self.manager.check()
        self.manager.check()
        self.assertEqual(len(network.requests), 1)
        self.manager.set_manifest_url("https://another.invalid/latest.json")
        self.assertTrue(first.aborted)
        self.assertIsNone(self.manager.release)
        first.finished.emit()
        self.assertEqual(releases, [])
        self.manager.check()
        second.finished.emit()
        self.assertEqual(len(releases), 1)
        self.assertEqual(completed, [True])
        self.assertEqual(network.requests[1].transferTimeout(), 30_000)
        self.assertEqual(network.requests[1].attribute(QNetworkRequest.RedirectPolicyAttribute),
                         QNetworkRequest.NoLessSafeRedirectPolicy)

    def test_no_new_version_reports_successful_completion(self):
        raw = json.dumps({"version": __version__, "url": self.release.url,
                          "sha256": self.release.sha256}).encode()
        reply = Reply(raw)
        self.manager._nam = Network(reply)
        completed = []
        self.manager.check_finished.connect(completed.append)
        self.manager.check()
        reply.finished.emit()
        self.assertEqual(completed, [False])
        self.assertIsNone(self.manager.release)

    def test_insecure_manifest_url_makes_no_request(self):
        network = self.manager._nam = Network(Reply())
        failures = []
        self.manager.check_failed.connect(failures.append)
        self.manager.set_manifest_url("http://updates.invalid/latest.json")
        self.manager.check()
        self.assertEqual(network.requests, [])
        self.assertEqual(len(failures), 1)

    def test_shutdown_aborts_and_cleans_active_download(self):
        reply = Reply(self.payload)
        self.manager._nam = Network(reply)
        self.manager.download()
        self.manager.shutdown()
        self.assertTrue(reply.aborted)
        self.assertEqual(self.success, [])
        self.assertEqual(self.failures, [])
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])


class ManifestSafetyTests(unittest.TestCase):
    def test_invalid_manifests_are_rejected(self):
        base = {"version": "9.0.0", "url": "https://updates.invalid/setup.exe", "sha256": "a" * 64}
        invalid = [[], {**base, "sha256": ""}, {**base, "sha256": "z" * 64},
                   {**base, "sha256": 123}, {**base, "url": "http://updates.invalid/setup.exe"},
                   {**base, "url": "file:///C:/setup.exe"},
                   {**base, "url": "https://user:password@updates.invalid/setup.exe"},
                   {**base, "version": "invalid"}, {**base, "version": "2" * 5000},
                   {**base, "minVersion": []}]
        for value in invalid:
            with self.subTest(value=str(value)[:80]), self.assertRaises(ValueError):
                parse_manifest(json.dumps(value))
        self.assertEqual(parse_manifest(json.dumps(base)).sha256, "a" * 64)


class SettingsTransactionTests(unittest.TestCase):
    def test_failed_patch_preserves_memory_disk_and_listeners(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            with patch("mdnote.core.settings.settings_file", return_value=target):
                service = SettingsService()
            service.save()
            previous = service.current
            old_disk = target.read_bytes()
            observed = []
            service.on_change(observed.append)
            with patch("mdnote.core.settings.atomic_write_text", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    service.patch(theme="dark", enabled_plugins=["new"])
            self.assertIs(service.current, previous)
            self.assertEqual(target.read_bytes(), old_disk)
            self.assertEqual(observed, [])

    def test_successful_patch_notifies_after_persistence_and_supports_unsubscribe(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "settings.json"
            with patch("mdnote.core.settings.settings_file", return_value=target):
                service = SettingsService()
            observed = []

            def observer(settings):
                observed.append(json.loads(target.read_text(encoding="utf-8")))
                self.assertIs(service.current, settings)
                self.assertEqual(observed[-1], asdict(settings))

            service.on_change(observer)
            service.on_change(observer)
            plugins = ["good"]
            service.patch(theme="dark", enabled_plugins=plugins)
            plugins.append("unexpected")
            self.assertEqual(service.current.enabled_plugins, ["good"])
            self.assertEqual(len(observed), 1)
            service.off_change(observer)
            service.patch(theme="light")
            self.assertEqual(len(observed), 1)


class PluginRecoveryTests(unittest.TestCase):
    def test_registration_failure_does_not_break_startup_or_leave_mutations(self):
        good = '''
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor
class P(Preprocessor):
    def run(self, lines): return [line.replace("TOK", "GOOD") for line in lines]
class E(Extension):
    def extendMarkdown(self, md): md.preprocessors.register(P(md), "good", 31)
def makeExtension(**kwargs): return E()
'''
        broken = '''
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor
class P(Preprocessor):
    def run(self, lines): return ["BROKEN MUTATION"]
class E(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(P(md), "broken", 40)
        raise RuntimeError("registration failed")
def makeExtension(**kwargs): return E()
'''
        with tempfile.TemporaryDirectory() as folder, patch.object(engine_module, "_engine", None):
            directory = Path(folder)
            (directory / "good.py").write_text(good, encoding="utf-8")
            (directory / "broken.py").write_text(broken, encoding="utf-8")
            errors = engine_module.reconfigure(["good", "broken"], directory)
            self.assertEqual([name for name, _error in errors], ["broken"])
            result = engine_module.markdown_engine().render("TOK")
            self.assertIn("GOOD", result)
            self.assertNotIn("BROKEN MUTATION", result)
            errors = engine_module.reconfigure(["broken", "good"], directory)
            self.assertEqual([name for name, _error in errors], ["broken"])
            self.assertIn("GOOD", engine_module.markdown_engine().render("TOK"))

    def test_invalid_factory_return_and_unreadable_plugin_directory_are_reported(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(engine_module, "_engine", None):
            directory = Path(folder)
            (directory / "invalid.py").write_text("def makeExtension(): return object()", encoding="utf-8")
            instances, errors = load_enabled(["invalid"], directory)
            self.assertEqual(instances, [])
            self.assertEqual(errors[0][0], "invalid")
            with patch("mdnote.services.plugin_loader.discover", side_effect=OSError("denied")):
                errors = engine_module.reconfigure(["invalid"], directory)
            self.assertIn("denied", errors[0][1])

    def test_mermaid_fences_survive_highlighting_and_escape_html(self):
        engine = engine_module.MarkdownEngine()
        result = engine.render("~~~mermaid\ngraph TD\nA[<script>bad</script>]-->B\n~~~")
        self.assertIn('class="language-mermaid"', result)
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)
        self.assertIn("codehilite", engine.render("~~~python\nprint(123)\n~~~"))
        nested = engine.render("~~~~text\n~~~mermaid\ngraph TD\n~~~\n~~~~")
        self.assertNotIn('class="language-mermaid"', nested)


class InstallerInventoryTests(unittest.TestCase):
    SETUP_NSI = ROOT if False else Path(__file__).resolve().parent.parent / "installer" / "setup.nsi"

    def test_setup_enforces_dedicated_install_directory(self):
        script = self.SETUP_NSI.read_text(encoding="utf-8-sig")
        # Directory page leave, silent init path and core section all check it.
        self.assertIn("Function ValidateInstallDir", script)
        self.assertIn("MUI_PAGE_CUSTOMFUNCTION_LEAVE ValidateInstallDir", script)
        self.assertEqual(script.count("Call ValidateInstallDir"), 2)
        # Existing installs identified by application-owned markers...
        self.assertIn(r'"$INSTDIR\MdNote.exe"', script)
        self.assertIn(r'"$INSTDIR\Uninstall.exe"', script)
        # ...other non-empty folders detected by directory enumeration...
        self.assertIn('FindFirst $R0 $R1 "$INSTDIR\\*"', script)
        # ...silent installs abort, and recursion deletion is never used.
        self.assertIn("VID_SilentFail:", script)
        self.assertRegex(script[script.index("VID_SilentFail:"):script.index("FunctionEnd", script.index("VID_SilentFail:"))],
                         r"SetErrorLevel\s+3\s+Quit")
        self.assertNotRegex(script, r"RMDir\s+/r")

    def test_inventory_cleanup_preserves_unlisted_files_in_application_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            build, installed = base / "build", base / "installed"
            for target in (build, installed):
                (target / "_internal").mkdir(parents=True)
                (target / "MdNote.exe").write_bytes(b"app")
                (target / "_internal" / "runtime.dll").write_bytes(b"runtime")
            user_files = [installed / "notes.md", installed / "_internal" / "user.txt"]
            for target in user_files:
                target.write_text("keep", encoding="utf-8")
            contents = build_inventory(build, read_app_version())
            self.assertNotRegex(contents, r"(?m)^\s*RMDir\s+/r")
            delete_targets = re.findall(r'^  Delete "\$INSTDIR\\(.*)"$', contents, re.MULTILINE)
            for relative in delete_targets:
                target = (installed / relative.replace("\\", "/")).resolve()
                self.assertTrue(target.is_relative_to(installed.resolve()))
                target.unlink()
            directories = re.findall(r'^  RMDir "\$INSTDIR\\(.*)"$', contents, re.MULTILINE)
            for relative in directories:
                target = (installed / relative.replace("\\", "/")).resolve()
                self.assertTrue(target.is_relative_to(installed.resolve()))
                try:
                    target.rmdir()
                except OSError:
                    pass
            self.assertTrue(all(target.read_text(encoding="utf-8") == "keep" for target in user_files))
            self.assertFalse((installed / "MdNote.exe").exists())
            self.assertFalse((installed / "_internal" / "runtime.dll").exists())
            self.assertIn(f'!define APP_VERSION "{__version__}"', contents)

    def test_manifest_defaults_to_canonical_version_and_hashes_package(self):
        with tempfile.TemporaryDirectory() as folder:
            package, output = Path(folder) / "package.exe", Path(folder) / "latest.json"
            package.write_bytes(b"package")
            argv = ["make_manifest.py", "--installer", str(package), "--out", str(output),
                    "--url", "https://updates.invalid/package.exe"]
            with patch("sys.argv", argv), contextlib.redirect_stdout(io.StringIO()):
                make_manifest.main()
            release = parse_manifest(output.read_bytes())
            self.assertEqual(release.version, __version__)
            self.assertEqual(release.sha256, hashlib.sha256(b"package").hexdigest())
            with patch("sys.argv", argv + ["--version", "99.0.0"]), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    make_manifest.main()
            self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
