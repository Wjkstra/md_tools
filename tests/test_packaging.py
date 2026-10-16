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

from scripts.prepare_installer import sync_vc_runtime, VC_RUNTIME_DLLS


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


if __name__ == "__main__":
    unittest.main()
