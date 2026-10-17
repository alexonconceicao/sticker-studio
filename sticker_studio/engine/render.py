"""Pipeline de geração da figurinha.

1. extrai frames PNG do trecho (corte, velocidade, fps, escala lanczos, HDR→SDR)
2. remove fundo (opcional, IA)
3. aplica a camada de texto (PNG transparente feito pela interface)
4. monta a sequência final (boomerang, limite de duração)
5. codifica buscando a melhor qualidade que cabe no limite de tamanho
"""
import io
import math
import os
import shutil
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sticker_studio.engine import ffmpeg
from sticker_studio.engine.media import MediaInfo

SIZE = 512
TARGETS = {
    # limites oficiais com margem de segurança
    "whatsapp": {"ext": "webp", "max_bytes": 495_000, "max_dur": 10.0, "label": "500 KB"},
    "telegram": {"ext": "webm", "max_bytes": 255_000, "max_dur": 3.0, "label": "256 KB"},
}


class Cancelled(Exception):
    pass


@dataclass
class RenderParams:
    media: MediaInfo
    target: str = "whatsapp"
    start: float = 0.0
    end: float = 3.0
    crop: tuple = (0, 0, 0, 0)  # x, y, w, h em pixels da fonte
    speed: float = 1.0
    fps: int = 30
    boomerang: bool = False
    remove_bg: bool = False
    sharpen: bool = True  # realce leve depois de reduzir pra 512 px
    bg_model: str = "birefnet-general"
    overlay_png: bytes | None = None  # texto já renderizado, do tamanho do conteúdo
    out_dir: Path = field(default_factory=Path.cwd)


@dataclass
class RenderResult:
    path: Path
    bytes: int
    width: int
    height: int
    fps: int
    frames: int
    duration: float
    quality: str
    warning: str | None = None


def even(n):
    return max(2, int(round(n / 2)) * 2)


def fit_dims(w, h, box=SIZE):
    """Lado maior = box, mantendo proporção, dimensões pares."""
    if w >= h:
        return box, min(box, even(box * h / w))
    return min(box, even(box * w / h)), box


def output_dims(p: RenderParams):
    _, _, cw, ch = p.crop
    return fit_dims(cw, ch)


def max_source_span(target: str, speed: float, boomerang: bool) -> float:
    return TARGETS[target]["max_dur"] * speed / (2 if boomerang else 1)


