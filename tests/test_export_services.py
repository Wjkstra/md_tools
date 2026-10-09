"""Export completion, standalone resources and image-save transaction regressions."""
import base64
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
from PySide6.QtCore import QCoreApplication, QEvent, QProcess, QTimer
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from mdnote.services import exporter
from mdnote.services.html_service import safe_html
from mdnote.services.image_service import import_image, prepare_images_for_save


class ExportServicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait(self, condition, seconds=12):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(.005)
        self.fail("Export job did not complete")

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def png(self, path):
        image = QImage(12, 12, QImage.Format_ARGB32)
        image.fill(QColor("#ce231d"))
        self.assertTrue(image.save(str(path), "PNG"))

    def test_standalone_sanitizes_authored_html_and_embeds_local_image(self):
        with tempfile.TemporaryDirectory() as folder:
            self.png(Path(folder) / "picture.png")
            text = '# <img src="bad" onerror="evil()">\n\n![](picture.png)\n<script>alert(1)</script>\n<a href="javascript:evil()">bad</a>'
            html = exporter.build_standalone_html(text, include_toc=True, doc_base=folder)
            self.assertIsNone(re.search(r'<img[^>]*\bonerror\s*=', html))
            self.assertNotIn('javascript:evil()', html)
            self.assertNotIn('<script>alert(1)', html)
            self.assertIn('data:image/png;base64,', html)
            self.assertIn('&lt;img', html)
            self.assertIn('Content-Security-Policy', html)
            self.assertIn('data-toc-id="target"', safe_html('<nav><a data-toc-id="target">目录</a></nav>'))

    def test_shared_image_folder_and_untrusted_filename_work_without_orphans(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder) / "notes"
            base.mkdir()
            reference = import_image(data_url=base64.b64encode(b"png-content").decode(),
                                     file_name="../../picture.png", doc_path=str(base / "note.md"),
                                     folder="../shared")
            self.assertEqual(reference, '![](<../shared/picture.png>)')
            self.assertEqual((Path(folder) / "shared" / "picture.png").read_bytes(), b"png-content")
            before = list((Path(folder) / "shared").iterdir())
            with self.assertRaises(ValueError):
                import_image(data_url="not valid base64!", doc_path=str(base / "note.md"), folder="../shared")
            self.assertEqual(list((Path(folder) / "shared").iterdir()), before)

    def test_image_save_collision_and_rollback_preserve_existing_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "draft", Path(folder) / "destination"
            old.mkdir(); (new / "assets").mkdir(parents=True)
            (old / "picture.png").write_bytes(b"draft")
            existing = new / "assets" / "picture.png"
            existing.write_bytes(b"existing")
            text = '![](picture.png)\n\n![same][image]\n\n[image]: picture.png\n\n<img src="picture.png">'
            prepared = prepare_images_for_save(text, str(old), str(new / "note.md"))
            self.assertEqual(len(prepared.created_paths), 1)
            copied = prepared.created_paths[0]
            self.assertEqual(copied.name, "picture-1.png")
            self.assertEqual(prepared.text.count('assets/picture-1.png'), 3)
            self.assertEqual(existing.read_bytes(), b"existing")
            prepared.rollback()
            self.assertFalse(copied.exists())
            self.assertEqual((old / "picture.png").read_bytes(), b"draft")
            self.assertEqual(existing.read_bytes(), b"existing")

    def test_image_save_commit_and_code_examples(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / "old", Path(folder) / "new"
            old.mkdir(); new.mkdir()
            (old / "image.png").write_bytes(b"image")
            ticks = chr(96)
            code = ticks * 3 + '\n![](image.png)\n' + ticks * 3 + '\n' + ticks + '![](image.png)' + ticks
            prepared = prepare_images_for_save('![](image.png)\n\n' + code, str(old), str(new / "note.md"))
            self.assertIn('![](assets/image.png)', prepared.text)
            self.assertIn(code, prepared.text)
            copied = prepared.created_paths[0]
            prepared.commit(); prepared.rollback()
            self.assertTrue(copied.exists())

    def test_pdf_completion_writes_full_document_and_cleans_temporary_page(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "full.pdf"
            text = '\n\n'.join('Paragraph %d, complete document export.' % i for i in range(150))
            job = exporter.export_pdf(text, str(target), timeout_ms=15000)
            results = []
            job.finished.connect(lambda *args: results.append(args))
            self.assertEqual(results, [])
            self.wait(lambda: bool(results), seconds=18)
            self.assertEqual(results, [(True, str(target))])
            content = target.read_bytes()
            self.assertTrue(content.startswith(b'%PDF'))
            self.assertGreater(len(re.findall(rb'/Type\s*/Page\b', content)), 1)
            self.assertIsNone(job._temporary)
            job.deleteLater()

    def test_image_export_waits_for_embedded_math_and_diagram(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "result.png"
            self.png(Path(folder) / "picture.png")
            text = '![](picture.png)\n\n$x^2$\n\n<pre><code class="language-mermaid">graph TD; A--&gt;B</code></pre>'
            html = exporter.build_standalone_html(text, doc_base=folder)
            self.assertNotIn('url(fonts/', html)
            observed = []
            original_height = exporter.RenderExportJob._on_height
            def inspect_render(job, height):
                job._view.page().runJavaScript(
                    "JSON.stringify({math:document.querySelectorAll('.katex').length,diagrams:document.querySelectorAll('.mermaid svg').length,image:document.images[0].naturalWidth})",
                    observed.append)
                original_height(job, height)
            with patch.object(exporter.RenderExportJob, '_on_height', inspect_render):
                job = exporter.export_image(html, str(target), timeout_ms=20000)
                results = []
                job.finished.connect(lambda *args: results.append(args))
                self.wait(lambda: bool(results), seconds=23)
            self.assertTrue(observed)
            import json
            self.assertEqual(json.loads(observed[0]), {'math': 1, 'diagrams': 1, 'image': 12})
            self.assertEqual(results, [(True, str(target))])
            image = QImage(str(target))
            self.assertFalse(image.isNull())
            self.assertIsNone(job._temporary)
            job.deleteLater()

    def test_capture_page_blocks_link_navigation_away_from_local_document(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "result.png"
            html = '<html><body><a id="go" href="https://evil.invalid/leave">go</a></body></html>'
            # No authored state script in this raw page, so the job stays pending
            # until we cancel it after the assertion.
            job = exporter.export_image(html, str(target), timeout_ms=60000)
            try:
                self.wait(lambda: job._view is not None)
                def eval_js(expr):
                    values = []
                    job._view.page().runJavaScript(expr, values.append)
                    deadline = time.monotonic() + 5
                    while not values and time.monotonic() < deadline:
                        self.app.processEvents(); time.sleep(.005)
                    return values[0] if values else None
                self.wait(lambda: eval_js("document.readyState") == "complete", seconds=8)
                eval_js("document.getElementById('go').click()")
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    self.app.processEvents(); time.sleep(.005)
                location = eval_js("location.href")
                self.assertTrue(location.startswith("file:"), location)
                self.assertNotIn("evil.invalid", location)
            finally:
                job.cancel()
                job.deleteLater()

    def test_media_deadline_and_cancel_complete_once(self):
        with tempfile.TemporaryDirectory() as folder:
            job = exporter.export_image('<html><body>never ready</body></html>', str(Path(folder) / 'none.png'), timeout_ms=120)
            results = []
            job.finished.connect(lambda *args: results.append(args))
            self.wait(lambda: bool(results))
            self.assertFalse(results[0][0])
            self.assertIn('超时', results[0][1])
            self.assertIsNone(job._temporary)
            job.cancel()
            self.assertEqual(len(results), 1)
            job.deleteLater()

    def test_pandoc_is_asynchronous_and_uses_selected_target_and_resource_base(self):
        class FakePandoc(QProcess):
            calls = []
            def start(self, executable, arguments):
                self.calls.append((executable, arguments, self.workingDirectory()))
                self.target = Path(arguments[arguments.index('-o') + 1])
                self.started.emit()
            def write(self, data):
                self.input = bytes(data)
                return len(data)
            def closeWriteChannel(self):
                self.target.write_bytes(self.input)
                QTimer.singleShot(0, lambda: self.finished.emit(0, QProcess.NormalExit))
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'selected.docx'
            with patch.object(exporter, 'QProcess', FakePandoc), patch.object(exporter.shutil, 'which', return_value='/fake/pandoc'):
                job = exporter.pandoc_export('文档', 'docx', str(target), doc_base=folder)
                results = []
                job.finished.connect(lambda *args: results.append(args))
                self.assertEqual(results, [])
                self.wait(lambda: bool(results))
                self.assertEqual(results, [(True, str(target))])
                self.assertEqual(target.read_text(encoding='utf-8'), '文档')
                call = FakePandoc.calls[0]
                staged = Path(call[1][call[1].index('-o') + 1])
                self.assertEqual(staged.parent, target.resolve().parent)
                self.assertEqual(staged.suffix, '.docx')
                self.assertFalse(staged.exists())
                self.assertEqual(call[1][call[1].index('--resource-path') + 1], str(Path(folder).resolve()))
                self.assertEqual(call[2], str(Path(folder).resolve()))
                job.deleteLater()

    def test_failed_atomic_output_preserves_previous_export(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'previous.pdf'
            target.write_bytes(b'previous-content')
            with patch.object(exporter.os, 'replace', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    exporter._atomic_output(str(target), lambda path: path.write_bytes(b'new-content'))
            self.assertEqual(target.read_bytes(), b'previous-content')
            self.assertEqual(list(Path(folder).iterdir()), [target])

    def test_missing_image_fails_instead_of_exporting_blank_media(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'none.pdf'
            job = exporter.export_pdf('![](missing.png)', str(target), doc_base=folder)
            results = []
            job.finished.connect(lambda *args: results.append(args))
            self.wait(lambda: bool(results))
            self.assertFalse(results[0][0])
            self.assertIn('资源加载失败', results[0][1])
            self.assertFalse(target.exists())
            self.assertIsNone(job._temporary)
            job.deleteLater()


if __name__ == '__main__':
    unittest.main()
