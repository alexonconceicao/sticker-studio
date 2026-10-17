"""Copiar figurinha pra área de transferência e abrir o WhatsApp (ZapZap)."""
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData, QUrl
from PySide6.QtGui import QGuiApplication

ZAPZAP_FLATPAK = "com.rtosta.zapzap"


def copy_file(path: Path):
    """Copia o arquivo (não a imagem): colar numa conversa anexa o próprio .webp/.webm."""
    url = QUrl.fromLocalFile(str(path))
    mime = QMimeData()
    mime.setUrls([url])
    # formato que gerenciadores de arquivo do GNOME entendem
    mime.setData("x-special/gnome-copied-files", QByteArray(f"copy\n{url.toString()}".encode()))
    QGuiApplication.clipboard().setMimeData(mime)


def zapzap_command():
    if sys.platform.startswith("linux"):
        if shutil.which("zapzap"):
            return ["zapzap"]
        if shutil.which("flatpak"):
            r = subprocess.run(["flatpak", "info", ZAPZAP_FLATPAK], capture_output=True)
            if r.returncode == 0:
                return ["flatpak", "run", ZAPZAP_FLATPAK]
    return None


def open_zapzap() -> bool:
    """Traz o ZapZap pra frente (ele é instância única: abrir de novo só ativa a janela)."""
    cmd = zapzap_command()
    if not cmd:
        return False
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return True
