"""Update retries, byte ranges, verified cache and installation-path regressions."""
import ctypes
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from mdnote.services import installer_service
from mdnote.services.updater import ReleaseInfo, UpdateManager, parse_manifest
from scripts import make_manifest
import test_service_safety as safety
import test_input_workflow as workflow


class UpdateReliabilityTests(unittest.TestCase):
    setUpClass = classmethod(safety.UpdateSafetyTests.setUpClass.__func__)
    setUp = safety.UpdateSafetyTests.setUp

    def retry_now(self):
        self.assertTrue(self.manager.busy)
        self.assertTrue(self.manager._retry_timer.isActive())
        self.manager._retry_timer.stop()
        self.manager._start_attempt()

    def interrupted(self, prefix=b"verified "):
        first = safety.Reply(prefix)
        first.failure = QNetworkReply.NetworkError.RemoteHostClosedError
        return first

    def ranged(self, payload, offset):
        reply = safety.Reply(payload)
        reply.status = 206
        reply.headers[b"Content-Range"] = f"bytes {offset}-{offset + len(payload) - 1}/{len(self.payload)}".encode()
        return reply

    def test_compatibility_request_and_inactivity_timeout(self):
        network = self.manager._nam = safety.Network(safety.Reply(self.payload))
        self.manager.download()
        request = network.requests[0]
        self.assertIs(request.attribute(QNetworkRequest.Http2AllowedAttribute), False)
        self.assertEqual(request.transferTimeout(), 60_000)
        self.assertEqual(bytes(request.rawHeader("Accept-Encoding")), b"identity")
        self.assertTrue(bytes(request.rawHeader("User-Agent")).startswith(b"MdNote/"))

    def test_transient_failure_resumes_without_repeating_prefix(self):
        prefix = b"verified "
        first, second = self.interrupted(prefix), self.ranged(self.payload[len(prefix):], len(prefix))
        network = self.manager._nam = safety.Network(first, second)
        self.manager.download()
        first.finished.emit()
        self.assertEqual(self.failures, [])
        self.manager.download()  # Retry wait is still busy; no parallel request.
        self.assertEqual(len(network.requests), 1)
        self.retry_now()
        self.assertEqual(bytes(network.requests[1].rawHeader("Range")), b"bytes=9-")
        first.readyRead.emit()
        first.finished.emit()  # Late events cannot overwrite the retry.
        second.finished.emit()
        self.assertEqual(Path(self.success[0]).read_bytes(), self.payload)
        self.assertEqual(self.failures, [])

    def test_server_ignoring_range_replaces_partial_file(self):
        first, second = self.interrupted(), safety.Reply(self.payload)
        self.manager._nam = safety.Network(first, second)
        self.manager.download()
        first.finished.emit()
        self.retry_now()
        second.finished.emit()
        self.assertEqual(Path(self.success[0]).read_bytes(), self.payload)

    def test_wrong_range_is_never_accepted(self):
        first, second = self.interrupted(), self.ranged(self.payload, 0)
        self.manager._nam = safety.Network(first, second)
        self.manager.download()
        first.finished.emit()
        self.retry_now()
        second.readyRead.emit()
        second.finished.emit()
        self.assertEqual(self.success, [])
        self.assertEqual(len(self.failures), 1)
        self.assertIn("续传位置", self.failures[0])
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_range_beyond_end_restarts_from_zero(self):
        first, rejected, third = self.interrupted(), safety.Reply(b"error page"), safety.Reply(self.payload)
        rejected.status = 416
        network = self.manager._nam = safety.Network(first, rejected, third)
        self.manager.download()
        first.finished.emit()
        self.retry_now()
        rejected.finished.emit()
        self.retry_now()
        self.assertEqual(bytes(network.requests[2].rawHeader("Range")), b"")
        third.finished.emit()
        self.assertEqual(Path(self.success[0]).read_bytes(), self.payload)

    def test_retry_limit_emits_once_and_cleans_nonpersistent_download(self):
        replies = [self.interrupted(b"") for _ in range(3)]
        network = self.manager._nam = safety.Network(*replies)
        self.manager.download()
        for index, reply in enumerate(replies):
            reply.finished.emit()
            if index < 2:
                self.retry_now()
        self.assertEqual(len(network.requests), 3)
        self.assertFalse(self.manager.busy)
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_cancel_during_retry_wait_prevents_later_request(self):
        first = self.interrupted()
        network = self.manager._nam = safety.Network(first)
        self.manager.download()
        first.finished.emit()
        self.manager.shutdown()
        self.assertFalse(self.manager._retry_timer.isActive())
        self.manager._start_attempt()
        QCoreApplication.processEvents()
        self.assertEqual(len(network.requests), 1)
        self.assertEqual(self.failures, [])
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_http_error_body_is_discarded_before_mirror_retry(self):
        first, second = safety.Reply(b"server error"), safety.Reply(self.payload)
        first.status = 503
        self.release.mirrors = ("https://mirror.invalid/setup.exe",)
        network = self.manager._nam = safety.Network(first, second)
        self.manager.download()
        first.readyRead.emit()
        self.assertEqual(self.manager._file.tell(), 0)
        first.finished.emit()
        self.retry_now()
        self.assertEqual(network.requests[1].url().host(), "mirror.invalid")
        second.finished.emit()
        self.assertEqual(Path(self.success[0]).read_bytes(), self.payload)

    def test_tls_failure_is_terminal_and_never_bypasses_verification(self):
        reply = safety.Reply()
        reply.failure = QNetworkReply.NetworkError.SslHandshakeFailedError
        network = self.manager._nam = safety.Network(reply)
        self.manager.download()
        reply.finished.emit()
        self.assertFalse(self.manager.busy)
        self.assertFalse(self.manager._retry_timer.isActive())
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(len(network.requests), 1)

    def test_every_published_mirror_can_be_reached_with_bounded_retries(self):
        self.release.mirrors = tuple(f"https://mirror{i}.invalid/setup.exe" for i in range(3))
        replies = [safety.Reply(b"unavailable") for _ in range(3)] + [safety.Reply(self.payload)]
        for reply in replies[:-1]:
            reply.status = 503
        network = self.manager._nam = safety.Network(*replies)
        self.manager.download()
        for reply in replies[:-1]:
            reply.finished.emit()
            self.assertLessEqual(self.manager._retry_timer.interval(), 4000)
            self.retry_now()
        replies[-1].finished.emit()
        self.assertEqual(network.requests[-1].url().host(), "mirror2.invalid")
        self.assertEqual(len(network.requests), 4)
        self.assertEqual(Path(self.success[0]).read_bytes(), self.payload)

    def test_cache_retains_partial_across_managers_and_reuses_verified_exe(self):
        cache = Path(self.folder.name) / "cache"
        self.manager._cache_dir = cache
        first = self.interrupted()
        self.manager._nam = safety.Network(first)
        self.manager.download()
        first.finished.emit()
        self.manager.shutdown()
        partial = cache / (self.release.sha256 + ".part")
        self.assertEqual(partial.read_bytes(), b"verified ")
        second = self.ranged(self.payload[9:], 9)
        manager = UpdateManager("https://updates.invalid/latest.json", cache_dir=cache)
        self.addCleanup(manager.shutdown)
        manager._release = self.release
        network = manager._nam = safety.Network(second)
        done = []
        manager.download_finished.connect(done.append)
        manager.download()
        self.assertEqual(bytes(network.requests[0].rawHeader("Range")), b"bytes=9-")
        second.finished.emit()
        self.assertFalse(partial.exists())
        self.assertEqual(Path(done[0]).read_bytes(), self.payload)
        manager.download()
        self.assertEqual(len(network.requests), 1)
        self.assertEqual(len(done), 2)
        Path(done[0]).write_bytes(b"corrupted cache")
        replacement = safety.Reply(self.payload)
        network.replies.append(replacement)
        manager.download()
        replacement.finished.emit()
        self.assertEqual(len(network.requests), 2)
        self.assertEqual(Path(done[-1]).read_bytes(), self.payload)

    def test_complete_partial_cache_needs_no_network(self):
        cache = Path(self.folder.name)
        (cache / (self.release.sha256 + ".part")).write_bytes(self.payload)
        self.manager._cache_dir = cache
        network = self.manager._nam = safety.Network()
        self.manager.download()
        self.assertEqual(network.requests, [])
        self.assertEqual(Path(self.success[0]).read_bytes(), self.payload)

    def test_cached_digest_mismatch_removes_partial_and_never_launches(self):
        self.manager._cache_dir = Path(self.folder.name)
        reply = safety.Reply(b"modified installer")
        self.manager._nam = safety.Network(reply)
        self.manager.download()
        reply.finished.emit()
        self.assertEqual(self.success, [])
        self.assertEqual(len(self.failures), 1)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_resume_progress_includes_saved_prefix_and_shows_speed(self):
        first, second = self.interrupted(), self.ranged(self.payload[9:], 9)
        self.manager._nam = safety.Network(first, second)
        values, statuses = [], []
        self.manager.download_progress.connect(values.append)
        self.manager.download_status.connect(statuses.append)
        self.manager.download()
        first.finished.emit()
        self.retry_now()
        second.downloadProgress.emit(2, len(self.payload) - 9)
        self.assertEqual(values[-1], int(11 * 100 / len(self.payload)))
        self.assertIn("KB/s", statuses[-1])
        self.assertIn("MB", statuses[-1])

    def test_only_publisher_supplied_https_mirrors_are_accepted(self):
        base = dict(version="9.0.0", url=self.release.url, sha256=self.release.sha256)
        for invalid in ["https://mirror.invalid/setup.exe", ["http://mirror.invalid/setup.exe"], [None], ["https://user:secret@mirror.invalid/setup.exe"]]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                parse_manifest(json.dumps({**base, "mirrors": invalid}))
        parsed = parse_manifest(json.dumps({**base, "mirrors": ["https://mirror.invalid/setup.exe"] * 2}))
        self.assertEqual(parsed.mirrors, ("https://mirror.invalid/setup.exe",))

    def test_manifest_cli_writes_validated_fallback_sources(self):
        package, output = Path(self.folder.name) / "setup.exe", Path(self.folder.name) / "latest.json"
        package.write_bytes(self.payload)
        args = ["make_manifest.py", "--installer", str(package), "--out", str(output),
                "--url", self.release.url, "--mirror", "https://mirror.invalid/setup.exe"]
        with patch.object(sys, "argv", args), patch("builtins.print"):
            make_manifest.main()
        self.assertEqual(parse_manifest(output.read_bytes()).mirrors, ("https://mirror.invalid/setup.exe",))
        with patch.object(sys, "argv", args + ["--mirror", "http://insecure.invalid/setup.exe"]), patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                make_manifest.main()

    def test_completed_cache_keeps_two_installers_and_preserves_unrelated_files(self):
        cache = Path(self.folder.name)
        self.manager._cache_dir = cache
        (cache / "notes.txt").write_text("keep")
        for char in "123":
            (cache / (char * 64 + ".exe")).write_bytes(b"old")
        (cache / ("4" * 64 + ".part")).write_bytes(b"old partial")
        reply = safety.Reply(self.payload)
        self.manager._nam = safety.Network(reply)
        self.manager.download()
        reply.finished.emit()
        self.assertEqual(len(list(cache.glob("*.exe"))), 2)
        self.assertEqual(list(cache.glob("*.part")), [])
        self.assertEqual((cache / "notes.txt").read_text(), "keep")


class InstallerDestinationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows shell arguments")
    def test_elevated_installer_gets_current_unicode_directory_as_final_argument(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            installed = root / "中文 安装位置"
            installed.mkdir()
            executable = installed / "MdNote.exe"
            executable.write_bytes(b"test")
            package = root / "setup.exe"
            package.write_bytes(b"test")
            launch = Mock(return_value=33)
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)), patch.object(ctypes.windll.shell32, "ShellExecuteW", launch):
                installer_service.launch_installer(str(package))
            self.assertEqual(launch.call_args.args[1], "runas")
            self.assertEqual(launch.call_args.args[3], "/D=" + str(installed))

    @unittest.skipUnless(os.name == "nt", "Windows shell arguments")
    def test_explicit_destination_and_uac_cancellation(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / "setup.exe"
            package.write_bytes(b"test")
            with patch.object(ctypes.windll.shell32, "ShellExecuteW", return_value=5) as launch:
                with self.assertRaises(OSError):
                    installer_service.launch_installer(str(package), install_dir=folder)
            self.assertEqual(launch.call_args.args[3], "/D=" + folder)


class UpdateWindowTests(unittest.TestCase):
    setUpClass = classmethod(workflow.InputWorkflowTests.setUpClass.__func__)
    window = workflow.InputWorkflowTests.window

    def test_update_handoff_passes_executable_directory_and_respects_close_cancel(self):
        with self.window() as (window, _, folder), patch.object(window, "alert"), patch.object(installer_service, "launch_installer") as launch:
            executable = folder / "MdNote.exe"
            with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
                with patch.object(window, "close", return_value=False):
                    window._on_download_finished("verified.exe")
                launch.assert_not_called()
                with patch.object(window, "close", return_value=True):
                    window._on_download_finished("verified.exe")
                launch.assert_called_once_with("verified.exe", install_dir=folder)


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "cryptography required for local TLS fixture")
class RealHttpsDownloadTests(unittest.TestCase):
    setUpClass = classmethod(safety.UpdateSafetyTests.setUpClass.__func__)

    def test_real_tls_disconnect_then_range_resume(self):
        import datetime
        import ipaddress
        import socket
        import ssl
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        from PySide6.QtNetwork import QNetworkProxy, QSslCertificate

        payload = b"local HTTPS installer fixture\n" * 8192
        prefix_size = 16384
        received_ranges = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def do_GET(self):
                offset = self.headers.get("Range")
                received_ranges.append(offset)
                if offset is None:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload[:prefix_size])
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    self.close_connection = True
                else:
                    start = int(offset.removeprefix("bytes=").removesuffix("-"))
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(payload)-1}/{len(payload)}")
                    self.send_header("Content-Length", str(len(payload) - start))
                    self.end_headers()
                    self.wfile.write(payload[start:])

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "MdNote local test")])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=1))
                    .not_valid_after(now + datetime.timedelta(days=1))
                    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                    .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                    .sign(key, hashes.SHA256()))
            cert_path, key_path = root / "cert.pem", root / "key.pem"
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert_path, key_path)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            manager = UpdateManager("https://127.0.0.1/latest.json", cache_dir=root / "cache")
            manager._nam.setProxy(QNetworkProxy(QNetworkProxy.NoProxy))
            url = f"https://127.0.0.1:{server.server_port}/setup.exe"
            manager._release = ReleaseInfo("9.0.0", "", url, hashlib.sha256(payload).hexdigest())
            original_request = manager._request

            def trusted_local_request(address):
                request = original_request(address)
                config = request.sslConfiguration()
                config.setCaCertificates(config.caCertificates() + [QSslCertificate(cert_path.read_bytes())])
                request.setSslConfiguration(config)
                return request

            manager._request = trusted_local_request
            done, failures = [], []
            manager.download_finished.connect(done.append)
            manager.download_failed.connect(failures.append)
            try:
                manager.download()
                deadline = time.monotonic() + 10
                while manager.busy and time.monotonic() < deadline:
                    self.app.processEvents()
                    time.sleep(.002)
                self.assertEqual(failures, [])
                self.assertEqual(len(done), 1)
                self.assertEqual(Path(done[0]).read_bytes(), payload)
                self.assertEqual(received_ranges, [None, f"bytes={prefix_size}-"])
            finally:
                manager.shutdown()
                manager.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                self.app.processEvents()
                server.shutdown()
                server.server_close()
                worker.join(timeout=2)
