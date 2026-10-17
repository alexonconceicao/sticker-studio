"""Motor de prévia: decodifica o trecho com ffmpeg e toca em loop dentro da janela."""
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage

from sticker_studio.engine import media

MAX_CACHE_FRAMES = 600
PREVIEW_SIDE = 480
SCRUB_SIDE = 720


def to_qimage(buf, w, h) -> QImage:
    return QImage(buf, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()


class Player(QObject):
    frameReady = Signal(QImage)
    timeChanged = Signal(float)
    playingChanged = Signal(bool)
    _segFrame = Signal(int, int, QImage)  # geração, índice, frame
    _segDone = Signal(int)
    _scrubFrame = Signal(int, QImage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.info = None
        self.start = self.end = self.pos = 0.0
        self.speed = 1.0
        self.boomerang = False
        self.playing = False
        self.cache: list[QImage] = []
        self.cache_key = None
        self.cache_complete = False
        self.fps = 30.0
        self._gen = 0
        self._scrub_gen = 0
        self._idx = 0
        self._dir = 1
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self._segFrame.connect(self._on_seg_frame)
        self._segDone.connect(self._on_seg_done)
        self._scrubFrame.connect(self._on_scrub_frame)
        self._reload = QTimer(self, singleShot=True, interval=250)
        self._reload.timeout.connect(self._load_segment)

    # ---------------------------------------------------------------- estado
    def set_media(self, info):
        self.pause()
        self.info = info
        self.fps = min(30.0, info.fps or 30.0)
        self.cache, self.cache_key, self.cache_complete = [], None, False
        self.start, self.end, self.pos = 0.0, info.duration, 0.0
        self.seek(0.0)

    def set_range(self, start, end):
        self.start, self.end = start, end
        if (start, end) != self.cache_key:
            self._reload.start()
        if not (start <= self.pos <= end):
            self.seek(start)

    def set_speed(self, s):
        self.speed = s
        self._restart_timer()

    def set_boomerang(self, b):
        self.boomerang = b
        self._dir = 1

    # ---------------------------------------------------------------- controle
    def toggle(self):
        self.pause() if self.playing else self.play()

    def play(self):
        if not self.info or self.playing:
            return
        if (self.start, self.end) != self.cache_key:
            self._load_segment()
        self.playing = True
        if not (self.start <= self.pos < self.end - 1e-3):
            self.pos = self.start
        self._idx = int((self.pos - self.start) * self.fps)
        self._dir = 1
        self._restart_timer()
        self.playingChanged.emit(True)

    def pause(self):
        if self.playing:
            self.playing = False
            self.timer.stop()
            self.playingChanged.emit(False)

    def step(self, frames: int):
        self.pause()
        self.seek(self.pos + frames / self.fps)

    def seek(self, t):
        if not self.info:
            return
        self.pos = max(0.0, min(t, self.info.duration))
        self.timeChanged.emit(self.pos)
        idx = int(round((self.pos - self.start) * self.fps))
        if self.cache_key == (self.start, self.end) and 0 <= idx < len(self.cache) and self.start <= self.pos <= self.end:
            self._idx = idx
            self.frameReady.emit(self.cache[idx])
            return
        self._scrub_gen += 1
        gen, info, pos = self._scrub_gen, self.info, self.pos

        def work():
            r = media.frame_at(info, pos, SCRUB_SIDE)
            if r and gen == self._scrub_gen:
                self._scrubFrame.emit(gen, to_qimage(*r))

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- interno
    def _restart_timer(self):
        if self.playing:
            self.timer.start(max(5, int(1000 / (self.fps * self.speed))))

    def _tick(self):
        if not self.cache:
            return
        n_total = max(1, int((self.end - self.start) * self.fps))
        if self._idx >= len(self.cache):
            if not self.cache_complete and self._idx < n_total:
                return  # ainda decodificando: espera
            self._idx = len(self.cache) - 1
        self.frameReady.emit(self.cache[self._idx])
        self.pos = self.start + self._idx / self.fps
        self.timeChanged.emit(self.pos)
        last = len(self.cache) - 1 if self.cache_complete else n_total - 1
        if self.boomerang:
            if self._idx + self._dir > last or self._idx + self._dir < 0:
                self._dir *= -1
            self._idx += self._dir
        else:
            self._idx = self._idx + 1 if self._idx < last else 0

    def _load_segment(self):
        if not self.info:
            return
        self._gen += 1
        gen, info = self._gen, self.info
        start, end = self.start, self.end
        self.cache, self.cache_key, self.cache_complete = [], (start, end), False
        self._idx = 0
        fps = self.fps

        def work():
            for i, (buf, w, h) in enumerate(media.iter_segment(info, start, end, fps, PREVIEW_SIDE)):
                if gen != self._gen or i >= MAX_CACHE_FRAMES:
                    break
                self._segFrame.emit(gen, i, to_qimage(buf, w, h))
            if gen == self._gen:
                self._segDone.emit(gen)

        threading.Thread(target=work, daemon=True).start()

    def _on_seg_frame(self, gen, i, img):
        if gen == self._gen and i == len(self.cache):
            self.cache.append(img)
            if not self.playing and i == int(round((self.pos - self.start) * self.fps)):
                self.frameReady.emit(img)

    def _on_seg_done(self, gen):
        if gen == self._gen:
            self.cache_complete = True

    def _on_scrub_frame(self, gen, img):
        if gen == self._scrub_gen:
            self.frameReady.emit(img)

