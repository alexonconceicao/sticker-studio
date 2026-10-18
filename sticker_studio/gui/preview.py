"""Prévia animada de figurinha pronta (webp ou webm), sobre fundo xadrez."""
import threading
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

from sticker_studio.engine import media
from sticker_studio.gui.player import to_qimage
from sticker_studio.gui.viewer import checker_brush


def load_frames(path: Path, max_side=512):
    """Lista de (QImage, duração_ms)."""
    if media.is_webp(path):
        from PIL import Image, ImageSequence

        im = Image.open(path)
        out = []
        for fr in ImageSequence.Iterator(im):
            rgba = fr.convert("RGBA")
            rgba.thumbnail((max_side, max_side))
            data = rgba.tobytes()
            out.append((to_qimage(data, rgba.width, rgba.height), max(20, fr.info.get("duration") or 40)))
        return out
    info = media.probe(path)
    fps = min(30, info.fps or 30)
    return [(to_qimage(b, w, h, bpp), int(1000 / fps))
            for b, w, h, bpp in media.iter_segment(info, 0, info.duration + 1, fps, max_side)]


def first_frame(path: Path, max_side=128) -> QImage | None:
    try:
        if media.is_webp(path):
            from PIL import Image

            im = Image.open(path).convert("RGBA")
            im.thumbnail((max_side, max_side))
            return to_qimage(im.tobytes(), im.width, im.height)
        info = media.probe(path)
        r = media.frame_at(info, 0, max_side)
        return to_qimage(*r) if r else None
    except Exception:
        return None


class AnimatedPreview(QWidget):
    _loaded = Signal(int, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.frames = []
        self.idx = 0
        self._gen = 0
        self._checker = checker_brush(8)
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self._next)
        self._loaded.connect(self._on_loaded)

    def sizeHint(self):
        return QSize(180, 180)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return w

    def load(self, path: Path | None):
        self._gen += 1
        self.frames, self.idx = [], 0
        self.timer.stop()
        self.update()
        if not path:
            return
        gen = self._gen

        def work():
            try:
                frames = load_frames(path)
            except Exception:
                frames = []
            self._loaded.emit(gen, frames)

        threading.Thread(target=work, daemon=True).start()

    def _on_loaded(self, gen, frames):
        if gen != self._gen:
            return
        self.frames, self.idx = frames, 0
        self._next()

    def _next(self):
        if not self.frames:
            return
        self.update()
        _, ms = self.frames[self.idx]
        self.idx = (self.idx + 1) % len(self.frames)
        if len(self.frames) > 1:
            self.timer.start(ms)

    def paintEvent(self, _):
        p = QPainter(self)
        side = min(self.width(), self.height())
        box = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._checker)
        p.drawRoundedRect(box, 10, 10)
        if not self.frames:
            p.setPen(QColor("#666"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, "…")
            return
        img, _ = self.frames[(self.idx - 1) % len(self.frames)]
        s = min(side / img.width(), side / img.height())
        w, h = img.width() * s, img.height() * s
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h), img)
