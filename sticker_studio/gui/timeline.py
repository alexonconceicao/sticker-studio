"""Linha do tempo com seleção de trecho (início/fim) e cursor de reprodução."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

ACCENT = QColor("#7c5cff")


class Timeline(QWidget):
    rangeChanged = Signal(float, float)
    seekRequested = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(40)
        self.setMouseTracking(True)
        self.duration = 0.0
        self.start = self.end = self.pos = 0.0
        self.max_span = lambda: 1e9
        self._drag = None

    def set_duration(self, d):
        self.duration = d
        self.update()

    def set_range(self, s, e):
        self.start, self.end = s, e
        self.update()

    def set_pos(self, t):
        self.pos = t
        self.update()

    def _x(self, t):
        return 8 + (self.width() - 16) * (t / self.duration if self.duration else 0)

    def _t(self, x):
        return min(self.duration, max(0.0, (x - 8) / max(1, self.width() - 16) * self.duration))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(8, 6, self.width() - 16, self.height() - 12)
        p.setPen(QPen(QColor("#262b36")))
        p.setBrush(QColor("#1b1f28"))
        p.drawRoundedRect(track, 6, 6)
        if not self.duration:
            return
        sel = QRectF(self._x(self.start), track.y(), self._x(self.end) - self._x(self.start), track.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(124, 92, 255, 70))
        p.drawRect(sel)
        p.setBrush(ACCENT)
        for x in (sel.left(), sel.right()):
            p.drawRoundedRect(QRectF(x - 5, 2, 10, self.height() - 4), 3, 3)
        p.setPen(QPen(QColor("#ffffff"), 2))
        x = self._x(self.pos)
        p.drawLine(int(x), 4, int(x), self.height() - 4)

    def mousePressEvent(self, e):
        if not self.duration:
            return
        x = e.position().x()
        if abs(x - self._x(self.start)) <= 8:
            self._drag = "s"
        elif abs(x - self._x(self.end)) <= 8:
            self._drag = "e"
        else:
            self._drag = "seek"
            self.seekRequested.emit(self._t(x))

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if not self._drag:
            near = self.duration and min(abs(x - self._x(self.start)), abs(x - self._x(self.end))) <= 8
            self.setCursor(Qt.CursorShape.SizeHorCursor if near else Qt.CursorShape.PointingHandCursor)
            return
        t, m = self._t(x), self.max_span()
        if self._drag == "seek":
            self.seekRequested.emit(t)
            return
        if self._drag == "s":
            s = min(t, self.end - 0.1)
            e_ = self.end if self.end - s <= m else s + m
            self.rangeChanged.emit(s, e_)
            self.seekRequested.emit(s)
        else:
            e_ = max(t, self.start + 0.1)
            s = self.start if e_ - self.start <= m else e_ - m
            self.rangeChanged.emit(s, e_)
            self.seekRequested.emit(max(s, e_ - 0.05))

    def mouseReleaseEvent(self, _):
        self._drag = None
