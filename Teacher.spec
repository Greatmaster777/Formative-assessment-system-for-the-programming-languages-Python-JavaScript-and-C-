# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all

openpyxl_datas, openpyxl_binaries, openpyxl_hiddenimports = collect_all('openpyxl')

a = Analysis(
    ['teacher.py'],
    pathex=[],
    binaries=openpyxl_binaries,
    datas=openpyxl_datas,
    hiddenimports=openpyxl_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Teacher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
