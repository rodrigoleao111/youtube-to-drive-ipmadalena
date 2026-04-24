"""
player_window.py — Painel de controles de seleção de trecho.

A janela de controles (CTkToplevel) é posicionada como uma barra horizontal
diretamente abaixo da janela do player, formando uma unidade visual integrada.

O player corre em player_subprocess.py para evitar conflito de thread com o
Tkinter (webview.start() exige a thread principal do processo).
"""

import json
import os
import queue
import subprocess
import sys
import threading

import customtkinter as ctk


# ---------------------------------------------------------------------------
# Utilitários de tempo
# ---------------------------------------------------------------------------

def _seconds_to_hms(seconds: float) -> str:
    """1234.0 → '00:20:34'"""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _hms_to_seconds(hms: str):
    """'00:20:34' → 1234.0 — retorna None se inválido."""
    parts = hms.strip().split(":")
    if len(parts) != 3:
        return None
    try:
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        if not (0 <= m < 60 and 0 <= s < 60):
            return None
        return float(h * 3600 + m * 60 + s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Resolução do comando para o subprocesso
# ---------------------------------------------------------------------------

def _build_player_cmd(video_id: str, x: int, y: int, w: int, h: int) -> list:
    """
    Retorna os argumentos para o subprocess do player.
    - Frozen: IPMadalena.exe --player-mode <args>
    - Script: python player_subprocess.py <args>
    """
    pos_args = [video_id, str(x), str(y), str(w), str(h)]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--player-mode"] + pos_args
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "player_subprocess.py",
    )
    return [sys.executable, script] + pos_args


# ---------------------------------------------------------------------------
# PlayerWindow
# ---------------------------------------------------------------------------

