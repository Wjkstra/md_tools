"""Regression for packaging: bundled VC runtimes must match Qt's build.

PyInstaller can collect an older vcruntime140.dll from the base Python while
PySide6/Qt needs a newer one; the mismatch aborts startup with
"DLL load failed while importing QtGui: 找不到指定的程序" on machines lacking
the newer system redistributable.
"""
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from scripts.prepare_installer import (
    MANIFEST_NAME,
    build_inventory,
    sync_vc_runtime,
    VC_RUNTIME_DLLS,
)


@unittest.skipUnless(
    __import__("importlib.util").util.find_spec("PySide6"),
    "PySide6 required to verify runtime packaging",
)
class VcRuntimeSyncTests(unittest.TestCase):
    def test_older_runtime_is_replaced_by_pyside6_version(self):
        import tempfile
        import PySide6

        qt_dir = Path(PySide6.__file__).resolve().parent
        source = qt_dir / "vcruntime140.dll"
        if not source.exists():
            self.skipTest("PySide6 does not ship vcruntime140.dll")

        with tempfile.TemporaryDirectory() as tmp:
            internal = Path(tmp) / "_internal"
            internal.mkdir()
            stale = internal / "vcruntime140.dll"
            stale.write_bytes(b"stale-old-runtime-build")  # wrong size/version
            replaced = sync_vc_runtime(Path(tmp))
            self.assertTrue(any("vcruntime140" in item for item in replaced))
            self.assertEqual(stale.read_bytes(), source.read_bytes())

    def test_idempotent_when_versions_match(self):
        import tempfile
        import PySide6

        qt_dir = Path(PySide6.__file__).resolve().parent
        source = qt_dir / "vcruntime140_1.dll"
        if not source.exists():
            self.skipTest("PySide6 does not ship vcruntime140_1.dll")

        with tempfile.TemporaryDirectory() as tmp:
            internal = Path(tmp) / "_internal"
            internal.mkdir()
            (internal / "vcruntime140_1.dll").write_bytes(source.read_bytes())
            # Same bytes -> nothing to replace on the second run.
            first = sync_vc_runtime(Path(tmp))
            second = sync_vc_runtime(Path(tmp))
            self.assertFalse(any("vcruntime140_1" in item for item in second))


class InstallManifestTests(unittest.TestCase):
    def _make_dist(self, root: Path) -> None:
        root.mkdir(parents=True)
        (root / "MdNote.exe").write_bytes(b"exe")
        pkg = root / "_internal" / "PySide6"
        pkg.mkdir(parents=True)
        (pkg / "Qt6Core.dll").write_bytes(b"qt")

    def test_manifest_lists_files_then_dirs_deepest_first(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "MdNote"
            self._make_dist(dist)
            build_inventory(dist, "1.2.3")

            with (dist / MANIFEST_NAME).open(
                    encoding="ascii", newline="") as handle:
                text = handle.read()
            self.assertTrue(text.endswith("\r\n"))
            lines = text.splitlines()
            self.assertIn("FMdNote.exe", lines)
            self.assertIn(r"F_internal\PySide6\Qt6Core.dll", lines)
            # The manifest documents other files, never itself.
            self.assertNotIn(f"F{MANIFEST_NAME}", lines)
            dirs = [line for line in lines if line.startswith("D")]
            self.assertEqual(dirs, [r"D_internal\PySide6", r"D_internal"])

    def test_manifest_is_installed_and_uninstalled(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp) / "MdNote"
            self._make_dist(dist)
            nsh = build_inventory(dist, "1.2.3")

            self.assertIn(f'File "{dist / MANIFEST_NAME}"', nsh)
            self.assertIn(
                f'Delete "$INSTDIR\\{MANIFEST_NAME}"', nsh)


if __name__ == "__main__":
    unittest.main()
