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
"""

import json
import os
import subprocess
import sys
import threading


def _build_cmd() -> list[str]:
    """Retorna o comando para iniciar o subprocess Qt do player."""
    if getattr(sys, "frozen", False):
        # Exe empacotado: usa --player-mode-qt (tratado em app.py antes de Tk)
        return [sys.executable, "--player-mode-qt"]
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "player_subprocess_qt.py",
    )
    return [sys.executable, script]


class PlayerWindowQt:
    """
    Launcher do player Qt.

    Parâmetros
    ----------
    master      : janela pai CTk (usado para agendar callbacks no thread principal)
    videos      : list[{id, title, upload_date}]
    on_complete : callback(segments: list[{id, title, start, end}])
                  start/end → "HH:MM:SS" ou None (vídeo completo)
    on_cancel   : callback()
    """

    def __init__(self, master, videos: list, on_complete, on_cancel):
        self._master      = master
        self._on_complete = on_complete
        self._on_cancel   = on_cancel

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
            self._proc.terminate()
            master.after(0, on_cancel)
            return

        # Monitoramento em thread daemon: espera o resultado do subprocess
        threading.Thread(target=self._monitor, daemon=True).start()

    def _monitor(self):
        """Thread: lê stdout do subprocess e dispara o callback correto."""
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
            # Garante que o processo encerrou
            try:
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.terminate()
                except Exception:
                    pass

        if result and result.get("type") == "segments":
            segments = result.get("segments", [])
            self._master.after(0, lambda: self._on_complete(segments))
        else:
            self._master.after(0, self._on_cancel)
