"""
Utilitários internos da camada de infraestrutura YouTube.

Funções puras de suporte — sem estado global, sem dependências de domínio.
Não importar diretamente fora do pacote infrastructure.youtube.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Optional

from domain.exceptions import OperacaoCancelada


# ---------------------------------------------------------------------------
# Localizadores de executáveis externos
# ---------------------------------------------------------------------------

def ytdlp_exe() -> str:
    """
    Retorna o caminho do executável yt-dlp.

    Prioridade:
      1. Bundled pelo PyInstaller em sys._MEIPASS/yt-dlp.exe (frozen)
      2. "yt-dlp" do PATH (desenvolvimento)
    """
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "yt-dlp.exe")
        if os.path.exists(bundled):
            return bundled
    return "yt-dlp"


def ffmpeg_dir() -> Optional[str]:
    """
    Retorna o DIRETÓRIO que contém ffmpeg.exe, ou None se não localizado.

    Prioridade:
      1. ffmpeg/bin/ ao lado do executável/fonte
      2. sys._MEIPASS/ffmpeg/bin/ (bundle PyInstaller)
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        # Subir dois níveis: infrastructure/youtube/ → raiz do projeto
        base = os.path.dirname(os.path.dirname(base))

    local = os.path.join(base, "ffmpeg", "bin")
    if os.path.exists(os.path.join(local, "ffmpeg.exe")):
        return local

    if getattr(sys, "frozen", False):
        meipass_loc = os.path.join(sys._MEIPASS, "ffmpeg", "bin")
        if os.path.exists(os.path.join(meipass_loc, "ffmpeg.exe")):
            return meipass_loc

    return None


# ---------------------------------------------------------------------------
# Subprocess com watchdog de cancelamento
# ---------------------------------------------------------------------------

def start_process(cmd: list, cancel_event=None) -> subprocess.Popen:
    """
    Inicia um subprocess e registra um watchdog daemon que o termina
    automaticamente se cancel_event for sinalizado.

    Garante:
      - stdout capturado (pipe), stderr redirecionado para stdout
      - encoding UTF-8 com replace de erros
      - PYTHONUTF8=1 e PYTHONIOENCODING=utf-8 injetados no ambiente
      - CREATE_NO_WINDOW no Windows (sem janela preta visível)
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
            # Polla com timeout para não vazar thread quando o subprocess
            # termina normalmente (cancel_event.wait() sem timeout bloquearia
            # para sempre, mesmo após process.poll() retornar código de saída).
            while process.poll() is None:
                if cancel_event.wait(timeout=0.5):
                    try:
                        process.terminate()
                    except Exception:
                        pass
                    return
        threading.Thread(target=_watchdog, daemon=True).start()

    return process


# ---------------------------------------------------------------------------
# Verificação de cancelamento
# ---------------------------------------------------------------------------

def check_cancel(cancel_event) -> None:
    """
    Lança OperacaoCancelada se cancel_event estiver sinalizado.

    Passa silenciosamente se cancel_event for None.
    """
    if cancel_event is not None and cancel_event.is_set():
        raise OperacaoCancelada("Operação cancelada pelo usuário.")
