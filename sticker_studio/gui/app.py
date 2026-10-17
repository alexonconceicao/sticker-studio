"""Inicialização do aplicativo: tema escuro e verificação do ffmpeg."""
import shutil
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from sticker_studio import APP_ID, APP_NAME
from sticker_studio.engine import ffmpeg
from sticker_studio.paths import resource

QSS = """
QWidget { font-size: 13px; }
#header { background: #13161c; border-bottom: 1px solid #262b36; }
#side { background: #171a21; border-left: 1px solid #262b36; }
#muted { color: #8a92a3; }
#cap { color: #8a92a3; font-size: 11px; letter-spacing: 1px; margin-top: 4px; }
#warn { color: #f59e0b; }
QPushButton { background: #222734; border: 1px solid #2f3544; border-radius: 8px; padding: 6px 12px; color: #e7e9ee; }
QPushButton:hover { background: #2a3040; border-color: #3a4152; }
QPushButton:disabled { color: #59606e; background: #1b1f28; }
QPushButton:checked { background: #7c5cff; border-color: #7c5cff; color: white; }
QPushButton#primary { background: #7c5cff; border-color: #7c5cff; color: white; font-weight: 600; font-size: 14px; }
QPushButton#primary:hover { background: #6b48ff; }
QPushButton#primary:disabled { background: #3b3360; color: #9a93b8; }
#seg { background: #11141a; border: 1px solid #262b36; border-radius: 9px; }
QPushButton#segbtn { background: transparent; border: none; border-radius: 6px; padding: 6px 4px; }
QPushButton#segbtn:checked { background: #2b3142; color: white; }
QPushButton#segbtn:hover:!checked { background: #1d2230; }
QPlainTextEdit, QSpinBox, QComboBox, QFontComboBox { background: #11141a; border: 1px solid #2f3544; border-radius: 8px; padding: 4px 6px; color: #e7e9ee; }
QListWidget { background: #11141a; border: 1px solid #262b36; border-radius: 8px; }
QProgressBar { background: #11141a; border: none; border-radius: 3px; }
QProgressBar::chunk { background: #7c5cff; border-radius: 3px; }
QCheckBox::indicator { width: 16px; height: 16px; }
"""


def dark_palette() -> QPalette:
    pal = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#0f1115"), (QPalette.ColorRole.WindowText, "#e7e9ee"),
        (QPalette.ColorRole.Base, "#11141a"), (QPalette.ColorRole.AlternateBase, "#171a21"),
        (QPalette.ColorRole.Text, "#e7e9ee"), (QPalette.ColorRole.Button, "#222734"),
        (QPalette.ColorRole.ButtonText, "#e7e9ee"), (QPalette.ColorRole.Highlight, "#7c5cff"),
        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, "#222734"),
        (QPalette.ColorRole.ToolTipText, "#e7e9ee"), (QPalette.ColorRole.PlaceholderText, "#6b7280"),
    ):
        pal.setColor(role, QColor(color))
    return pal


def selftest() -> int:
    """Gera uma figurinha de teste de cada tipo (usado no CI e pra conferir o pacote)."""
    import tempfile

    from sticker_studio.engine import media
    from sticker_studio.engine.render import RenderParams, render
    from sticker_studio.gui.textlayer import TextLayer, render_png

    tmp = Path(tempfile.mkdtemp(prefix="sticker-selftest-"))
    src = tmp / "src.mp4"
    ffmpeg.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=2",
                "-pix_fmt", "yuv420p", str(src)])
    info = media.probe(src)
    overlay = render_png([TextLayer(text="TESTE")], 1024, 1024)
    for target in ("whatsapp", "telegram"):
        r = render(RenderParams(media=info, target=target, start=0, end=1.5, crop=(140, 0, 360, 360),
                                overlay_png=overlay, out_dir=tmp), tmp / "work")
        print(f"{target}: {r.path.name} {r.bytes} bytes {r.width}x{r.height} {r.quality}")
    edited = media.open_media(r.path, tmp / "imports")
    print(f"import: {edited.width}x{edited.height} alpha={edited.alpha}")
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


def main():
    if "--selftest" in sys.argv:
        QApplication.setApplicationName(APP_NAME)
        from PySide6.QtGui import QGuiApplication

        _app = QGuiApplication(sys.argv)  # noqa: F841  (fontes pro texto)
        sys.exit(selftest())
    QApplication.setApplicationName(APP_NAME)
    QApplication.setOrganizationName(APP_ID)
    QApplication.setDesktopFileName("sticker-studio")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    app.setStyleSheet(QSS)
    app.setWindowIcon(QIcon(str(resource("icon.svg"))))

    from sticker_studio.gui.main_window import MainWindow, fatal

    try:
        ffmpeg.find("ffmpeg")
        ffmpeg.find("ffprobe")
    except ffmpeg.FFmpegError as e:
        fatal(str(e))

    win = MainWindow()
    win.show()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args and Path(args[0]).exists():
        win.open_path(Path(args[0]))
    sys.exit(app.exec())