def render(p: RenderParams, work_root: Path, progress=lambda msg, frac: None, cancelled=lambda: False) -> RenderResult:
    target = TARGETS[p.target]
    work = work_root / f"job-{uuid.uuid4().hex[:10]}"
    frames = work / "frames"
    frames.mkdir(parents=True)

    def check():
        if cancelled():
            raise Cancelled()

    try:
        info = p.media
        start = max(0.0, p.start)
        end = min(p.end, info.duration or p.end)
        speed = min(4.0, max(0.25, p.speed))
        fps = min(30, max(5, int(p.fps)))
        if end - start < 0.1:
            raise ValueError("trecho muito curto")
        end = min(end, start + max_source_span(p.target, speed, p.boomerang))

        cx, cy, cw, ch = (int(v) for v in p.crop)
        cx, cy = max(0, cx), max(0, cy)
        cw, ch = min(cw, info.width - cx), min(ch, info.height - cy)
        cw, ch = max(2, cw - cw % 2), max(2, ch - ch % 2)
        fw, fh = fit_dims(cw, ch)

        vf = []
        if info.hdr and ffmpeg.has_filter("zscale"):
            vf.append("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                      "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")
        vf += [f"crop={cw}:{ch}:{cx}:{cy}", f"setpts=(PTS-STARTPTS)/{speed}", f"fps={fps}",
               f"scale={fw}:{fh}:flags=lanczos+accurate_rnd+full_chroma_int"]
        if p.sharpen:
            vf.append("unsharp=5:5:0.6:5:5:0")
        vf.append("format=rgba")

        progress("extraindo frames", 0.02)
        ffmpeg.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}",
            *info.decoder_args(), "-i", str(info.path), "-an", "-vf", ",".join(vf), "-fps_mode", "cfr",
            str(frames / "%05d.png"),
        ])
        files = sorted(frames.glob("*.png"))
        if not files:
            raise ValueError("nenhum frame extraído (confira o trecho)")
        check()

        if p.remove_bg:
            files = remove_background(files, work / "nobg", p.bg_model, progress, check)
        if p.overlay_png:
            files = apply_overlay(files, p.overlay_png, work / "txt", progress)
        check()

        seq = work / "seq"
        seq.mkdir()
        order = files + (files[-2:0:-1] if p.boomerang else [])
        order = order[: max(1, math.floor(target["max_dur"] * fps))]
        for i, f in enumerate(order, 1):
            dst = seq / f"{i:05d}.png"
            try:
                os.link(f, dst)
            except OSError:
                shutil.copyfile(f, dst)

        p.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = p.out_dir / f"sticker-{stamp}.{target['ext']}"
        n = 1
        while out.exists():
            out = p.out_dir / f"sticker-{stamp}-{n}.{target['ext']}"
            n += 1
        encode = encode_webp if p.target == "whatsapp" else encode_webm
        best = encode(seq, fps, work, target, progress, check)
        shutil.move(best["path"], out)
        w, h = (SIZE, SIZE) if p.target == "whatsapp" else (fw, fh)
        progress("pronto", 1.0)
        return RenderResult(out, out.stat().st_size, w, h, best["fps"], len(order),
                            round(len(order) / fps, 2), best["label"], best.get("warning"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def remove_background(files, out: Path, model, progress, check):
    from PIL import Image

    from sticker_studio.engine.background import Remover

    progress("carregando modelo de IA", 0.1)
    rm = Remover(model, download_progress=lambda f: progress(f"baixando modelo de IA {f:.0%}", 0.1))
    out.mkdir()
    result = []
    for i, f in enumerate(files, 1):
        check()
        dst = out / f.name
        rm.cutout(Image.open(f)).save(dst, compress_level=1)
        result.append(dst)
        progress(f"removendo fundo ({rm.device}) {i}/{len(files)}", 0.12 + 0.58 * i / len(files))
    return result


def apply_overlay(files, png: bytes, out: Path, progress):
    """Compõe o PNG de texto sobre cada frame, somando o alpha."""
    from PIL import Image

    progress("aplicando texto", 0.72)
    out.mkdir()
    over = Image.open(io.BytesIO(png)).convert("RGBA")
    sized = None
    result = []
    for f in files:
        im = Image.open(f).convert("RGBA")
        if sized is None or sized.size != im.size:
            sized = over.resize(im.size, Image.Resampling.LANCZOS)
        dst = out / f.name
        Image.alpha_composite(im, sized).save(dst, compress_level=1)
        result.append(dst)
    return result


# ---------------------------------------------------------------- codificação


def fps_ladder(fps):
    return [fps] + [f for f in (24, 20, 15, 12, 10) if f < fps]


def search_encode(levels, encode_one, max_bytes, progress, label, check):
    """Nível de melhor qualidade que cabe em max_bytes (levels: do melhor pro pior).

    Passo grosso em paralelo, depois refina entre o último que estourou e o primeiro que coube.
    """
    workers = max(2, (os.cpu_count() or 4) - 2)

    def batch(vals, base, span):
        check()
        res = {}
        with ThreadPoolExecutor(workers) as ex:
            for i, (v, out) in enumerate(zip(vals, ex.map(encode_one, vals)), 1):
                res[v] = out
                progress(f"comprimindo {label}", base + span * i / len(vals))
        return res

    coarse = levels[:: max(1, len(levels) // 9)]
    if coarse[-1] != levels[-1]:
        coarse.append(levels[-1])
    res = batch(coarse, 0.75, 0.12)
    fit = [v for v in coarse if res[v].stat().st_size <= max_bytes]
    if not fit:
        return None
    first = fit[0]
    i = levels.index(first)
    prev = levels.index(coarse[coarse.index(first) - 1]) if coarse.index(first) else i
    fine = levels[prev + 1: i]
    if fine:
        res.update(batch(fine, 0.87, 0.1))
    best = next(v for v in levels[prev: i + 1] if v in res and res[v].stat().st_size <= max_bytes)
    return best, res[best]


def encode_webp(seq, fps, work, target, progress, check):
    pad = f"pad={SIZE}:{SIZE}:(ow-iw)/2:(oh-ih)/2:color=black@0"
    ladder = fps_ladder(fps)
    for k, f_out in enumerate(ladder):
        vf = (f"fps={f_out}," if f_out != fps else "") + f"{pad},format=rgba"

        def one(q, vf=vf, f_out=f_out):
            out = work / f"try-{f_out}-{q}.webp"
            ffmpeg.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
                "-i", str(seq / "%05d.png"), "-vf", vf, "-c:v", "libwebp_anim", "-lossless", "0",
                "-q:v", str(q), "-compression_level", "5", "-loop", "0", "-an",
                "-map_metadata", "-1", "-y", str(out),
            ])
            return out

        # abaixo de q40 o webp fica borrado: prefere baixar fps antes, exceto no último degrau
        last = k == len(ladder) - 1
        r = search_encode(list(range(100, 4 if last else 39, -1)), one, target["max_bytes"], progress,
                          f"webp {f_out} fps", check)
        if r:
            q, path = r
            best = {"path": path, "fps": f_out, "label": f"webp q{q}"}
            if k:
                best["warning"] = f"fps reduzido para {f_out} para caber em {target['label']}"
            return best
    raise ValueError(f"não coube em {target['label']} nem na qualidade mínima; encurte o trecho")


def encode_webm(seq, fps, work, target, progress, check):
    ladder = fps_ladder(fps)
    for k, f_out in enumerate(ladder):
        vf = (f"fps={f_out}," if f_out != fps else "") + "format=yuva420p"

        def one(crf, vf=vf, f_out=f_out):
            out = work / f"try-{f_out}-{crf}.webm"
            ffmpeg.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-framerate", str(fps),
                "-i", str(seq / "%05d.png"), "-vf", vf,
                "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-crf", str(crf), "-b:v", "0",
                "-deadline", "good", "-cpu-used", "1", "-row-mt", "1", "-threads", "2", "-g", "300",
                "-an", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
                "-metadata:s:v:0", "encoder=", "-y", str(out),
            ])
            return out

        last = k == len(ladder) - 1
        # crf menor = melhor qualidade
        r = search_encode(list(range(8, 64 if last else 46)), one, target["max_bytes"], progress,
                          f"vp9 {f_out} fps", check)
        if r:
            crf, path = r
            best = {"path": path, "fps": f_out, "label": f"vp9 crf{crf}"}
            if k:
                best["warning"] = f"fps reduzido para {f_out} para caber em {target['label']}"
            return best
    raise ValueError(f"não coube em {target['label']} nem na qualidade mínima; encurte o trecho")
