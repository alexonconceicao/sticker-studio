"""Localiza e executa o ffmpeg/ffprobe (embutido no pacote ou do sistema)."""
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

EXE = ".exe" if sys.platform == "win32" else ""
# não abre janela de console no Windows
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class FFmpegError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def find(tool: str) -> str:
    """Ordem: variável STICKER_STUDIO_FFMPEG_DIR, pasta bin/ do pacote, PATH."""
    candidates = []
    if os.environ.get("STICKER_STUDIO_FFMPEG_DIR"):
        candidates.append(Path(os.environ["STICKER_STUDIO_FFMPEG_DIR"]) / f"{tool}{EXE}")
    roots = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent, Path(__file__).resolve().parents[2]]
    candidates += [r / "bin" / f"{tool}{EXE}" for r in roots if str(r)]
    for c in candidates:
        if c.is_file():
            return str(c)
    found = shutil.which(tool)
    if found:
        return found
    raise FFmpegError(f"{tool} não encontrado. Instale o ffmpeg ou use a versão empacotada.")


def run(args, timeout=None) -> subprocess.CompletedProcess:
    cmd = [find(args[0]), *args[1:]]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace").strip()
        raise FFmpegError(f"{args[0]} falhou: {err[-600:]}")
    return r


def popen(args, **kw) -> subprocess.Popen:
    return subprocess.Popen([find(args[0]), *args[1:]], creationflags=NO_WINDOW, **kw)


@lru_cache(maxsize=None)
def has_filter(name: str) -> bool:
    try:
        out = run(["ffmpeg", "-hide_banner", "-filters"]).stdout.decode()
    except FFmpegError:
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines() if line.strip())
