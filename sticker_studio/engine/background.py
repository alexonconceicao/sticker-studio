"""Remoção de fundo com BiRefNet (ONNX), sem depender do rembg.

Modelos baixados na primeira vez para a pasta de dados do app. Usa GPU quando o
onnxruntime instalado oferece (CUDA no Linux, DirectML no Windows); senão CPU.
Na GPU, se existir a versão fp16 do modelo (`<nome>-fp16.onnx`), ela é preferida:
gasta metade da memória de vídeo com máscara praticamente idêntica.
"""
import hashlib
import urllib.request
from pathlib import Path

from sticker_studio.paths import models_dir

MODELS = {
    "birefnet-general": {
        "label": "Alta qualidade (BiRefNet general)",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-epoch_244.onnx",
        "md5": "7a35a0141cbbc80de11d9c9a28f52697",
    },
    "birefnet-general-lite": {
        "label": "Rápido (BiRefNet lite)",
        "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/BiRefNet-general-bb_swin_v1_tiny-epoch_232.onnx",
        "md5": "4fab47adc4ff364be1713e97b7e66334",
    },
}
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
SIZE = 1024


class BackgroundError(RuntimeError):
    pass


def available() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import numpy  # noqa: F401
    except ImportError:
        return False
    return True


def model_path(name: str) -> Path:
    return models_dir() / f"{name}.onnx"


def ensure_model(name: str, progress=None) -> Path:
    path = model_path(name)
    if path.exists():
        return path
    meta = MODELS[name]
    tmp = path.with_suffix(".part")
    md5 = hashlib.md5()
    try:
        with urllib.request.urlopen(meta["url"], timeout=60) as r, open(tmp, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                fh.write(chunk)
                md5.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise BackgroundError(f"falha ao baixar o modelo: {e}") from e
    if md5.hexdigest() != meta["md5"]:
        tmp.unlink(missing_ok=True)
        raise BackgroundError("modelo baixado está corrompido (md5 não confere)")
    tmp.rename(path)
    return path


class Remover:
    def __init__(self, name="birefnet-general", download_progress=None):
        import onnxruntime as ort

        try:
            ort.preload_dlls()  # libs CUDA/cuDNN instaladas via pip, se houver
        except Exception:
            pass
        self.ort = ort
        fp32 = ensure_model(name, download_progress)
        fp16 = fp32.with_name(f"{name}-fp16.onnx")
        avail = ort.get_available_providers()
        self.session = None
        attempts = []
        if "CUDAExecutionProvider" in avail:
            attempts.append((fp16 if fp16.exists() else fp32,
                             [("CUDAExecutionProvider", {"arena_extend_strategy": "kSameAsRequested"})]))
        if "DmlExecutionProvider" in avail:
            attempts.append((fp32, ["DmlExecutionProvider"]))
        attempts.append((fp32, ["CPUExecutionProvider"]))
        errors = []
        for model, providers in attempts:
            try:
                self.session = ort.InferenceSession(str(model), providers=providers)
                self._warmup()
                break
            except Exception as e:  # GPU sem memória etc: tenta o próximo
                errors.append(str(e)[:200])
                self.session = None
        if not self.session:
            raise BackgroundError("não consegui carregar o modelo: " + " | ".join(errors))
        self.device = "GPU" if self.session.get_providers()[0] != "CPUExecutionProvider" else "CPU"

    def _warmup(self):
        import numpy as np

        name = self.session.get_inputs()[0].name
        self.session.run(None, {name: np.zeros((1, 3, SIZE, SIZE), dtype=np.float32)})

    def mask(self, img):
        """Máscara L (0-255) do primeiro plano, no tamanho da imagem."""
        import numpy as np
        from PIL import Image

        im = img.convert("RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS)
        a = np.asarray(im, dtype=np.float64)
        a = a / max(a.max(), 1e-6)
        a = (a - MEAN) / STD
        x = a.transpose(2, 0, 1)[None].astype(np.float32)
        out = self.session.run(None, {self.session.get_inputs()[0].name: x})[0][:, 0]
        pred = 1 / (1 + np.exp(-np.clip(out, -50, 50)))
        pred = (pred - pred.min()) / max(pred.max() - pred.min(), 1e-6)
        m = Image.fromarray((np.squeeze(pred) * 255).astype("uint8"), mode="L")
        return m.resize(img.size, Image.Resampling.LANCZOS)

    def cutout(self, img):
        """Imagem RGBA com o fundo transparente (respeita alpha que já existia)."""
        from PIL import ImageChops

        rgba = img.convert("RGBA")
        m = self.mask(rgba)
        rgba.putalpha(ImageChops.multiply(rgba.getchannel("A"), m))
        return rgba
