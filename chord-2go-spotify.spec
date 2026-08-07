# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


root = Path(SPEC).resolve().parent
payload = root / "src" / "chord_2go_spotify" / "data" / "spotify-install.tar.gz"
if not payload.is_file():
    raise SystemExit(
        "Missing generated payload. Run scripts/build-payload.sh before PyInstaller."
    )

datas, binaries, hiddenimports = collect_all("bleak")
datas.append((str(payload), "chord_2go_spotify/data"))

analysis = Analysis(
    [str(root / "scripts" / "pyinstaller_entry.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="chord-2go-spotify",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
