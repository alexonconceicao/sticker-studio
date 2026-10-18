"""Área de edição: frame atual, quadro de corte e camadas de texto arrastáveis."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from sticker_studio.gui.textlayer import layer_rect, paint_layer

HANDLE = 14


def checker_brush(cell=10) -> QBrush:
    pm = QPixmap(cell * 2, cell * 2)
    pm.fill(QColor("#ffffff"))
    p = QPainter(pm)
    p.fillRect(0, 0, cell, cell, QColor("#d9d9d9"))
    p.fillRect(cell, cell, cell, cell, QColor("#d9d9d9"))
    p.end()
    return QBrush(pm)


class Viewer(QWidget):
    cropChanged = Signal()
    textSelected = Signal(object)
    textsChanged = Signal()
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.image: QImage | None = None
        self.src_w = self.src_h = 0
        self.crop = QRectF()
        self.square = True
        self.alpha = False
        self.texts = []
        self.selected = None
        self._drag = None
        self._checker = checker_brush()

    # ---------------------------------------------------------------- dados
    def set_source(self, w, h, alpha):
        self.src_w, self.src_h, self.alpha = w, h, alpha
        self.image = None
        self.update()

    def set_image(self, img: QImage):
        self.image = img
        self.update()

    def set_crop(self, rect: QRectF):
        self.crop = QRectF(rect)
        self.cropChanged.emit()
        self.update()

    def select(self, t):
        self.selected = t
        self.textSelected.emit(t)
        self.update()

    # ---------------------------------------------------------------- geometria
    def disp_rect(self) -> QRectF:
        if not self.src_w:
            return QRectF()
        m = 8
        aw, ah = self.width() - 2 * m, self.height() - 2 * m
        s = min(aw / self.src_w, ah / self.src_h)
        w, h = self.src_w * s, self.src_h * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def scale(self):
        r = self.disp_rect()
        return r.width() / self.src_w if self.src_w else 1

    def crop_disp(self) -> QRectF:
        r, s = self.disp_rect(), self.scale()
        return QRectF(r.x() + self.crop.x() * s, r.y() + self.crop.y() * s, self.crop.width() * s, self.crop.height() * s)

    def corners(self):
        c = self.crop_disp()
        return {"nw": c.topLeft(), "ne": c.topRight(), "sw": c.bottomLeft(), "se": c.bottomRight()}

    # ---------------------------------------------------------------- pintura
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0f1115"))
        if not self.src_w:
            p.setPen(QColor("#8a92a3"))
            f = p.font()
            f.setPointSize(13)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "🎬\n\nArraste um vídeo ou figurinha aqui\nou clique em “Abrir”")
            return
        r = self.disp_rect()
        if self.alpha:
            p.fillRect(r, self._checker)
        if self.image is not None:
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            p.drawImage(r, self.image)
        c = self.crop_disp()
        outside = QPainterPath()
        outside.addRect(r)
        inner = QPainterPath()
        inner.addRect(c)
        p.fillPath(outside.subtracted(inner), QColor(0, 0, 0, 150))
        # terços
        p.setPen(QPen(QColor(255, 255, 255, 80), 1))
        for i in (1, 2):
            x = c.x() + c.width() * i / 3
            y = c.y() + c.height() * i / 3
            p.drawLine(QPointF(x, c.top()), QPointF(x, c.bottom()))
            p.drawLine(QPointF(c.left(), y), QPointF(c.right(), y))
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.drawRect(c)
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self.corners().values():
            p.drawRoundedRect(QRectF(pt.x() - HANDLE / 2, pt.y() - HANDLE / 2, HANDLE, HANDLE), 3, 3)
        # textos dentro do quadro
        p.save()
        p.setClipRect(c)
        p.translate(c.topLeft())
        for t in self.texts:
            paint_layer(p, t, c.width(), c.height())
        if self.selected in self.texts:
            br = layer_rect(self.selected, c.width(), c.height())
            pen = QPen(QColor("#ffffff"), 1.5, Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(br)
        p.restore()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self.resized.emit()

    # ---------------------------------------------------------------- mouse
    def _hit_text(self, pos: QPointF):
        c = self.crop_disp()
        local = pos - c.topLeft()
        for t in reversed(self.texts):
            if layer_rect(t, c.width(), c.height()).contains(local):
                return t
        return None

    def mousePressEvent(self, e):
        if not self.src_w or e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        for name, pt in self.corners().items():
            if abs(pos.x() - pt.x()) <= HANDLE and abs(pos.y() - pt.y()) <= HANDLE:
                c = self.crop
                ax = c.right() if "w" in name else c.left()
                ay = c.bottom() if "n" in name else c.top()
                self._drag = ("corner", name, ax, ay)
                return
        t = self._hit_text(pos)
        if t:
            self.select(t)
            self._drag = ("text", t, pos, t.x, t.y)
            return
        if self.crop_disp().contains(pos):
            self._drag = ("move", pos, QRectF(self.crop))

    def mouseMoveEvent(self, e):
        pos = e.position()
        if not self._drag:
            if not self.src_w:
                return
            near = any(abs(pos.x() - pt.x()) <= HANDLE and abs(pos.y() - pt.y()) <= HANDLE for pt in self.corners().values())
            if near:
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif self._hit_text(pos):
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            elif self.crop_disp().contains(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.unsetCursor()
            return
        s = self.scale()
        kind = self._drag[0]
        if kind == "text":
            _, t, p0, tx, ty = self._drag
            c = self.crop_disp()
            t.x = min(1, max(0, tx + (pos.x() - p0.x()) / c.width()))
            t.y = min(1, max(0, ty + (pos.y() - p0.y()) / c.height()))
            self.textsChanged.emit()
            self.update()
        elif kind == "move":
            _, p0, c0 = self._drag
            x = min(max(0, c0.x() + (pos.x() - p0.x()) / s), self.src_w - c0.width())
            y = min(max(0, c0.y() + (pos.y() - p0.y()) / s), self.src_h - c0.height())
            self.set_crop(QRectF(x, y, c0.width(), c0.height()))
        else:
            _, name, ax, ay = self._drag
            r = self.disp_rect()
            px = min(max(0, (pos.x() - r.x()) / s), self.src_w)
            py = min(max(0, (pos.y() - r.y()) / s), self.src_h)
            sx = 1 if "e" in name else -1
            sy = 1 if "s" in name else -1
            max_w = self.src_w - ax if sx > 0 else ax
            max_h = self.src_h - ay if sy > 0 else ay
            mn = max(32, 16 / s)
            w = min(max(abs(px - ax), mn), max_w)
            h = min(max(abs(py - ay), mn), max_h)
            if self.square:
                w = h = min(max(w, h), max_w, max_h)
            self.set_crop(QRectF(ax if sx > 0 else ax - w, ay if sy > 0 else ay - h, w, h))

    def mouseReleaseEvent(self, _):
        self._drag = None
