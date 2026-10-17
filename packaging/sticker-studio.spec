# PyInstaller: gera o app em pasta (onedir) ou arquivo único (ONEFILE=1).
# ffmpeg é procurado em ./ffmpeg-bin (copiado pra dentro do pacote como bin/).
import os
from pathlib import Path

root = Path(SPECPATH).parent
onefile = os.environ.get("ONEFILE") == "1"
ffbin = root / "ffmpeg-bin"
binaries = [(str(f), "bin") for f in ffbin.iterdir()] if ffbin.is_dir() else []
icon = root / "build" / ("icon.ico" if os.name == "nt" else "icon.png")

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=[(str(root / "sticker_studio" / "icon.svg"), "sticker_studio")],
    hiddenimports=["PySide6.QtSvg"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtBluetooth", "matplotlib", "scipy"],
)
pyz = PYZ(a.pure)
common = dict(name="StickerStudio", console=False, icon=str(icon) if icon.exists() else None, upx=False)
if onefile:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, name="StickerStudio", upx=False)
