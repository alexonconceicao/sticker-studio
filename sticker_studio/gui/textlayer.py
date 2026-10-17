"""Camadas de texto: desenhadas igual na prévia e na exportação."""
from dataclasses import dataclass, field

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QFontMetricsF, QImage, QPainter,
                           QPainterPath, QPen)

BASE = 512  # tamanho e contorno são medidos nessa base (lado maior da figurinha)
PREFERRED_FONTS = ["Impact", "Anton", "Arial Black", "Bebas Neue", "Comic Sans MS", "Ubuntu", "Noto Sans",
                   "DejaVu Sans", "Arial", "Liberation Sans"]


def default_font() -> str:
    fams = set(QFontDatabase.families())
    return next((f for f in PREFERRED_FONTS if f in fams), QFont().defaultFamily())


@dataclass
class TextLayer:
    text: str = "TEXTO"
    x: float = 0.5  # centro, normalizado no quadro
    y: float = 0.85
    size: float = 64
    font: str = field(default_factory=default_font)
    bold: bool = True
    italic: bool = False
    fill: str = "#ffffff"
    stroke: str = "#000000"
    stroke_w: float = 6

    def qfont(self, px: float) -> QFont:
        f = QFont(self.font)
        f.setPixelSize(max(1, int(round(px))))
        f.setBold(self.bold)
        f.setItalic(self.italic)
        f.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        return f


def is_emoji_char(ch: str) -> bool:
    cp = ord(ch)
    return (cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF or cp in (0x200D, 0xFE0F, 0x20E3)
            or 0x1F1E6 <= cp <= 0x1F1FF)


def segments(line: str):
    """Divide a linha em trechos [(texto, é_emoji)].

    Emoji colorido (fonte bitmap) não aceita negrito/itálico sintético nem contorno,
    então é desenhado com uma fonte normal e sem contorno.
    """
    out = []
    for ch in line:
        e = is_emoji_char(ch)
        if out and out[-1][1] == e:
            out[-1][0] += ch
        else:
            out.append([ch, e])
    return [(t, e) for t, e in out]


def plain_font(f: QFont) -> QFont:
    g = QFont(f)
    g.setBold(False)
    g.setItalic(False)
    return g


def line_width(font: QFont, line: str) -> float:
    fm, fe = QFontMetricsF(font), QFontMetricsF(plain_font(font))
    return sum((fe if e else fm).horizontalAdvance(t) for t, e in segments(line))


def layer_rect(t: TextLayer, w: float, h: float) -> QRectF:
    """Retângulo ocupado pelo texto (com contorno), em pixels de um quadro w×h."""
    k = max(w, h) / BASE
    fm = QFontMetricsF(t.qfont(t.size * k))
    lines = t.text.split("\n") or [""]
    lh = fm.height()
    font = t.qfont(t.size * k)
    tw = max((line_width(font, ln) for ln in lines), default=0)
    pad = t.stroke_w * k + 4
    bw, bh = tw + 2 * pad, lh * len(lines) + 2 * pad
    return QRectF(t.x * w - bw / 2, t.y * h - bh / 2, bw, bh)


def paint_layer(p: QPainter, t: TextLayer, w: float, h: float):
    if not t.text.strip():
        return
    k = max(w, h) / BASE
    font = t.qfont(t.size * k)
    fm = QFontMetricsF(font)
    lines = t.text.split("\n")
    lh = fm.height()
    top = t.y * h - lh * len(lines) / 2
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    efont = plain_font(font)
    fe = QFontMetricsF(efont)
    pen = QPen(QColor(t.stroke), t.stroke_w * 2 * k)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    for i, ln in enumerate(lines):
        segs = segments(ln)
        baseline = top + i * lh + fm.ascent()
        # contorno primeiro (só texto), depois o preenchimento por cima
        for stroke_pass in (True, False):
            x = t.x * w - line_width(font, ln) / 2
            for seg, emoji in segs:
                adv = (fe if emoji else fm).horizontalAdvance(seg)
                if stroke_pass and not emoji and t.stroke_w > 0:
                    path = QPainterPath()
                    path.addText(QPointF(x, baseline), font, seg)
                    p.strokePath(path, pen)
                elif not stroke_pass:
                    p.setFont(efont if emoji else font)
                    p.setPen(QColor(t.fill))
                    p.drawText(QPointF(x, baseline), seg)
                x += adv
    p.restore()


def render_png(layers, w: int, h: int) -> bytes | None:
    """PNG transparente w×h com as camadas, ou None se não houver texto."""
    used = [t for t in layers if t.text.strip()]
    if not used:
        return None
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    for t in used:
        paint_layer(p, t, w, h)
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba.data())