class PlayerWindow(ctk.CTkToplevel):
    """
    Barra de controles horizontal posicionada abaixo do player YouTube.

    Parâmetros
    ----------
    master      : janela pai (App)
    videos      : list[{id, title, upload_date}]
    on_complete : callback(segments: list[{id, title, start, end}])
                  start/end → "HH:MM:SS" ou None (vídeo completo)
    on_cancel   : callback()
    """

    # Dimensões do player (subprocesso)
    _PLAY_W = 860
    _PLAY_H = 480

    # Dimensões do painel de controles (esta janela)
    _CTRL_W = 860
    _CTRL_H = 118

    def __init__(self, master, videos: list, on_complete, on_cancel):
        super().__init__(master)
        self.title("Seleção de Trecho")
        self.geometry(f"{self._CTRL_W}x{self._CTRL_H}")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._videos      = videos
        self._on_complete = on_complete
        self._on_cancel   = on_cancel
        self._idx         = 0
        self._segments    = []
        self._proc        = None
        self._ev_queue    = queue.Queue()

        self._build_ui()
        self._load_video(0)
        self.after(100, self._poll_queue)

    # -----------------------------------------------------------------------
    # Layout horizontal compacto
    # -----------------------------------------------------------------------

    def _build_ui(self):
        # ── Linha 1: título + contador ─────────────────────────────────────
        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.pack(fill="x", padx=16, pady=(8, 0))

        self._title_lbl = ctk.CTkLabel(
            row1,
            text="",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self._title_lbl.pack(side="left", fill="x", expand=True)

        self._counter_lbl = ctk.CTkLabel(
            row1,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="e",
        )
        self._counter_lbl.pack(side="right")

        # ── Separador ──────────────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color=("gray78", "gray28")).pack(
            fill="x", padx=10, pady=(4, 0)
        )

        # ── Linha 2: controles de tempo + botões ───────────────────────────
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=(6, 0))

        # -- Início --
        ctk.CTkLabel(
            row2, text="Início:",
            font=ctk.CTkFont(size=12), width=50, anchor="e",
        ).pack(side="left")

        self._start_var = ctk.StringVar(value="00:00:00")
        self._start_var.trace_add("write", lambda *_: self._update_duration())
        ctk.CTkEntry(
            row2, textvariable=self._start_var,
            width=88, font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(4, 4))

        self._btn_start = ctk.CTkButton(
            row2, text="◀", width=34, state="disabled",
            command=lambda: self._request_mark("start"),
        )
        self._btn_start.pack(side="left", padx=(0, 14))

        # -- Fim --
        ctk.CTkLabel(
            row2, text="Fim:",
            font=ctk.CTkFont(size=12), width=36, anchor="e",
        ).pack(side="left")

        self._end_var = ctk.StringVar(value="00:00:00")
        self._end_var.trace_add("write", lambda *_: self._update_duration())
        ctk.CTkEntry(
            row2, textvariable=self._end_var,
            width=88, font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(4, 4))

        self._btn_end = ctk.CTkButton(
            row2, text="◀", width=34, state="disabled",
            command=lambda: self._request_mark("end"),
        )
        self._btn_end.pack(side="left", padx=(0, 14))

        # -- Duração --
        ctk.CTkLabel(
            row2, text="Dur:",
            font=ctk.CTkFont(size=11), text_color="gray",
        ).pack(side="left")

        self._dur_lbl = ctk.CTkLabel(
            row2, text="--:--:--",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._dur_lbl.pack(side="left", padx=(4, 0))

        # -- Botões de ação (alinhados à direita) --
        ctk.CTkButton(
            row2, text="✕",
            width=34,
            fg_color="transparent",
            border_width=1,
            text_color=("gray40", "gray70"),
            hover_color=("gray85", "gray20"),
            command=self._cancel,
        ).pack(side="right")

        self._full_btn = ctk.CTkButton(
            row2, text="Usar completo",
            width=118,
            fg_color=("gray75", "gray30"),
            hover_color=("gray65", "gray25"),
            state="disabled",
            command=self._use_full,
        )
        self._full_btn.pack(side="right", padx=(0, 6))

        self._confirm_btn = ctk.CTkButton(
            row2, text="Confirmar trecho →",
            width=150,
            font=ctk.CTkFont(size=12, weight="bold"),
            state="disabled",
            command=self._confirm,
        )
        self._confirm_btn.pack(side="right", padx=(0, 6))

        # ── Linha 3: status / erro (compartilhado) ─────────────────────────
        self._status_lbl = ctk.CTkLabel(
            self,
            text="⏳ Abrindo player...",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            anchor="w",
        )
        self._status_lbl.pack(anchor="w", padx=16, pady=(3, 0))

    # -----------------------------------------------------------------------
    # Subprocesso do player
    # -----------------------------------------------------------------------

    def _calc_positions(self):
        """Calcula posições: player em cima, controles colados abaixo."""
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        # Altura total visível (desconta taskbar ~40px)
        total_h = self._PLAY_H + self._CTRL_H
        base_x  = max(0, (sw - self._PLAY_W) // 2)
        base_y  = max(0, (sh - 40 - total_h) // 2)
        ctrl_y  = base_y + self._PLAY_H
        self.geometry(f"{self._CTRL_W}x{self._CTRL_H}+{base_x}+{ctrl_y}")
        return base_x, base_y

    def _start_player(self, video_id: str):
        """Inicia ou recarrega o player via subprocesso."""
        px, py = self._calc_positions()

        if self._proc and self._proc.poll() is None:
            # Processo vivo — navega para novo vídeo via stdin
            try:
                self._send_cmd({"cmd": "load", "video_id": video_id})
                return
            except Exception:
                self._kill_player()  # fallback: reinicia

        self._kill_player()

        cmd = _build_player_cmd(video_id, px, py, self._PLAY_W, self._PLAY_H)
        extra = {}
        if sys.platform == "win32":
            extra["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                **extra,
            )
        except Exception as e:
            self._set_status(f"⚠ Erro ao abrir player: {e}", error=True)
            self._confirm_btn.configure(state="normal")
            self._full_btn.configure(state="normal")
            return

        threading.Thread(
            target=self._read_player_stdout,
            args=(self._proc,),
            daemon=True,
        ).start()

    def _kill_player(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._send_cmd({"cmd": "quit"})
            except Exception:
                pass
            try:
                self._proc.terminate()
            except Exception:
                pass
        self._proc = None

    def _send_cmd(self, obj: dict):
        """Envia um comando JSON ao subprocess via stdin."""
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(json.dumps(obj) + "\n")
            self._proc.stdin.flush()

    def _read_player_stdout(self, proc):
        """Thread: lê JSON do stdout do subprocesso → fila de eventos."""
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    self._ev_queue.put(json.loads(line))
                except Exception:
                    pass
        except Exception:
            pass
        self._ev_queue.put({"type": "proc_ended"})

    def _poll_queue(self):
        """Tick Tk: despacha eventos do player para a UI (thread-safe)."""
        try:
            while True:
                ev = self._ev_queue.get_nowait()
                self._handle_player_event(ev)
        except queue.Empty:
            pass
        try:
            self.after(100, self._poll_queue)
        except Exception:
            pass

    def _handle_player_event(self, ev: dict):
        kind = ev.get("type")

        if kind == "ready":
            self._set_status("✓ Player pronto — assista e use ◀ para marcar os tempos.",
                             color="#2fa84f")
            self._btn_start.configure(state="normal")
            self._btn_end.configure(state="normal")
            self._confirm_btn.configure(state="normal")
            self._full_btn.configure(state="normal")

        elif kind == "mark":
            seconds = ev.get("seconds", 0.0)
            target  = ev.get("target", "")
            hms = _seconds_to_hms(seconds)
            if target == "start":
                self._start_var.set(hms)
            else:
                self._end_var.set(hms)

        elif kind == "error":
            self._set_status("⚠ Erro no player — insira os tempos manualmente.",
                             color="#e0a020")
            self._confirm_btn.configure(state="normal")
            self._full_btn.configure(state="normal")

        elif kind in ("closed", "proc_ended"):
            self._set_status("⚠ Player fechado — insira os tempos manualmente.",
                             color="#e0a020")
            self._confirm_btn.configure(state="normal")
            self._full_btn.configure(state="normal")

    # -----------------------------------------------------------------------
    # Carregamento de vídeo
    # -----------------------------------------------------------------------

    def _load_video(self, idx: int):
        video = self._videos[idx]
        total = len(self._videos)
        self._title_lbl.configure(text=video["title"])
        self._counter_lbl.configure(text=f"Vídeo {idx + 1} de {total}")
        self._set_status("⏳ Abrindo player...", color="gray")
        self._start_var.set("00:00:00")
        self._end_var.set("00:00:00")
        self._btn_start.configure(state="disabled")
        self._btn_end.configure(state="disabled")
        self._confirm_btn.configure(state="disabled")
        self._full_btn.configure(state="disabled")
        self._update_duration()
        self._start_player(video["id"])

    # -----------------------------------------------------------------------
    # Ações do usuário
    # -----------------------------------------------------------------------

    def _request_mark(self, target: str):
        """Captura o tempo atual do player via evaluate_js no subprocess."""
        if self._proc and self._proc.poll() is None:
            try:
                self._send_cmd({"cmd": "get_time", "target": target})
            except Exception:
                pass

    def _set_status(self, text: str, color: str = "gray", error: bool = False):
        if error:
            color = "#e05252"
        self._status_lbl.configure(text=text, text_color=color)

    def _update_duration(self):
        start_s = _hms_to_seconds(self._start_var.get())
        end_s   = _hms_to_seconds(self._end_var.get())
        if start_s is not None and end_s is not None and end_s > start_s:
            self._dur_lbl.configure(text=_seconds_to_hms(end_s - start_s))
        else:
            self._dur_lbl.configure(text="--:--:--")

    def _confirm(self):
        start_str = self._start_var.get().strip()
        end_str   = self._end_var.get().strip()
        start_s   = _hms_to_seconds(start_str)
        end_s     = _hms_to_seconds(end_str)
        if start_s is None or end_s is None:
            self._set_status("⚠ Tempo inválido — use HH:MM:SS.", error=True)
            return
        if end_s <= start_s:
            self._set_status("⚠ O tempo de fim deve ser maior que o início.", error=True)
            return
        if start_s == 0 and end_s == 0:
            self._set_status(
                "⚠ Informe o trecho ou clique em 'Usar completo'.", error=True
            )
            return
        self._save_segment(start_str, end_str)
        self._advance()

    def _use_full(self):
        self._save_segment(None, None)
        self._advance()

    def _save_segment(self, start, end):
        v = self._videos[self._idx]
        self._segments.append({
            "id":    v["id"],
            "title": v["title"],
            "start": start,
            "end":   end,
        })

    def _advance(self):
        self._idx += 1
        if self._idx >= len(self._videos):
            self._finish()
        else:
            self._load_video(self._idx)

    def _finish(self):
        self._kill_player()
        self.grab_release()
        self.destroy()
        self._on_complete(self._segments)

    def _cancel(self):
        self._kill_player()
        self.grab_release()
        self.destroy()
        self._on_cancel()
