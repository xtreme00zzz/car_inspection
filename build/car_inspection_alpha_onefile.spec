# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

project_root = Path.cwd()
datas = []
script_path = project_root / 'ui_app.py'


def add_data(rel_path: str, target: str) -> None:
    src = project_root / rel_path
    if not src.exists():
        return
    datas.append((str(src), target))


add_data('reference_cars', 'reference_cars')
add_data('icon.ico', '.')
add_data('README.md', '.')
add_data('PACKAGING_ALPHA.md', 'docs')
add_data('build/alpha_release_notes.txt', 'docs')

binaries = []
hiddenimports = [
    'PIL._imaging',
    'PIL._imagingtk',
    'PIL._tkinter_finder',
]

a = Analysis(
    [str(script_path)],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='car_inspection_alpha',
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
    icon=str(project_root / 'icon.ico'),
)
