"""
Utilitários internos do pacote infrastructure.audio.

Funções privadas — não importar fora do pacote. A regra arquitetural do projeto
impede que `infrastructure/audio` importe de `infrastructure/youtube`, então
parte dessa lógica é duplicada de `infrastructure/youtube/_utils.py`. Se um
dia houver mais subpacotes precisando do mesmo, considere extrair para um
`infrastructure/_common.py` compartilhado.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Optional


# ---------------------------------------------------------------------------
# Localizadores de executáveis ffmpeg / ffprobe
# ---------------------------------------------------------------------------

def ffmpeg_dir() -> Optional[str]:
    """
    Diretório que contém `ffmpeg.exe` e `ffprobe.exe`, ou None se não localizado.

    Prioridade:
      1. ffmpeg/bin/ ao lado do executável (frozen) ou da raiz do projeto (script)
      2. sys._MEIPASS/ffmpeg/bin/ (bundle PyInstaller)
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        # __file__ está em infrastructure/audio/_utils.py — subir 3 níveis para a raiz
        base = os.path.dirname(os.path.abspath(__file__))
        base = os.path.dirname(os.path.dirname(base))

    local = os.path.join(base, "ffmpeg", "bin")
    if os.path.exists(os.path.join(local, "ffmpeg.exe")):
        return local

    if getattr(sys, "frozen", False):
        meipass_loc = os.path.join(sys._MEIPASS, "ffmpeg", "bin")
        if os.path.exists(os.path.join(meipass_loc, "ffmpeg.exe")):
            return meipass_loc

    return None


def ffmpeg_exe() -> str:
    """Retorna o caminho do `ffmpeg.exe` (bundled) ou apenas 'ffmpeg' (PATH)."""
    d = ffmpeg_dir()
    return os.path.join(d, "ffmpeg.exe") if d else "ffmpeg"


def ffprobe_exe() -> str:
    """Retorna o caminho do `ffprobe.exe` (bundled) ou apenas 'ffprobe' (PATH)."""
    d = ffmpeg_dir()
    return os.path.join(d, "ffprobe.exe") if d else "ffprobe"


# ---------------------------------------------------------------------------
# Subprocess com watchdog de cancelamento
# ---------------------------------------------------------------------------

def start_process(cmd: list, cancel_event=None) -> subprocess.Popen:
    """
    Inicia um subprocess capturando stdout (stderr → stdout) e registra um
    watchdog daemon que termina o processo se `cancel_event` for sinalizado.

    Idêntico ao `start_process` de `infrastructure.youtube._utils` — duplicado
    aqui pelo isolamento entre subpacotes de infrastructure (ver docstring do
    módulo).
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    extra: dict = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **extra,
    )

    if cancel_event is not None:
        def _watchdog() -> None:
            while process.poll() is None:
                if cancel_event.wait(timeout=0.5):
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    return
        threading.Thread(target=_watchdog, daemon=True).start()

    return process
