"""
IPMadalena — Cultos para o Drive
Interface gráfica principal.
"""

import logging
import os
import queue
import socket
import threading
from datetime import datetime

import customtkinter as ctk
from tkcalendar import Calendar

import baixar_audio

# ---------------------------------------------------------------------------
# Instância única — impede abrir dois apps ao mesmo tempo
# ---------------------------------------------------------------------------
_LOCK_PORT = 47892
_lock_socket = None


def _acquire_single_instance():
    """Tenta reservar uma porta TCP local. Retorna True se conseguiu (primeira instância)."""
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
        _lock_socket.listen(1)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Logging em arquivo
# ---------------------------------------------------------------------------

def _setup_file_logging():
    os.makedirs(baixar_audio.LOGS_DIR, exist_ok=True)
    log_file = os.path.join(
        baixar_audio.LOGS_DIR,
        datetime.now().strftime("%d-%m-%Y") + ".log",
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.info("App iniciado.")


def _file_log(msg: str):
    logging.info(msg)


# ---------------------------------------------------------------------------
# Tema
# ---------------------------------------------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Mapeamento de status → progresso da barra de subtarefas (0.0 – 1.0)
SUBTASK_PROGRESS = {
    "Iniciando":                  0.05,
    "Verificando":                0.08,
    "Buscando vídeos":            0.15,
    "Encontrando vídeo":          0.25,
    "Baixando áudio":             0.45,
    "Convertendo para MP3":       0.65,
    "Conectando ao Google Drive": 0.75,
    "Localizando pasta":          0.82,
    "Enviando arquivo":           0.90,
    "Concluído":                  1.00,
}


def _subtask_pct(status_text):
    """Retorna o valor (0–1) da barra de subtarefas para o status recebido."""
    for key, val in SUBTASK_PROGRESS.items():
        if key.lower() in status_text.lower():
            return val
    return None


# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------
class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("IPMadalena — Cultos para o Drive")
        self.geometry("660x660")
        self.resizable(False, False)

        self._queue        = queue.Queue()
        self._running      = False
        self._cancel_event = threading.Event()

        self._build_ui()
        self.after(100, self._process_queue)

        # Inicialização em background: atualizar yt-dlp
        threading.Thread(target=self._init_update_ytdlp, daemon=True).start()

    # -----------------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------------
    def _build_ui(self):
        # ── Cabeçalho ────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="IPMadalena — Cultos para o Drive",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(pady=(24, 4))

        ctk.CTkLabel(
            self,
            text="Baixa o áudio dos cultos do YouTube e envia para o Google Drive",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        ).pack(pady=(0, 16))

        # ── Seleção de data ───────────────────────────────────────────────────
        date_frame = ctk.CTkFrame(self, fg_color="transparent")
        date_frame.pack(fill="x", padx=28)

        ctk.CTkLabel(
            date_frame,
            text="Data do culto:",
            font=ctk.CTkFont(size=13),
        ).pack(side="left")

        self.date_entry = ctk.CTkEntry(
            date_frame,
            placeholder_text="DD/MM/AAAA",
            width=130,
            font=ctk.CTkFont(size=13),
        )
        self.date_entry.pack(side="left", padx=(10, 6))

        ctk.CTkButton(
            date_frame,
            text="📅",
            width=40,
            font=ctk.CTkFont(size=14),
            command=self._open_calendar,
        ).pack(side="left")

        # Botão cancelar — visível apenas durante execução
        self.cancel_btn = ctk.CTkButton(
            date_frame,
            text="Cancelar",
            width=100,
            font=ctk.CTkFont(size=13),
            fg_color="#c0392b",
            hover_color="#922b21",
            command=self._cancel,
        )
        # NÃO empacotado ainda — aparece só quando rodando

        self.run_btn = ctk.CTkButton(
            date_frame,
            text="Processar",
            width=120,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start,
        )
        self.run_btn.pack(side="right")

        # ── Status ────────────────────────────────────────────────────────────
        self.status_label = ctk.CTkLabel(
            self,
            text="Aguardando...",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        )
        self.status_label.pack(fill="x", padx=28, pady=(18, 2))

        # ── Barra de upload (progresso por chunk) ────────────────────────────
        upload_frame = ctk.CTkFrame(self, fg_color="transparent")
        upload_frame.pack(fill="x", padx=28, pady=(0, 6))

        ctk.CTkLabel(
            upload_frame,
            text="Upload:",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            width=52,
            anchor="w",
        ).pack(side="left")

        self.progress_bar = ctk.CTkProgressBar(upload_frame, height=14)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.upload_stats_label = ctk.CTkLabel(
            upload_frame,
            text="",
            font=ctk.CTkFont(family="Consolas", size=11),
            text_color="gray",
            width=210,
            anchor="w",
        )
        self.upload_stats_label.pack(side="left")

        # ── Barra de subtarefas (pipeline) ────────────────────────────────────
        subtask_frame = ctk.CTkFrame(self, fg_color="transparent")
        subtask_frame.pack(fill="x", padx=28, pady=(0, 14))

        ctk.CTkLabel(
            subtask_frame,
            text="Etapas:",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            width=52,
            anchor="w",
        ).pack(side="left")

        self.subtask_bar = ctk.CTkProgressBar(subtask_frame, height=8, width=148)
        self.subtask_bar.pack(side="left")

        # Guarda a cor original das barras e inicia sem marcador visível
        self._bar_orig_color     = self.progress_bar.cget("progress_color")
        self._subtask_orig_color = self.subtask_bar.cget("progress_color")
        self._hide_bars()

        # ── Log ───────────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="Log de execução:",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        ).pack(fill="x", padx=28)

        self.log_box = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=28, pady=(4, 24))
        self.log_box.configure(state="disabled")

    # -----------------------------------------------------------------------
    # Calendário popup
    # -----------------------------------------------------------------------
    def _open_calendar(self):
        popup = ctk.CTkToplevel(self)
        popup.title("Selecionar data")
        popup.geometry("300x300")
        popup.resizable(False, False)
        popup.grab_set()
        popup.focus_force()

        initial = datetime.today()
        typed = self.date_entry.get().strip()
        try:
            initial = datetime.strptime(typed, "%d/%m/%Y")
        except ValueError:
            pass

        cal = Calendar(
            popup,
            selectmode="day",
            date_pattern="dd/MM/yyyy",
            locale="pt_BR",
            year=initial.year,
            month=initial.month,
            day=initial.day,
            background="#2b2b2b",
            foreground="white",
            selectbackground="#1f6aa5",
            headersbackground="#1f1f1f",
            headersforeground="white",
            weekendforeground="#aaaaaa",
            othermonthforeground="#555555",
            bordercolor="#333333",
            font=("Helvetica", 11),
        )
        cal.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        def _confirmar():
            self.date_entry.delete(0, "end")
            self.date_entry.insert(0, cal.get_date())
            popup.destroy()

        ctk.CTkButton(popup, text="Confirmar", command=_confirmar).pack(pady=8)

    # -----------------------------------------------------------------------
    # Fila de mensagens (thread → GUI)
    # -----------------------------------------------------------------------
    def _process_queue(self):
        try:
            while True:
                kind, value = self._queue.get_nowait()

                if kind == "log":
                    self._append_log(value)
                    _file_log(value)

                elif kind == "status":
                    is_done = value == "Concluído!"
                    self.status_label.configure(
                        text=value,
                        text_color="#2fa84f" if is_done else "white",
                    )
                    _file_log(f"[STATUS] {value}")
                    # Atualiza barra de subtarefas
                    pct = _subtask_pct(value)
                    if pct is not None:
                        self.subtask_bar.set(pct)

                elif kind == "progress":
                    self.progress_bar.set(value / 100)

                elif kind == "upload_stats":
                    mb_done, mb_total, rate = value
                    if mb_done == 0 and rate == 0:
                        self.upload_stats_label.configure(text="")
                    elif rate > 0:
                        self.upload_stats_label.configure(
                            text=f"{mb_done:.1f} / {mb_total:.1f} MB  {rate:.2f} MB/s"
                        )
                    else:
                        self.upload_stats_label.configure(
                            text=f"{mb_done:.1f} / {mb_total:.1f} MB"
                        )

                elif kind == "select_videos":
                    self._show_video_selection(*value)

                elif kind == "done":
                    self._on_done(*value)

                elif kind == "cancelled":
                    self._on_cancelled()

                elif kind == "error":
                    self._on_error(value)

                elif kind == "history_warning":
                    self._show_history_warning(*value)

                elif kind == "preflight_error":
                    self._on_preflight_error(value)

        except queue.Empty:
            pass
        finally:
            self.after(100, self._process_queue)

    def _append_log(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{now}]  {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # -----------------------------------------------------------------------
    # Controle das barras de progresso
    # -----------------------------------------------------------------------
    def _hide_bars(self):
        """Remove o marcador visual — torna as barras invisíveis."""
        track = self.progress_bar.cget("fg_color")
        self.progress_bar.configure(progress_color=track)
        self.progress_bar.set(0)
        track = self.subtask_bar.cget("fg_color")
        self.subtask_bar.configure(progress_color=track)
        self.subtask_bar.set(0)
        self.upload_stats_label.configure(text="")

    def _show_bars(self):
        """Restaura as cores originais das barras."""
        self.progress_bar.configure(progress_color=self._bar_orig_color)
        self.subtask_bar.configure(progress_color=self._subtask_orig_color)

    # -----------------------------------------------------------------------
    # Iniciar / Cancelar
    # -----------------------------------------------------------------------
    def _start(self):
        date_str = self.date_entry.get().strip()

        if not date_str:
            self._show_error("Informe a data do culto.")
            return

        try:
            datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            self._show_error("Data inválida.\nUse o formato DD/MM/AAAA  (ex: 19/04/2026).")
            return

        # Limpa UI e reinicia estado
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.progress_bar.set(0)
        self.subtask_bar.set(0)
        self.status_label.configure(text="Verificando...", text_color="white")
        self._cancel_event.clear()

        self._running = True
        self._show_bars()
        self._set_buttons_running(True)

        # Fase 0: verificações pré-execução
        threading.Thread(target=self._worker_preflight, args=(date_str,), daemon=True).start()

    def _cancel(self):
        if not self._running:
            return
        self._cancel_event.set()
        self._append_log("Cancelamento solicitado...")
        self.status_label.configure(text="Cancelando...", text_color="#e0a020")
        self._hide_bars()
        self.cancel_btn.configure(state="disabled")

    def _set_buttons_running(self, running: bool):
        """Alterna entre estado idle e running nos botões."""
        if running:
            self.run_btn.configure(state="disabled", text="Processando...")
            self.cancel_btn.pack(side="right", padx=(0, 8))   # aparece
        else:
            self.cancel_btn.pack_forget()                       # some
            self.run_btn.configure(state="normal", text="Processar")
            self.cancel_btn.configure(state="normal")           # reseta para próxima vez

    # -----------------------------------------------------------------------
    # Workers (threads de background)
    # -----------------------------------------------------------------------

    def _init_update_ytdlp(self):
        """Roda em background ao iniciar o app — atualiza yt-dlp silenciosamente."""
        baixar_audio.update_ytdlp(
            on_log=lambda m: self._queue.put(("log", m))
        )

    def _worker_preflight(self, date_str):
        """
        Fase 0 — verificações antes de começar:
        internet, espaço em disco, limpeza de resíduos, histórico.
        """
        log = lambda m: self._queue.put(("log", m))

        # 1. Internet
        log("Verificando conexão com a internet...")
        if not baixar_audio.check_internet():
            self._queue.put(("preflight_error",
                             "Sem conexão com a internet.\nVerifique sua rede e tente novamente."))
            return

        # 2. Espaço em disco
        log("Verificando espaço em disco...")
        ok, free_mb = baixar_audio.check_disk_space(min_mb=500)
        if not ok:
            self._queue.put(("preflight_error",
                             f"Espaço insuficiente em disco: {free_mb:.0f} MB livres.\n"
                             "São necessários pelo menos 500 MB."))
            return
        log(f"Espaço livre: {free_mb:.0f} MB — OK.")

        # 3. Limpeza de resíduos
        baixar_audio.cleanup_downloads(on_log=log)

        # 4. Histórico — avisa se data já foi processada
        history = baixar_audio.load_history()
        if date_str in history:
            entry = history[date_str]
            videos = entry.get("videos", [])
            processado_em = entry.get("processado_em", "?")
            try:
                dt = datetime.fromisoformat(processado_em)
                processado_em = dt.strftime("%d/%m/%Y às %H:%M")
            except Exception:
                pass
            # Passa para a GUI via fila para exibir popup (não pode abrir popup da thread)
            self._queue.put(("history_warning", (date_str, videos, processado_em)))
            return  # GUI retomará chamando _worker_after_preflight

        self._queue.put(("status", "Buscando vídeos..."))
        threading.Thread(target=self._worker, args=(date_str,), daemon=True).start()

    def _worker(self, date_str):
        """Fase 1 — lista vídeos sem baixar."""
        try:
            videos = baixar_audio.list_videos(
                date_str,
                on_log=lambda m: self._queue.put(("log", m)),
                on_status=lambda m: self._queue.put(("status", m)),
                cancel_event=self._cancel_event,
            )
            self._queue.put(("select_videos", (date_str, videos)))
        except baixar_audio.OperacaoCancelada:
            self._queue.put(("cancelled", None))
        except Exception as e:
            self._queue.put(("error", str(e)))

    def _worker_phase2(self, date_str, selected_videos):
        """Fase 2 — baixa e faz upload dos vídeos selecionados."""
        try:
            files = baixar_audio.download_selected(
                selected_videos,
                on_log=lambda m: self._queue.put(("log", m)),
                on_status=lambda m: self._queue.put(("status", m)),
                cancel_event=self._cancel_event,
            )
            if not files:
                raise RuntimeError("Nenhum arquivo MP3 gerado após o download.")

            baixar_audio.upload_files(
                date_str,
                files,
                on_log=lambda m: self._queue.put(("log", m)),
                on_status=lambda m: self._queue.put(("status", m)),
                on_progress=lambda p: self._queue.put(("progress", p)),
                on_upload_stats=lambda d, t, r: self._queue.put(("upload_stats", (d, t, r))),
                cancel_event=self._cancel_event,
            )
            titles = [v["title"] for v in selected_videos]
            self._queue.put(("done", (date_str, titles)))
        except baixar_audio.OperacaoCancelada:
            self._queue.put(("cancelled", None))
        except Exception as e:
            self._queue.put(("error", str(e)))

    # -----------------------------------------------------------------------
    # Popup de aviso de histórico
    # -----------------------------------------------------------------------
    def _show_history_warning(self, date_str, videos, processado_em):
        """Avisa que a data já foi processada e pergunta se quer continuar."""
        popup = ctk.CTkToplevel(self)
        popup.title("Data já processada")
        popup.geometry("480x280")
        popup.resizable(False, False)
        popup.grab_set()
        popup.focus_force()

        ctk.CTkLabel(
            popup,
            text="⚠  Data já processada",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#e0a020",
        ).pack(pady=(20, 6))

        ctk.CTkLabel(
            popup,
            text=f"A data {date_str} já foi processada em {processado_em}.",
            font=ctk.CTkFont(size=12),
            wraplength=440,
            justify="center",
        ).pack(padx=20)

        if videos:
            nomes = "\n".join(f"  • {v}" for v in videos[:5])
            if len(videos) > 5:
                nomes += f"\n  … e mais {len(videos) - 5} vídeo(s)"
            ctk.CTkLabel(
                popup,
                text=nomes,
                font=ctk.CTkFont(family="Consolas", size=11),
                text_color="gray",
                justify="left",
                anchor="w",
            ).pack(padx=30, pady=(6, 0), fill="x")

        ctk.CTkLabel(
            popup,
            text="Deseja processar novamente?",
            font=ctk.CTkFont(size=12),
            justify="center",
        ).pack(pady=(12, 4))

        btn_frame = ctk.CTkFrame(popup, fg_color="transparent")
        btn_frame.pack(pady=(0, 16))

        def _continuar():
            popup.destroy()
            threading.Thread(target=self._worker, args=(date_str,), daemon=True).start()

        def _cancelar():
            popup.destroy()
            self._on_cancelled()

        ctk.CTkButton(
            btn_frame, text="Sim, continuar", width=140,
            command=_continuar,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            btn_frame, text="Não, cancelar", width=140,
            fg_color="#555", hover_color="#444",
            command=_cancelar,
        ).pack(side="left", padx=8)

    # -----------------------------------------------------------------------
    # Popup de seleção de vídeos
    # -----------------------------------------------------------------------
    def _show_video_selection(self, date_str, videos):
        popup = ctk.CTkToplevel(self)
        popup.title("Vídeos encontrados")
        popup.geometry("560x400")
        popup.resizable(False, False)
        popup.grab_set()
        popup.focus_force()

        ctk.CTkLabel(
            popup,
            text=f"Vídeos encontrados para {date_str}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(pady=(18, 4))

        ctk.CTkLabel(
            popup,
            text="Selecione os vídeos que deseja baixar e enviar para o Drive:",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        ).pack(pady=(0, 12))

        scroll_frame = ctk.CTkScrollableFrame(popup, height=220)
        scroll_frame.pack(fill="x", padx=20, pady=(0, 12))

        check_vars = []
        for video in videos:
            var = ctk.BooleanVar(value=True)
            check_vars.append(var)

            row = ctk.CTkFrame(scroll_frame, fg_color=("gray90", "gray20"), corner_radius=8)
            row.pack(fill="x", pady=4, padx=2)

            ctk.CTkCheckBox(
                row, text="", variable=var,
                width=28, checkbox_width=20, checkbox_height=20,
            ).pack(side="left", padx=(10, 4), pady=10)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, pady=8)

            ctk.CTkLabel(
                info, text=video["title"],
                font=ctk.CTkFont(size=12, weight="bold"),
                anchor="w", wraplength=420,
            ).pack(anchor="w")

            try:
                d = datetime.strptime(video["upload_date"], "%Y%m%d")
                date_fmt = f"Publicado em {d.strftime('%d/%m/%Y')}"
            except Exception:
                date_fmt = video["upload_date"]

            ctk.CTkLabel(
                info, text=date_fmt,
                font=ctk.CTkFont(size=11), text_color="gray", anchor="w",
            ).pack(anchor="w")

        def _prosseguir():
            selected = [v for v, chk in zip(videos, check_vars) if chk.get()]
            popup.destroy()
            if not selected:
                self._on_error("Nenhum vídeo selecionado.")
                return
            self._append_log(f"{len(selected)} vídeo(s) selecionado(s). Iniciando download...")
            threading.Thread(
                target=self._worker_phase2,
                args=(date_str, selected),
                daemon=True,
            ).start()

        ctk.CTkButton(
            popup, text="Prosseguir", width=160,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=_prosseguir,
        ).pack(pady=(0, 16))

    # -----------------------------------------------------------------------
    # Callbacks de finalização
    # -----------------------------------------------------------------------
    def _on_preflight_error(self, msg):
        """Falha nas verificações pré-execução — volta ao estado idle."""
        self._running = False
        self._set_buttons_running(False)
        self._hide_bars()
        self.status_label.configure(text="Erro — veja o log abaixo", text_color="#e05252")
        self._append_log(f"ERRO: {msg}")
        _file_log(f"ERRO pré-execução: {msg}")
        self._show_error(msg)

    def _on_cancelled(self):
        self._running = False
        self._set_buttons_running(False)
        self._hide_bars()
        self.status_label.configure(text="Operação cancelada.", text_color="gray")
        self._append_log("Operação cancelada pelo usuário.")
        _file_log("Operação cancelada pelo usuário.")

    def _on_done(self, date_str=None, video_titles=None):
        self._running = False
        self._set_buttons_running(False)
        self.progress_bar.set(1)
        self.subtask_bar.set(1)

        # Salva histórico
        if date_str and video_titles:
            baixar_audio.save_history(date_str, video_titles)
            _file_log(f"Histórico salvo: {date_str} — {len(video_titles)} vídeo(s).")

        # Notificação desktop
        try:
            from plyer import notification
            n = len(video_titles) if video_titles else 0
            notification.notify(
                title="IPMadalena — Concluído ✓",
                message=f"{n} vídeo(s) enviado(s) ao Drive com sucesso!",
                app_name="IPMadalena",
                timeout=8,
            )
        except Exception:
            pass  # plyer opcional

    def _on_error(self, msg):
        self._running = False
        self._set_buttons_running(False)
        self.status_label.configure(text="Erro — veja o log abaixo", text_color="#e05252")
        self._append_log(f"ERRO: {msg}")
        _file_log(f"ERRO: {msg}")
        self._show_error(msg)

    def _show_error(self, msg):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Erro")
        dialog.geometry("420x200")
        dialog.resizable(False, False)
        dialog.grab_set()
        dialog.focus_force()

        ctk.CTkLabel(
            dialog,
            text="⚠  Ocorreu um erro",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#e05252",
        ).pack(pady=(20, 8))

        ctk.CTkLabel(
            dialog, text=msg,
            font=ctk.CTkFont(size=12),
            wraplength=380, justify="center",
        ).pack(padx=20)

        ctk.CTkButton(dialog, text="OK", width=100, command=dialog.destroy).pack(pady=16)


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not _acquire_single_instance():
        # Já existe uma instância rodando — avisa e sai
        import tkinter as tk
        import tkinter.messagebox as mb
        root = tk.Tk()
        root.withdraw()
        mb.showerror(
            "IPMadalena já está aberto",
            "O aplicativo já está em execução.\nFeche a janela existente antes de abrir novamente.",
        )
        root.destroy()
    else:
        _setup_file_logging()
        app = App()
        app.mainloop()
