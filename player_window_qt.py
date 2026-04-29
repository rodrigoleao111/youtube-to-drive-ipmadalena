"""
player_window_qt.py — Launcher do player Qt (substitui player_window.py).

Mantém a mesma interface pública de PlayerWindow para que app.py não precise
de mudanças estruturais: PlayerWindowQt(master, videos, on_complete, on_cancel).

O player roda em player_subprocess_qt.py (processo separado, Qt + WebEngineView)
para evitar conflito com o event loop do Tkinter/customtkinter.

Protocolo com o subprocess:
  stdin  → pai envia: {"videos": [...]} (primeira linha, logo após Popen)
  stdout ← filho envia: {"type": "segments", "segments": [...]}
                         {"type": "cancelled"}

Dispatch cross-thread
---------------------
_monitor roda em uma Python threading.Thread (sem event loop Qt).
QTimer.singleShot() chamado de lá não dispara — a thread não tem loop.
A solução é _Dispatcher(QObject): criado no thread principal, seus sinais
emitidos de uma thread diferente são entregues ao thread principal via
QueuedConnection automático do Qt.
"""

import json
import os
import subprocess
import sys
import threading

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


# ---------------------------------------------------------------------------
# Dispatcher thread-safe: bridge entre _monitor e o thread principal
# ---------------------------------------------------------------------------

class _Dispatcher(QObject):
    """
    QObject criado no thread principal.
    Quando _monitor emite seus sinais de uma thread de background, o Qt
    usa QueuedConnection automaticamente e entrega os slots no thread principal.
    """
    complete = pyqtSignal(list)
    cancel   = pyqtSignal()


# ---------------------------------------------------------------------------
# Utilitário — comando do subprocess
# ---------------------------------------------------------------------------

def _build_cmd() -> list[str]:
    """Retorna o comando para iniciar o subprocess Qt do player."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--player-mode-qt"]
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "player_subprocess_qt.py",
    )
    return [sys.executable, script]


# ---------------------------------------------------------------------------
# PlayerWindowQt
# ---------------------------------------------------------------------------

class PlayerWindowQt:
    """
    Launcher do player Qt.

    Parâmetros
    ----------
    master      : janela pai (QMainWindow) — mantido por compatibilidade de interface
    videos      : list[{id, title, upload_date}]
    on_complete : callback(segments: list[{id, title, start, end}])
                  start/end → "HH:MM:SS" ou None (vídeo completo)
    on_cancel   : callback()
    """

    def __init__(self, master, videos: list, on_complete, on_cancel):
        self._master      = master
        self._on_complete = on_complete
        self._on_cancel   = on_cancel

        # Dispatcher criado no thread principal — sinais emitidos de _monitor
        # (thread de background) são entregues aqui via QueuedConnection automático.
        self._dispatcher = _Dispatcher()
        self._dispatcher.complete.connect(on_complete)
        self._dispatcher.cancel.connect(on_cancel)

        extra = {}
        if sys.platform == "win32":
            extra["creationflags"] = subprocess.CREATE_NO_WINDOW

        self._proc = subprocess.Popen(
            _build_cmd(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **extra,
        )

        # Envia a lista de vídeos como primeira linha do stdin
        try:
            self._proc.stdin.write(json.dumps({"videos": videos}) + "\n")
            self._proc.stdin.flush()
        except Exception:
            # Erro ainda no __init__ (thread principal) — QTimer.singleShot
            # funciona aqui pois estamos no thread principal com event loop ativo.
            self._proc.terminate()
            QTimer.singleShot(0, on_cancel)
            return

        # Monitoramento em thread daemon: espera o resultado do subprocess
        threading.Thread(target=self._monitor, daemon=True).start()

    def _monitor(self):
        """Thread daemon: lê stdout do subprocess e emite o sinal correto."""
        result = None
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    result = json.loads(line)
                    break          # primeiro JSON válido é o resultado final
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.terminate()
                except Exception:
                    pass

        # Emite o sinal do _Dispatcher — entregue no thread principal via
        # QueuedConnection (automaticamente aplicado em emissões cross-thread).
        if result and result.get("type") == "segments":
            self._dispatcher.complete.emit(result.get("segments", []))
        else:
            self._dispatcher.cancel.emit()
