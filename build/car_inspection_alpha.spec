# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\ui_app.py'],
    pathex=[],
    binaries=[],
    datas=[('C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\build\\reference_cars_alpha', 'reference_cars'), ('C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\icon.ico', '.'), ('C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\README.md', '.'), ('C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\PACKAGING_ALPHA.md', 'docs'), ('C:\\Users\\alexa\\Documents\\bot development\\eF Bot v2.1\\car_inspection\\build\\..\\build\\alpha_release_notes.txt', 'docs')],
    hiddenimports=[],
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
    name='eF Drift Car Scrutineer Alpha',
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
