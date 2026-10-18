"""Leitura de mídia: probe, importação de figurinhas e decodificação de frames pra prévia."""
import json
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from sticker_studio.engine import ffmpeg


@dataclass
class MediaInfo:
    path: Path
    width: int  # já considerando rotação
    height: int
    duration: float
    fps: float
    hdr: bool
    alpha: bool  # VP9 com transparência (precisa do decoder libvpx)
    name: str = ""
    sticker: bool = False

    def decoder_args(self):
        return ["-c:v", "libvpx-vp9"] if self.alpha else []


def probe(path: Path) -> MediaInfo:
    r = ffmpeg.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    data = json.loads(r.stdout)
    v = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if not v:
        raise ffmpeg.FFmpegError("o arquivo não tem trilha de vídeo")
    num, den = (v.get("avg_frame_rate") or "0/0").split("/")
    fps = float(num) / float(den) if float(den or 0) else 0
    if not fps or fps > 240:
        num, den = (v.get("r_frame_rate") or "30/1").split("/")
        fps = float(num) / float(den) if float(den or 0) else 30.0
    dur = float(v.get("duration") or data["format"].get("duration") or 0)
    w, h = int(v["width"]), int(v["height"])
    rot = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    rot = rot or int((v.get("tags") or {}).get("rotate", 0))
    if abs(rot) % 180 == 90:
        w, h = h, w
    tags = {k.lower(): val for k, val in (v.get("tags") or {}).items()}
    return MediaInfo(
        path=Path(path), width=w, height=h, duration=dur, fps=round(fps, 3),
        hdr=v.get("color_transfer") in ("smpte2084", "arib-std-b67"),
        alpha=tags.get("alpha_mode") == "1", name=Path(path).name,
    )


def is_webp(path: Path) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(12)
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def import_sticker(src: Path, work_dir: Path) -> MediaInfo:
    """Figurinha (.webp animado/estático ou .webm) vira um .webm VP9 sem perdas com alpha.

    Esse arquivo é usado como fonte normal no editor, preservando transparência.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / f"{uuid.uuid4().hex[:12]}.webm"
    enc = ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-lossless", "1", "-row-mt", "1",
           "-an", "-map_metadata", "-1", "-y", str(out)]
    if is_webp(src):
        from PIL import Image, ImageSequence

        tmp = work_dir / f"import-{uuid.uuid4().hex[:8]}"
        tmp.mkdir()
        try:
            im = Image.open(src)
            lines = []
            name = ""
            for i, fr in enumerate(ImageSequence.Iterator(im)):
                name = f"{i:05d}.png"
                fr.convert("RGBA").save(tmp / name, compress_level=1)
                dur = max(10, fr.info.get("duration") or im.info.get("duration") or 33) / 1000
                lines += [f"file '{name}'", f"duration {dur:.3f}"]
            lines.append(f"file '{name}'")  # o concat exige repetir o último
            (tmp / "list.txt").write_text("\n".join(lines) + "\n")
            ffmpeg.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(tmp / "list.txt"), "-vf", "fps=30,format=rgba", *enc])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    else:
        first = probe(src)
        ffmpeg.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *first.decoder_args(), "-i", str(src),
                    "-vf", "format=rgba", *enc])
    info = probe(out)
    info.name = src.name
    info.sticker = True
    return info


def open_media(src: Path, work_dir: Path) -> MediaInfo:
    """Abre vídeo ou figurinha. webp sempre é importado; webm com alpha é tratado como figurinha."""
    if is_webp(src):
        return import_sticker(src, work_dir)
    info = probe(src)
    if info.alpha:
        info.sticker = True
    return info


def preview_size(info: MediaInfo, max_side: int):
    s = min(1.0, max_side / max(info.width, info.height))
    return max(2, int(info.width * s) // 2 * 2), max(2, int(info.height * s) // 2 * 2)


TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")


def _preview_filters(info: MediaInfo, w: int, h: int, pix: str, fps: float | None = None) -> str:
    vf = [f"fps={fps}"] if fps else []
    vf.append(f"scale={w}:{h}:flags=bicubic")
    if info.hdr and ffmpeg.has_filter("zscale"):
        vf.append(TONEMAP)  # depois de reduzir: muito mais leve que em 4K
    vf.append(f"format={pix}")
    return ",".join(vf)


def frame_at(info: MediaInfo, t: float, max_side=720):
    """Um frame no tempo t. Retorna (bytes, w, h, bytes_por_pixel) ou None."""
    w, h = preview_size(info, max_side)
    bpp = 4 if info.alpha else 3
    t = max(0.0, min(t, max(0.0, info.duration - 0.02)))
    try:
        r = ffmpeg.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", *info.decoder_args(),
            "-i", str(info.path), "-frames:v", "1", "-an",
            "-vf", _preview_filters(info, w, h, "rgba" if bpp == 4 else "rgb24"), "-f", "rawvideo", "-",
        ], timeout=30)
    except (ffmpeg.FFmpegError, subprocess.TimeoutExpired):
        return None
    if len(r.stdout) < w * h * bpp:
        return None
    return r.stdout[: w * h * bpp], w, h, bpp


def iter_segment(info: MediaInfo, start: float, end: float, fps: float, max_side=480):
    """Gera frames (bytes, w, h, bytes_por_pixel) do trecho, na taxa fps. Pra prévia em tempo real."""
    w, h = preview_size(info, max_side)
    bpp = 4 if info.alpha else 3
    size = w * h * bpp
    proc = ffmpeg.popen([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{max(0.05, end - start):.3f}",
        *info.decoder_args(), "-i", str(info.path), "-an",
        "-vf", _preview_filters(info, w, h, "rgba" if bpp == 4 else "rgb24", fps), "-f", "rawvideo", "-",
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while True:
            buf = proc.stdout.read(size)
            if not buf or len(buf) < size:
                break
            yield buf, w, h, bpp
    finally:
        proc.kill()
        proc.wait()
