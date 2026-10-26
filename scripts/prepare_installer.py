"""Generate NSIS install/uninstall inventory and version metadata; do not build binaries.

Run after PyInstaller: python scripts/prepare_installer.py
Then: makensis installer/setup.nsi
"""

import argparse
import ast
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Written next to MdNote.exe and consumed by the installer on upgrade to
# delete files no longer shipped. Without it, files from older layouts (e.g.
# Qt DLLs collected at _internal root by older hooks) linger across upgrades
# and can shadow newer binaries.
MANIFEST_NAME = "install-manifest.txt"

# Visual C++ runtime DLLs that must match the version Qt was built against.
# PyInstaller may collect older copies from the base Python interpreter while
# PySide6/Qt needs newer ones; a mixed set causes
# "ImportError: DLL load failed while importing QtGui: 找不到指定的程序"
# on machines without the matching system redistributable.
VC_RUNTIME_DLLS = (
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "concrt140.dll",
)


def sync_vc_runtime(dist: Path) -> list[str]:
    """Overwrite bundled VC runtimes with the versions shipped by PySide6."""
    try:
        import PySide6
    except ImportError:
        return []
    qt_dir = Path(PySide6.__file__).resolve().parent
    internal = dist / "_internal"
    replaced: list[str] = []
    for name in VC_RUNTIME_DLLS:
        source = qt_dir / name
        target = internal / name
        if not source.exists():
            continue
        if not target.exists() or source.stat().st_size != target.stat().st_size:
            shutil.copy2(source, target)
            replaced.append(f"{name} {_file_version(source)}")
    return replaced


def _file_version(path: Path) -> str:
    try:
        import ctypes
        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return ""
        block = ctypes.create_string_buffer(size)
        ctypes.windll.version.GetFileVersionInfoW(str(path), None, size, block)
        pointer = ctypes.c_void_p()
        length = ctypes.c_uint()
        ctypes.windll.version.VerQueryValueW(
            block, "\\", ctypes.byref(pointer), ctypes.byref(length))
        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint32) for n in
                        ("sig", "struc", "ms_hi", "ms_lo", "ls_hi", "ls_lo")]
        info = VS_FIXEDFILEINFO.from_address(pointer.value)
        return (f"{info.ms_hi >> 16}.{info.ms_hi & 0xffff}."
                f"{info.ms_lo >> 16}.{info.ms_lo & 0xffff}")
    except Exception:
        return ""


def read_app_version(source: Path = ROOT / "mdnote" / "__init__.py") -> str:
    tree = ast.parse(source.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if (isinstance(node, ast.Assign) and
                any(isinstance(target, ast.Name) and target.id == "__version__"
                    for target in node.targets)):
            version = ast.literal_eval(node.value)
            if isinstance(version, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", version):
                return version
    raise ValueError("mdnote.__version__ must be a numeric release version")


def _nsis_text(value: str) -> str:
    if any(ord(character) < 32 for character in value):
        raise ValueError("NSIS file paths cannot contain control characters")
    return value.replace("$", "$$").replace('"', '$\\"')


def _ordered_dirs(files: list[Path]) -> list[Path]:
    """All parent directories, deepest first (safe order for RMDir)."""
    directories = {parent for relative in files for parent in relative.parents
                   if parent != Path(".")}
    return sorted(directories, key=lambda item: (len(item.parts), str(item)),
                  reverse=True)


def _build_path_text(relative: Path) -> str:
    text = relative.as_posix().replace("/", "\\")
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:  # NSIS reads the manifest as ANSI
        raise ValueError(f"Installed paths must be ASCII: {relative}") from exc
    return text


def write_install_manifest(dist: Path, files: list[Path]) -> None:
    """Write F/D lines the NSIS installer uses to remove the old release."""
    lines = [f"F{_build_path_text(relative)}" for relative in files]
    lines.extend(f"D{_build_path_text(directory)}"
                 for directory in _ordered_dirs(files))
    (dist / MANIFEST_NAME).write_text("\r\n".join(lines) + "\r\n", encoding="ascii")


def build_inventory(dist: Path, version: str) -> str:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", version):
        raise ValueError("Invalid release version")
    dist = dist.resolve(strict=True)
    files = []
    for item in sorted(dist.rglob("*")):
        if item.is_symlink() or not item.resolve().is_relative_to(dist):
            raise ValueError(f"Linked build entries are not supported: {item}")
        if item.is_file():
            files.append(item.relative_to(dist))
    if Path("MdNote.exe") not in files:
        raise ValueError("Build directory must contain MdNote.exe")
    # The manifest is installed (and removed) like any other file, but its own
    # content describes the remaining files; regenerate it first.
    write_install_manifest(dist, files)
    files = sorted(files + [Path(MANIFEST_NAME)])
    directories = _ordered_dirs(files)
    product_version = version + ".0" * (4 - len(version.split(".")))
    lines = ["; Generated by scripts/prepare_installer.py; do not edit.",
             f'!define APP_VERSION "{version}"',
             f'!define APP_PRODUCT_VERSION "{product_version}"',
             "", "!macro MDNOTE_INSTALL_FILES"]
    current_directory = None
    for relative in files:
        directory = relative.parent.as_posix()
        if directory != current_directory:
            destination = "$INSTDIR" + ("\\" + _nsis_text(directory.replace("/", "\\"))
                                        if directory != "." else "")
            lines.append(f'  SetOutPath "{destination}"')
            current_directory = directory
        source = _nsis_text(str(dist / relative))
        lines.append(f'  File "{source}"')
    lines.extend(["!macroend", "", "!macro MDNOTE_REMOVE_INSTALLED_FILES"])
    for relative in files:
        destination = _nsis_text(relative.as_posix().replace("/", "\\"))
        lines.append(f'  Delete "$INSTDIR\\{destination}"')
    for directory in directories:
        destination = _nsis_text(directory.as_posix().replace("/", "\\"))
        # Non-recursive removal leaves user-created files, and their parent directories, intact.
        lines.append(f'  RMDir "$INSTDIR\\{destination}"')
    lines.extend(["!macroend", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "MdNote")
    parser.add_argument("--out", type=Path, default=ROOT / "installer" / "generated-files.nsh")
    args = parser.parse_args()
    replaced = sync_vc_runtime(args.dist)
    for item in replaced:
        print(f"VC runtime synced: {item}")
    contents = build_inventory(args.dist, read_app_version())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(contents, encoding="utf-8-sig")
    print(f"NSIS inventory written: {args.out}")


if __name__ == "__main__":
    main()
