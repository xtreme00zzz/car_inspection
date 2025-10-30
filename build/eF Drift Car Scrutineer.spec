# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\ui_app.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\reference_cars', 'reference_cars'), ('C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\icon.ico', '.'), ('C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\README.md', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='eF Drift Car Scrutineer',
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
    icon=['C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\icon.ico'],
)
