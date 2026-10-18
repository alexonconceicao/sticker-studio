"""Janela principal do Sticker Studio."""
import shutil
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QRectF, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFontComboBox,
                               QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from sticker_studio import APP_ID, APP_NAME, __version__
from sticker_studio.engine import background, media
from sticker_studio.engine.render import (TARGETS, Cancelled, RenderParams, fit_dims, max_source_span,
                                          render)
from sticker_studio.gui import share
from sticker_studio.gui.player import Player
from sticker_studio.gui.preview import AnimatedPreview, first_frame
from sticker_studio.gui.textlayer import TextLayer, render_png
from sticker_studio.gui.timeline import Timeline
from sticker_studio.gui.viewer import Viewer
from sticker_studio.paths import cache_dir, default_output_dir, resource

VIDEO_FILTER = "Vídeos e figurinhas (*.mp4 *.mov *.m4v *.mkv *.webm *.avi *.gif *.webp *.3gp *.flv *.wmv *.mpg *.mpeg *.ts);;Todos (*)"


class Segmented(QWidget):
    changed = Signal(object)

    def __init__(self, options, value):
        super().__init__()
        self.setObjectName("seg")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(3)
        self.group = QButtonGroup(self)
        self.buttons = {}
        for val, label in options:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setObjectName("segbtn")
            b.clicked.connect(lambda _=False, v=val: self.changed.emit(v))
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[val] = b
        self.set_value(value)

    def set_value(self, v):
        self.value = v
        self.buttons[v].setChecked(True)


