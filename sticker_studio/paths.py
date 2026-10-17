"""Pastas de dados, cache e saída, por sistema operacional."""
import os
import sys
from pathlib import Path

from sticker_studio import APP_ID


def _base(kind: str) -> Path:
    home = Path.home()
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        return root / APP_ID / kind
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / APP_ID / kind
    xdg = {"data": "XDG_DATA_HOME", "cache": "XDG_CACHE_HOME"}[kind]
    default = {"data": home / ".local" / "share", "cache": home / ".cache"}[kind]
    return Path(os.environ.get(xdg, default)) / APP_ID


def data_dir() -> Path:
    d = _base("data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = _base("cache")
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = data_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_output_dir() -> Path:
    home = Path.home()
    for name in ("Pictures", "Imagens", "Images"):
        if (home / name).is_dir():
            return home / name / "Stickers"
    return home / "Stickers"


def resource(name: str) -> Path:
    """Arquivo empacotado junto do código (funciona também dentro do PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "sticker_studio" / name
    return p if p.exists() else Path(__file__).resolve().parent / name
