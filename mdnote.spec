# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置。用法：pyinstaller mdnote.spec

block_cipher = None

a = Analysis(
    ["launch.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("mdnote/editor/web", "mdnote/editor/web"),
        ("mdnote/resources", "mdnote/resources"),
    ],
    hiddenimports=[
        "PySide6.QtNetwork",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "numpy",
        "PIL",
        "tkinter",
        "unittest",
        "pydoc_data",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MdNote",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 窗口应用，无控制台
    icon="mdnote/resources/icon.ico",
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MdNote",
)
