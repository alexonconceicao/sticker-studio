"""Gera build/icon.png e build/icon.ico a partir do icon.svg."""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

root = Path(__file__).resolve().parent.parent
out = root / "build"
out.mkdir(exist_ok=True)
app = QGuiApplication(sys.argv)
r = QSvgRenderer(str(root / "sticker_studio" / "icon.svg"))
img = QImage(256, 256, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img)
r.render(p)
p.end()
img.save(str(out / "icon.png"))

from PIL import Image  # noqa: E402

Image.open(out / "icon.png").save(out / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icons ok")