class Worker(QThread):
    progress = Signal(str, float)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.cancel = threading.Event()

    def run(self):
        try:
            self.done.emit(self.fn(self))
        except Cancelled:
            self.failed.emit("cancelado")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class ColorButton(QPushButton):
    changed = Signal(str)

    def __init__(self, color):
        super().__init__()
        self.setFixedSize(34, 30)
        self.set_color(color)
        self.clicked.connect(self.pick)

    def set_color(self, c):
        self.color = c
        self.setStyleSheet(f"background:{c}; border:1px solid #3a4152; border-radius:6px;")

    def pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Cor")
        if c.isValid():
            self.set_color(c.name())
            self.changed.emit(c.name())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(resource("icon.svg"))))
        self.settings = QSettings(APP_ID, APP_ID)
        self.out_dir = Path(self.settings.value("out_dir", str(default_output_dir())))
        self.info = None
        self.result = None
        self.worker = None
        self.target, self.shape, self.speed, self.fps = "whatsapp", "square", 1.0, 30
        self.player = Player(self)
        self.setAcceptDrops(True)
        self._build()
        self._wire()
        self.resize(1360, 860)
        self.refresh_recent()

    # ================================================================ interface
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame(objectName="header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 8, 16, 8)
        logo = QLabel()
        logo.setPixmap(QIcon(str(resource("icon.svg"))).pixmap(24, 24))
        title = QLabel(f"<b>{APP_NAME}</b>")
        title.setStyleSheet("font-size:15px")
        self.fname = QLabel("", objectName="muted")
        self.btn_open = QPushButton("Abrir vídeo ou figurinha")
        self.btn_outdir = QPushButton("Pasta de saída…")
        hl.addWidget(logo)
        hl.addWidget(title)
        hl.addSpacing(10)
        hl.addWidget(self.fname, 1)
        hl.addWidget(self.btn_outdir)
        hl.addWidget(self.btn_open)
        outer.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # ---- coluna do editor
        left = QVBoxLayout()
        left.setContentsMargins(16, 12, 16, 12)
        left.setSpacing(10)
        self.viewer = Viewer()
        left.addWidget(self.viewer, 1)

        row = QHBoxLayout()
        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(44)
        self.timeline = Timeline()
        self.lbl_time = QLabel("0.00 / 0.00", objectName="muted")
        self.lbl_time.setMinimumWidth(110)
        row.addWidget(self.btn_play)
        row.addWidget(self.timeline, 1)
        row.addWidget(self.lbl_time)
        left.addLayout(row)

        row = QHBoxLayout()
        self.btn_in = QPushButton("Início aqui  [I]")
        self.btn_out = QPushButton("Fim aqui  [O]")
        hint = QLabel("Espaço: play/pause · ←/→: 1 frame · arraste o quadro pra enquadrar e os textos pra posicionar",
                      objectName="muted")
        row.addWidget(self.btn_in)
        row.addWidget(self.btn_out)
        row.addWidget(hint, 1)
        left.addLayout(row)

        # ---- barra de texto
        tb = QHBoxLayout()
        tb.setSpacing(8)
        self.btn_add_text = QPushButton("+ Texto")
        self.t_text = QPlainTextEdit()
        self.t_text.setPlaceholderText("Texto da figurinha (Enter quebra linha)")
        self.t_text.setFixedHeight(48)
        self.t_font = QFontComboBox()
        self.t_font.setMaximumWidth(190)
        self.t_bold = QPushButton("B")
        self.t_bold.setCheckable(True)
        self.t_bold.setChecked(True)
        self.t_bold.setFixedWidth(34)
        f = self.t_bold.font()
        f.setBold(True)
        self.t_bold.setFont(f)
        self.t_size = QSpinBox(minimum=10, maximum=240, value=64, suffix=" px")
        self.t_fill = ColorButton("#ffffff")
        self.t_stroke = ColorButton("#000000")
        self.t_stroke_w = QSpinBox(minimum=0, maximum=30, value=6)
        self.t_del = QPushButton("Apagar")
        tb.addWidget(self.btn_add_text)
        tb.addWidget(self.t_text, 1)
        for w in (self.t_font, self.t_bold, QLabel("Tamanho"), self.t_size, QLabel("Cor"), self.t_fill,
                  QLabel("Contorno"), self.t_stroke, self.t_stroke_w, self.t_del):
            tb.addWidget(w)
        self.text_controls = [self.t_text, self.t_font, self.t_bold, self.t_size, self.t_fill, self.t_stroke,
                              self.t_stroke_w, self.t_del]
        left.addLayout(tb)
        body.addLayout(left, 1)

        # ---- painel lateral
        side = QFrame(objectName="side")
        side.setFixedWidth(380)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 12, 16, 12)
        sl.setSpacing(8)

        def label(t):
            l = QLabel(t.upper(), objectName="cap")
            sl.addWidget(l)

        label("Destino")
        self.seg_target = Segmented([("whatsapp", "WhatsApp · webp"), ("telegram", "Telegram · webm")], "whatsapp")
        sl.addWidget(self.seg_target)
        label("Enquadramento")
        self.seg_shape = Segmented([("square", "Quadrado"), ("free", "Livre"), ("full", "Tela toda")], "square")
        sl.addWidget(self.seg_shape)
        label("Velocidade")
        self.seg_speed = Segmented([(0.5, "0.5×"), (1.0, "1×"), (1.5, "1.5×"), (2.0, "2×")], 1.0)
        sl.addWidget(self.seg_speed)
        label("FPS")
        self.seg_fps = Segmented([(30, "30"), (24, "24"), (20, "20"), (15, "15")], 30)
        sl.addWidget(self.seg_fps)
        self.chk_boom = QCheckBox("Boomerang (vai e volta)")
        self.chk_sharp = QCheckBox("Realçar nitidez")
        self.chk_sharp.setChecked(True)
        self.chk_bg = QCheckBox("Remover fundo (IA)")
        self.cmb_model = QComboBox()
        for k, m in background.MODELS.items():
            self.cmb_model.addItem(m["label"], k)
        self.cmb_model.setVisible(False)
        if not background.available():
            self.chk_bg.setEnabled(False)
            self.chk_bg.setToolTip("onnxruntime não está instalado")
        sl.addWidget(self.chk_boom)
        sl.addWidget(self.chk_sharp)
        sl.addWidget(self.chk_bg)
        sl.addWidget(self.cmb_model)
        self.lbl_dur = QLabel("", objectName="dur")
        sl.addWidget(self.lbl_dur)
        self.btn_go = QPushButton("Gerar figurinha", objectName="primary")
        self.btn_go.setMinimumHeight(38)
        sl.addWidget(self.btn_go)
        self.prog = QProgressBar()
        self.prog.setRange(0, 1000)
        self.prog.setTextVisible(False)
        self.prog.setFixedHeight(6)
        self.lbl_msg = QLabel("", objectName="muted")
        self.lbl_msg.setWordWrap(True)
        self.prog.hide()
        sl.addWidget(self.prog)
        sl.addWidget(self.lbl_msg)

        self.result_box = QFrame()
        rg = QGridLayout(self.result_box)
        rg.setContentsMargins(0, 4, 0, 0)
        rg.setHorizontalSpacing(10)
        rg.setVerticalSpacing(6)
        self.lbl_meta = QLabel("", objectName="muted")
        self.lbl_meta.setWordWrap(True)
        self.lbl_warn = QLabel("", objectName="warn")
        self.lbl_warn.setWordWrap(True)
        rg.addWidget(self.lbl_meta, 0, 0, 1, 2)
        rg.addWidget(self.lbl_warn, 1, 0, 1, 2)
        self.preview = AnimatedPreview()
        self.preview.setFixedSize(150, 150)
        rg.addWidget(self.preview, 2, 0, 5, 1)
        self.btn_wa = QPushButton("Mandar no WhatsApp")
        self.btn_copy = QPushButton("Copiar arquivo")
        self.btn_edit = QPushButton("Editar (pôr texto)")
        self.btn_save = QPushButton("Salvar como…")
        self.btn_folder = QPushButton("Abrir pasta")
        for i, b in enumerate((self.btn_wa, self.btn_copy, self.btn_edit, self.btn_save, self.btn_folder), 2):
            rg.addWidget(b, i, 1)
        self.lbl_tip = QLabel("", objectName="muted")
        self.lbl_tip.setWordWrap(True)
        self.lbl_tip.setMinimumHeight(48)
        rg.addWidget(self.lbl_tip, 7, 0, 1, 2)
        self.result_box.hide()
        sl.addWidget(self.result_box)

        sl.addStretch(1)
        label("Recentes")
        self.recent = QListWidget()
        self.recent.setViewMode(QListWidget.ViewMode.IconMode)
        self.recent.setIconSize(QSize(56, 56))
        self.recent.setGridSize(QSize(64, 64))
        self.recent.setFixedHeight(84)
        self.recent.setFlow(QListWidget.Flow.LeftToRight)
        self.recent.setWrapping(False)
        self.recent.setMovement(QListWidget.Movement.Static)
        self.recent.setResizeMode(QListWidget.ResizeMode.Adjust)
        sl.addWidget(self.recent)
        ver = QLabel(f"v{__version__}", objectName="muted")
        ver.setAlignment(Qt.AlignmentFlag.AlignRight)
        sl.addWidget(ver)
        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(side.width() + 2)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body.addWidget(scroll)

        self.set_editor_enabled(False)
        self.update_text_controls(None)

    def _wire(self):
        self.btn_open.clicked.connect(self.choose_file)
        self.btn_outdir.clicked.connect(self.choose_outdir)
        self.btn_play.clicked.connect(self.player.toggle)
        self.btn_in.clicked.connect(self.set_in)
        self.btn_out.clicked.connect(self.set_out)
        self.player.frameReady.connect(self.viewer.set_image)
        self.viewer.resized.connect(self.on_viewer_resized)
        self.player.timeChanged.connect(self.on_time)
        self.player.playingChanged.connect(lambda p: self.btn_play.setText("⏸" if p else "▶"))
        self.timeline.max_span = self.max_span
        self.timeline.rangeChanged.connect(self.set_range)
        self.timeline.seekRequested.connect(self.player.seek)
        self.viewer.textSelected.connect(self.update_text_controls)
        self.seg_target.changed.connect(self.on_target)
        self.seg_shape.changed.connect(self.on_shape)
        self.seg_speed.changed.connect(self.on_speed)
        self.seg_fps.changed.connect(lambda v: setattr(self, "fps", v) or self.seg_fps.set_value(v))
        self.chk_boom.toggled.connect(self.on_boom)
        self.chk_bg.toggled.connect(self.cmb_model.setVisible)
        self.btn_go.clicked.connect(self.generate)
        # texto
        self.btn_add_text.clicked.connect(self.add_text)
        self.t_text.textChanged.connect(lambda: self.set_text_prop("text", self.t_text.toPlainText()))
        self.t_font.currentFontChanged.connect(lambda f: self.set_text_prop("font", f.family()))
        self.t_bold.toggled.connect(lambda b: self.set_text_prop("bold", b))
        self.t_size.valueChanged.connect(lambda v: self.set_text_prop("size", v))
        self.t_fill.changed.connect(lambda c: self.set_text_prop("fill", c))
        self.t_stroke.changed.connect(lambda c: self.set_text_prop("stroke", c))
        self.t_stroke_w.valueChanged.connect(lambda v: self.set_text_prop("stroke_w", v))
        self.t_del.clicked.connect(self.delete_text)
        # resultado
        self.btn_wa.clicked.connect(self.send_whatsapp)
        self.btn_copy.clicked.connect(self.copy_result)
        self.btn_edit.clicked.connect(lambda: self.result and self.open_path(self.result))
        self.btn_save.clicked.connect(self.save_as)
        self.btn_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.out_dir))))
        self.recent.itemClicked.connect(lambda it: self.show_result(Path(it.data(Qt.ItemDataRole.UserRole))))
        # atalhos (campos de texto continuam recebendo as teclas normalmente)
        for key, fn in (("Space", self.player.toggle), ("I", self.set_in), ("O", self.set_out),
                        ("Left", lambda: self.player.step(-1)), ("Right", lambda: self.player.step(1)),
                        ("Ctrl+O", self.choose_file)):
            QShortcut(QKeySequence(key), self, fn)

    def on_viewer_resized(self):
        r = self.viewer.disp_rect()
        side = max(r.width(), r.height()) * self.viewer.devicePixelRatioF()
        self.player.display_side = side or 1280

    def set_editor_enabled(self, on):
        for w in (self.btn_play, self.btn_in, self.btn_out, self.btn_go, self.btn_add_text):
            w.setEnabled(on)

    # ================================================================ arquivos
    def choose_file(self):
        start = self.settings.value("last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Abrir vídeo ou figurinha", start, VIDEO_FILTER)
        if path:
            self.settings.setValue("last_dir", str(Path(path).parent))
            self.open_path(Path(path))

    def choose_outdir(self):
        d = QFileDialog.getExistingDirectory(self, "Pasta onde salvar as figurinhas", str(self.out_dir))
        if d:
            self.out_dir = Path(d)
            self.settings.setValue("out_dir", d)
            self.refresh_recent()

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        urls = [u for u in e.mimeData().urls() if u.isLocalFile()]
        if urls:
            self.open_path(Path(urls[0].toLocalFile()))

    def open_path(self, path: Path):
        self.player.pause()
        self.show_msg(f"abrindo {path.name}…", 0.3)
        w = Worker(lambda _w: media.open_media(path, cache_dir() / "imports"))
        w.done.connect(self.load_info)
        w.failed.connect(lambda m: self.show_error(f"não consegui abrir: {m}"))
        self._keep(w)

    def _keep(self, w):
        self._workers = [x for x in getattr(self, "_workers", []) if x.isRunning()] + [w]
        w.start()

    def load_info(self, info):
        self.hide_msg()
        self.info = info
        label = f"{'✏️ editando ' if info.sticker else ''}{info.name} · {info.duration:.2f}s · {info.fps:g} fps"
        self.fname.setText(label + (" · HDR→SDR" if info.hdr else ""))
        if info.sticker:
            self.on_target("telegram" if info.name.lower().endswith(".webm") else "whatsapp", reset=False)
            self.seg_shape.set_value("full")
            self.shape = "full"
            self.on_speed(1.0)
            self.chk_boom.setChecked(False)
            self.chk_bg.setChecked(False)
        self.viewer.set_source(info.width, info.height, info.alpha or info.sticker)
        self.on_viewer_resized()
        self.viewer.square = self.shape == "square"
        self.reset_crop()
        self.player.set_media(info)
        self.timeline.set_duration(info.duration)
        self.set_range(0.0, min(info.duration, self.max_span()))
        self.set_editor_enabled(True)
        self.player.play()

    # ================================================================ trecho
    def max_span(self):
        return max_source_span(self.target, self.speed, self.chk_boom.isChecked())

    def set_range(self, s, e):
        if not self.info:
            return
        e = min(e, self.info.duration)
        s = max(0.0, min(s, e - 0.1))
        if e - s > self.max_span():
            e = s + self.max_span()
        self.timeline.set_range(s, e)
        self.player.set_range(s, e)
        self.update_duration()

    def set_in(self):
        if self.info:
            s = self.player.pos
            self.set_range(s, max(self.timeline.end, s + 0.1))

    def set_out(self):
        if self.info:
            e = max(self.player.pos, 0.1)
            s = min(self.timeline.start, e - 0.1)
            self.set_range(max(s, e - self.max_span()), e)

    def on_time(self, t):
        self.timeline.set_pos(t)
        self.lbl_time.setText(f"{t:.2f} / {self.info.duration:.2f}" if self.info else "")

    def update_duration(self):
        span = self.timeline.end - self.timeline.start
        out = span / self.speed * (2 if self.chk_boom.isChecked() else 1)
        lim = TARGETS[self.target]["max_dur"]
        self.lbl_dur.setText(f"Duração: <b>{out:.2f}s</b> (máx {lim:g}s) · trecho "
                             f"{self.timeline.start:.2f}–{self.timeline.end:.2f}")

    # ================================================================ opções
    def on_target(self, v, reset=True):
        self.target = v
        self.seg_target.set_value(v)
        if reset and self.info:
            self.set_range(self.timeline.start, self.timeline.end)
        self.update_duration()

    def on_shape(self, v):
        self.shape = v
        self.seg_shape.set_value(v)
        self.viewer.square = v == "square"
        self.reset_crop()

    def on_speed(self, v):
        self.speed = v
        self.seg_speed.set_value(v)
        self.player.set_speed(v)
        if self.info:
            self.set_range(self.timeline.start, self.timeline.end)
        self.update_duration()

    def on_boom(self, b):
        self.player.set_boomerang(b)
        if self.info:
            self.set_range(self.timeline.start, self.timeline.end)
        self.update_duration()

    def reset_crop(self):
        if not self.info:
            return
        w, h = self.info.width, self.info.height
        if self.shape == "square":
            s = min(w, h)
            self.viewer.set_crop(QRectF((w - s) / 2, (h - s) / 2, s, s))
        else:
            self.viewer.set_crop(QRectF(0, 0, w, h))

    # ================================================================ textos
    def add_text(self):
        last = self.viewer.selected
        t = TextLayer(y=0.15 if self.viewer.texts else 0.85)
        if last:
            t.font, t.bold, t.size, t.fill, t.stroke, t.stroke_w = (
                last.font, last.bold, last.size, last.fill, last.stroke, last.stroke_w)
        self.viewer.texts.append(t)
        self.viewer.select(t)
        self.t_text.setFocus()
        self.t_text.selectAll()

    def delete_text(self):
        t = self.viewer.selected
        if t in self.viewer.texts:
            self.viewer.texts.remove(t)
        self.viewer.select(self.viewer.texts[-1] if self.viewer.texts else None)

    def update_text_controls(self, t):
        for w in self.text_controls:
            w.setEnabled(t is not None)
        if not t:
            return
        for w in self.text_controls:
            w.blockSignals(True)
        if self.t_text.toPlainText() != t.text:
            self.t_text.setPlainText(t.text)
        self.t_font.setCurrentFont(QFont(t.font))
        self.t_bold.setChecked(t.bold)
        self.t_size.setValue(int(t.size))
        self.t_fill.set_color(t.fill)
        self.t_stroke.set_color(t.stroke)
        self.t_stroke_w.setValue(int(t.stroke_w))
        for w in self.text_controls:
            w.blockSignals(False)

    def set_text_prop(self, key, value):
        t = self.viewer.selected
        if t is not None:
            setattr(t, key, value)
            self.viewer.update()

    # ================================================================ geração
    def generate(self):
        if not self.info:
            return
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            return
        c = self.viewer.crop
        crop = (round(c.x()), round(c.y()), round(c.width()), round(c.height()))
        ow, oh = fit_dims(crop[2], crop[3], 1024)  # texto renderizado em 2x
        params = RenderParams(
            media=self.info, target=self.target, start=self.timeline.start, end=self.timeline.end,
            crop=crop, speed=self.speed, fps=self.fps, boomerang=self.chk_boom.isChecked(),
            remove_bg=self.chk_bg.isChecked(), sharpen=self.chk_sharp.isChecked(), bg_model=self.cmb_model.currentData(),
            overlay_png=render_png(self.viewer.texts, ow, oh), out_dir=self.out_dir,
        )
        w = Worker(lambda wk: render(params, cache_dir() / "jobs",
                                     progress=lambda m, f: wk.progress.emit(m, f),
                                     cancelled=wk.cancel.is_set))
        w.progress.connect(self.show_msg)
        w.done.connect(self.on_rendered)
        w.failed.connect(self.on_render_failed)
        self.worker = w
        self.btn_go.setText("Cancelar")
        self.show_msg("iniciando…", 0)
        self._keep(w)

    def on_rendered(self, res):
        self.btn_go.setText("Gerar figurinha")
        self.hide_msg()
        self.show_result(res.path, res)
        self.refresh_recent()

    def on_render_failed(self, msg):
        self.btn_go.setText("Gerar figurinha")
        self.show_error(msg)

    def show_msg(self, msg, frac):
        self.prog.show()
        self.prog.setValue(int(frac * 1000))
        self.lbl_msg.setStyleSheet("")
        self.lbl_msg.setText(msg)

    def hide_msg(self):
        self.prog.hide()
        self.lbl_msg.setText("")

    def show_error(self, msg):
        self.prog.hide()
        self.lbl_msg.setStyleSheet("color:#ef4444")
        self.lbl_msg.setText(msg)

    # ================================================================ resultado
    def show_result(self, path: Path, res=None):
        if not path.exists():
            return
        self.result = path
        self.result_box.show()
        self.preview.load(path)
        webm = path.suffix.lower() == ".webm"
        kb = path.stat().st_size / 1024
        if res:
            meta = f"{kb:.0f} KB · {res.width}×{res.height} · {res.fps} fps · {res.duration:g}s · {res.quality}"
        else:
            meta = f"{kb:.0f} KB · {path.name}"
        self.lbl_meta.setText(meta)
        self.lbl_warn.setText(res.warning if res and res.warning else "")
        self.btn_wa.setVisible(not webm)
        self.lbl_tip.setText(
            "Telegram: no @Stickers use /newvideo (ou /addsticker) e envie o .webm como arquivo."
            if webm else
            "WhatsApp: “Mandar no WhatsApp” copia a figurinha e abre o ZapZap; cole com Ctrl+V na conversa. "
            "Pra ir como figurinha animada, o ZapZap precisa do script do projeto (veja o README).")

    def copy_result(self):
        if self.result:
            share.copy_file(self.result)
            self.btn_copy.setText("Copiado ✓")
            QTimer.singleShot(1500, lambda: self.btn_copy.setText("Copiar arquivo"))

    def send_whatsapp(self):
        if not self.result:
            return
        share.copy_file(self.result)
        opened = share.open_zapzap()
        self.btn_wa.setText("Copiado ✓ cole no ZapZap" if opened else "Copiado ✓ cole no WhatsApp")
        QTimer.singleShot(2500, lambda: self.btn_wa.setText("Mandar no WhatsApp"))

    def save_as(self):
        if not self.result:
            return
        dst, _ = QFileDialog.getSaveFileName(self, "Salvar figurinha", str(Path.home() / self.result.name))
        if dst:
            shutil.copyfile(self.result, dst)

    def refresh_recent(self):
        self.recent.clear()
        if not self.out_dir.is_dir():
            return
        files = sorted((f for f in self.out_dir.iterdir() if f.suffix.lower() in (".webp", ".webm")),
                       key=lambda f: f.stat().st_mtime, reverse=True)[:24]
        for f in files:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, str(f))
            it.setToolTip(f.name)
            img = first_frame(f, 112)
            if img:
                pm = QPixmap(img.size())
                pm.fill(QColor("#e8e8e8"))
                from PySide6.QtGui import QPainter

                p = QPainter(pm)
                p.drawImage(0, 0, img)
                p.end()
                it.setIcon(QIcon(pm))
            self.recent.addItem(it)

    def closeEvent(self, e):  # noqa: N802
        self.player.pause()
        if self.worker and self.worker.isRunning():
            self.worker.cancel.set()
            self.worker.wait(5000)
        super().closeEvent(e)


def fatal(msg):
    QMessageBox.critical(None, APP_NAME, msg)
    sys.exit(1)
