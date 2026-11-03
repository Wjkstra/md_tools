"""Execute only installer directory selection in a non-elevated NSIS fixture.

The production .onInit body is reused; registry reads are redirected to unique
HKCU test keys and all installation / process-guard calls are removed. No real
application, uninstall key, or installation directory is modified.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL_NSIS = ROOT / ".tools" / "nsis-3.10" / "makensis.exe"
COMPILER = str(LOCAL_NSIS) if LOCAL_NSIS.is_file() else shutil.which("makensis")


@unittest.skipUnless(os.name == "nt" and COMPILER, "Windows and NSIS required")
class InstallerDirectoryIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import winreg
        cls.winreg = winreg
        cls.temp = tempfile.TemporaryDirectory(prefix="mdnote-directory-test-")
        cls.base = Path(cls.temp.name)
        cls.key = "Software\\MdNoteDirectoryTest-" + uuid.uuid4().hex
        source = (ROOT / "installer" / "setup.nsi").read_text(encoding="utf-8-sig")
        body = re.search(r"(?ms)^Function \.onInit\s*\n(.*?)^FunctionEnd", source).group(1)
        body = body.replace("  Call EnsureMdNoteClosed", "").replace("  Call ValidateInstallDir", "")
        names = iter(["machine64", "machine32", "user32", "user64"])
        body = re.sub(r'ReadRegStr \$R1 HK(?:LM|CU) "[^"]+" "InstallLocation"',
                      lambda _: 'ReadRegStr $R1 HKCU "' + cls.key + "\\" + next(names) + '" "InstallLocation"', body)
        cls.result = cls.base / "selected.txt"
        cls.executable = cls.base / "select.exe"
        header = ('Unicode True\n!include "FileFunc.nsh"\nName "Directory test"\n'
                  f'OutFile "{cls.executable}"\nInstallDir "$PROGRAMFILES64\\MdNote"\n'
                  'RequestExecutionLevel user\nSilentInstall silent\n')
        script = header + 'Function .onInit\n' + body + (
            f'\nFileOpen $R9 "{cls.result}" w\nFileWriteUTF16LE $R9 "$INSTDIR"\n'
            'FileClose $R9\nSetErrorLevel 0\nQuit\nFunctionEnd\nSection\nSectionEnd\n')
        target = cls.base / "select.nsi"
        target.write_text(script, encoding="utf-8-sig")
        compiled = subprocess.run([COMPILER, str(target)], capture_output=True, text=True)
        if compiled.returncode:
            cls.temp.cleanup()
            raise AssertionError(compiled.stdout + compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.remove_keys()
        cls.temp.cleanup()

    @classmethod
    def remove_keys(cls):
        for name in ["machine64", "machine32", "user32", "user64", ""]:
            try:
                cls.winreg.DeleteKey(cls.winreg.HKEY_CURRENT_USER, cls.key + ("\\" + name if name else ""))
            except FileNotFoundError:
                pass

    def setUp(self):
        self.remove_keys()

    def registered(self, name, directory):
        with self.winreg.CreateKey(self.winreg.HKEY_CURRENT_USER, self.key + "\\" + name) as key:
            self.winreg.SetValueEx(key, "InstallLocation", 0, self.winreg.REG_SZ, str(directory))

    def app_directory(self, name):
        directory = self.base / name
        directory.mkdir(exist_ok=True)
        (directory / "MdNote.exe").write_bytes(b"test fixture, not executable")
        return directory

    def selected(self, destination=None):
        command = f'"{self.executable}" /S'
        if destination is not None:
            command += " /D=" + str(destination)
        subprocess.run(command, check=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        return self.result.read_text(encoding="utf-16-le").lstrip("\ufeff")

    def test_previous_directory_and_legacy_registry_fallback(self):
        for name in ["machine64", "machine32", "user32", "user64"]:
            with self.subTest(registry=name):
                self.remove_keys()
                existing = self.app_directory("已有 中文 " + name)
                self.registered(name, existing)
                self.assertEqual(self.selected(), str(existing))

    def test_explicit_unicode_directory_overrides_registered_directory(self):
        existing = self.app_directory("registered")
        self.registered("machine64", existing)
        target = self.base / "指定 中文 路径"
        self.assertEqual(self.selected(target), str(target))

    def test_explicit_default_still_wins_and_stale_registry_is_ignored(self):
        self.registered("machine64", self.app_directory("registered"))
        default = Path(os.environ.get("ProgramW6432", os.environ["ProgramFiles"])) / "MdNote"
        self.assertEqual(self.selected(default), str(default))
        self.remove_keys()
        self.registered("machine64", self.base / "no longer installed")
        fallback = self.app_directory("legacy")
        self.registered("machine32", fallback)
        self.assertEqual(self.selected(), str(fallback))


@unittest.skipUnless(os.name == "nt" and COMPILER, "Windows and NSIS required")
class InstallerCleanupIntegrationTests(unittest.TestCase):
    def test_upgrade_removes_old_icu_and_preserves_unowned_files(self):
        self.check_upgrade(b"F_internal\\icuuc.dll\r\nF_internal\\icudt78.dll\r\nD_internal\r\n")

    def test_upgrade_cleans_real_legacy_double_carriage_returns(self):
        self.check_upgrade(b"F_internal\\icuuc.dll\r\r\nF_internal\\icudt78.dll\r\r\nD_internal\r\r\n")

    def test_upgrade_cleans_orphans_after_previous_failed_upgrade(self):
        self.check_upgrade(b"FMdNote.exe\r\r\n")

    def test_upgrade_with_actual_published_manifests_when_available(self):
        manifests = [
            ROOT / ".audit-tool/ime-release/dist/MdNote/install-manifest.txt",
            ROOT / ".audit-tool/icu-fix/extracted/install-manifest.txt",
        ]
        if not all(path.is_file() for path in manifests):
            self.skipTest("Published build inventories unavailable")
        for manifest in manifests:
            with self.subTest(manifest=manifest):
                self.check_upgrade(manifest.read_bytes())

    def check_upgrade(self, manifest):
        with tempfile.TemporaryDirectory(prefix="mdnote-icu-upgrade-") as folder:
            base = Path(folder)
            install = base / "installed"
            internal = install / "_internal"
            internal.mkdir(parents=True)
            for name in ("icuuc.dll", "icudt78.dll"):
                (internal / name).write_bytes(b"old incompatible DLL")
            previous_backup = internal / "icuuc.dll.mdnote-disabled-0"
            previous_backup.write_bytes(b"existing backup")
            keep = install / "user-note.md"
            keep.write_text("preserve", encoding="utf-8")
            (install / "install-manifest.txt").write_bytes(manifest)
            source = (ROOT / "installer" / "setup.nsi").read_text(encoding="utf-8-sig")
            cleanup = re.search(r"(?ms)^Function CleanObsoleteFiles\s*\n.*?^FunctionEnd", source).group(0)
            executable = base / "cleanup.exe"
            script = ('Unicode True\nName "Cleanup test"\n'
                      f'OutFile "{executable}"\nRequestExecutionLevel user\nSilentInstall silent\n'
                      + cleanup + '\nSection\n'
                      + f'  StrCpy $INSTDIR "{install}"\n'
                      + '  Call CleanObsoleteFiles\nSectionEnd\n')
            target = base / "cleanup.nsi"
            target.write_text(script, encoding="utf-8-sig")
            subprocess.run([COMPILER, str(target)], check=True, capture_output=True)
            subprocess.run([str(executable), "/S"], check=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertFalse((internal / "icuuc.dll").exists())
            self.assertFalse((internal / "icudt78.dll").exists())
            self.assertEqual(keep.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(previous_backup.read_bytes(), b"existing backup")
            if b"F_internal\\icuuc.dll" not in manifest:
                self.assertEqual((internal / "icuuc.dll.mdnote-disabled-1").read_bytes(),
                                 b"old incompatible DLL")
                self.assertEqual((internal / "icudt78.dll.mdnote-disabled-0").read_bytes(),
                                 b"old incompatible DLL")

    def test_uninstall_removes_quarantined_files_but_keeps_user_files(self):
        with tempfile.TemporaryDirectory(prefix="mdnote-uninstall-test-") as folder:
            base = Path(folder)
            install = base / "installed"
            internal = install / "_internal"
            internal.mkdir(parents=True)
            for name in ("icuuc.dll.mdnote-disabled-0", "icuuc.dll.mdnote-disabled-1",
                         "icudt78.dll.mdnote-disabled-0"):
                (internal / name).write_bytes(b"quarantined DLL")
            keep = install / "user-note.md"
            keep.write_text("preserve", encoding="utf-8")
            source = (ROOT / "installer" / "setup.nsi").read_text(encoding="utf-8-sig")
            block = re.search(
                r"(?ms)^\s*; mdnote-quarantine-cleanup-begin\s*\n(.*?)"
                r"^\s*; mdnote-quarantine-cleanup-end",
                source).group(1)
            executable = base / "uninstall-tail.exe"
            script = ('Unicode True\nName "Uninstall tail test"\n'
                      f'OutFile "{executable}"\nRequestExecutionLevel user\n'
                      'SilentInstall silent\nSection\n'
                      f'  StrCpy $INSTDIR "{install}"\n'
                      + block + 'SectionEnd\n')
            target = base / "uninstall-tail.nsi"
            target.write_text(script, encoding="utf-8-sig")
            subprocess.run([COMPILER, str(target)], check=True, capture_output=True)
            subprocess.run([str(executable), "/S"], check=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual([p.name for p in install.iterdir()], ["user-note.md"])
            self.assertEqual(keep.read_text(encoding="utf-8"), "preserve")
