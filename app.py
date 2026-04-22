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
from setup_wizard import SetupWizard

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



# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------
class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("IPMadalena — Cultos para o Drive")
        self.geometry("660x700")
        self.resizable(False, False)

        self._queue        = queue.Queue()
        self._running      = False
        self._converting   = False
        self._cancel_event = threading.Event()

        self._build_ui()
        self.after(100, self._process_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Inicialização em background: atualizar yt-dlp
        threading.Thread(target=self._init_update_ytdlp, daemon=True).start()

        # Primeira execução: abre wizard de configuração se credentials ausentes
        if not os.path.exists(baixar_audio.CREDENTIALS_FILE):
            self.withdraw()
            SetupWizard(self, on_complete=self._on_wizard_complete)
        else:
            self._check_auth_visibility()

    # -----------------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------------
    def _build_ui(self):
        PAD = 28
        LABEL_W = 78   # largura fixa dos rótulos das barras

        # ── Cabeçalho ────────────────────────────────────────────────────────
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", padx=PAD, pady=(24, 0))

        ctk.CTkLabel(
            header_frame,
            text="IPMadalena — Cultos para o Drive",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left")

        ctk.CTkButton(
            header_frame,
            text="⚙",
            width=34,
            height=34,
            font=ctk.CTkFont(size=16),
            fg_color="transparent",
            hover_color=("#d0d0d0", "#444444"),
            command=self._open_settings,
        ).pack(side="right")

        ctk.CTkLabel(
            self,
            text="Baixa o áudio dos cultos do YouTube e envia para o Google Drive",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        ).pack(fill="x", padx=PAD, pady=(4, 12))

        # ── Banner de autorização Google Drive ────────────────────────────────
        self._auth_banner = ctk.CTkFrame(self, fg_color="#5a3500", corner_radius=8)
        # gerenciado por _check_auth_visibility

        ctk.CTkLabel(
            self._auth_banner,
            text="⚠  Google Drive não autorizado",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#f0a830",
        ).pack(side="left", padx=(14, 8), pady=10)

        self._auth_btn = ctk.CTkButton(
            self._auth_banner,
            text="Autorizar",
            width=100,
            font=ctk.CTkFont(size=12),
            fg_color="#d4820a",
            hover_color="#b36b08",
            command=self._start_auth,
        )
        self._auth_btn.pack(side="right", padx=14, pady=8)

        # ── Seleção de data ───────────────────────────────────────────────────
        date_frame = ctk.CTkFrame(self, fg_color=("gray90", "gray16"), corner_radius=10)
        date_frame.pack(fill="x", padx=PAD, pady=(0, 0))

        ctk.CTkLabel(
            date_frame,
            text="Data do culto:",
            font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=(16, 0), pady=14)

        self.date_entry = ctk.CTkEntry(
            date_frame,
            placeholder_text="DD/MM/AAAA",
            width=130,
            font=ctk.CTkFont(size=13),
        )
        self.date_entry.pack(side="left", padx=(10, 6), pady=14)

        ctk.CTkButton(
            date_frame,
            text="📅",
            width=40,
            font=ctk.CTkFont(size=14),
            fg_color="transparent",
            hover_color=("#d0d0d0", "#444444"),
            command=self._open_calendar,
        ).pack(side="left", pady=14)

        self.run_btn = ctk.CTkButton(
            date_frame,
            text="Processar",
            width=120,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._start,
        )
        self.run_btn.pack(side="right", padx=(0, 16), pady=14)

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
        # NÃO empacotado ainda

        # ── Separador ─────────────────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color=("gray78", "gray28")).pack(
            fill="x", padx=PAD, pady=(16, 0)
        )

        # ── Status ────────────────────────────────────────────────────────────
        status_row = ctk.CTkFrame(self, fg_color="transparent")
        status_row.pack(fill="x", padx=PAD, pady=(12, 8))

        self._status_dot = ctk.CTkLabel(
            status_row,
            text="●",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            width=16,
        )
        self._status_dot.pack(side="left", padx=(0, 6))

        self.status_label = ctk.CTkLabel(
            status_row,
            text="Pronto",
            font=ctk.CTkFont(size=13),
            text_color="gray",
            anchor="w",
        )
        self.status_label.pack(side="left", fill="x", expand=True)

        # ── Seção de progresso (Download / Conversão / Upload) ────────────────
        # Pack/unpack como bloco — oculta quando idle
        self._progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        # empacotado em _show_bars(), removido em _hide_bars()

        def _bar_row(parent, label):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=(0, 7))
            ctk.CTkLabel(
                row,
                text=label,
                font=ctk.CTkFont(size=11),
                text_color=("gray50", "gray60"),
                width=LABEL_W,
                anchor="w",
            ).pack(side="left")
            bar = ctk.CTkProgressBar(row, height=12)
            bar.pack(side="left", fill="x", expand=True, padx=(0, 8))
            stats = ctk.CTkLabel(
                row,
                text="",
                font=ctk.CTkFont(family="Consolas", size=11),
                text_color="gray",
                width=190,
                anchor="w",
            )
            stats.pack(side="left")
            return bar, stats

        self.download_bar,  self.download_stats  = _bar_row(self._progress_frame, "Download")
        self.convert_bar,   self.convert_stats   = _bar_row(self._progress_frame, "Conversão")
        self.progress_bar,  self.upload_stats_label = _bar_row(self._progress_frame, "Upload")

        # ── Log ───────────────────────────────────────────────────────────────
        self._log_label = ctk.CTkLabel(
            self,
            text="Log de execução:",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        )
        self._log_label.pack(fill="x", padx=PAD)

        self.log_box = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
        )
        self.log_box.pack(fill="both", expand=True, padx=PAD, pady=(4, 24))
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
                    state   = "done" if is_done else "running"
                    self._set_status(value, state)
                    _file_log(f"[STATUS] {value}")
                    # Controla animação da barra de conversão
                    lo = value.lower()
                    if "convertendo" in lo:
                        if not self._converting:
                            self._converting = True
                            self.convert_stats.configure(text="aguardando...")
                            self._animate_conversion()
                    elif self._converting:
                        # passou da fase de conversão
                        self._converting = False
                        self.convert_bar.set(1.0)
                        self.convert_stats.configure(text="")

                elif kind == "download_progress":
                    self.download_bar.set(value)
                    pct_txt = f"{value * 100:.0f}%"
                    self.download_stats.configure(text=pct_txt)

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

                elif kind == "auth_done":
                    self._auth_banner.pack_forget()
                    self._append_log("Google Drive autorizado com sucesso!")
                    _file_log("Google Drive autorizado com sucesso.")

                elif kind == "auth_error":
                    self._auth_btn.configure(state="normal", text="Autorizar")
                    self._append_log(f"Erro na autorização: {value}")
                    _file_log(f"Erro na autorização Drive: {value}")

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
    # Status dot + helper
    # -----------------------------------------------------------------------
    def _set_status(self, text, state="running"):
        """Atualiza texto e cor do status + dot de indicação."""
        _colors = {
            "idle":    ("gray",    "gray"),
            "running": ("white",   "#4a9edd"),
            "done":    ("#2fa84f", "#2fa84f"),
            "error":   ("#e05252", "#e05252"),
        }
        text_color, dot_color = _colors.get(state, ("white", "#4a9edd"))
        self.status_label.configure(text=text, text_color=text_color)
        self._status_dot.configure(text_color=dot_color)

    # -----------------------------------------------------------------------
    # Controle das barras de progresso
    # -----------------------------------------------------------------------
    def _hide_bars(self):
        self._converting = False
        self._progress_frame.pack_forget()
        self.download_bar.set(0)
        self.convert_bar.set(0)
        self.progress_bar.set(0)
        self.download_stats.configure(text="")
        self.convert_stats.configure(text="")
        self.upload_stats_label.configure(text="")

    def _show_bars(self):
        self.download_bar.set(0)
        self.convert_bar.set(0)
        self.progress_bar.set(0)
        self.download_stats.configure(text="")
        self.convert_stats.configure(text="")
        self.upload_stats_label.configure(text="")
        self._progress_frame.pack(fill="x", padx=28, pady=(0, 14),
                                  before=self._log_label)

    # -----------------------------------------------------------------------
    # Animação da barra de conversão
    # -----------------------------------------------------------------------
    def _animate_conversion(self):
        if not self._converting:
            return
        current = self.convert_bar.get()
        # Avança até 90%; os 10% finais preenchemos em _on_done
        nxt = min(current + 0.018, 0.90)
        self.convert_bar.set(nxt)
        self.after(160, self._animate_conversion)

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

        if not baixar_audio.check_auth_status():
            self._show_error(
                "Google Drive não autorizado.\n\n"
                "Clique em 'Autorizar' no banner acima ou acesse ⚙ Configurações."
            )
            return

        # Limpa UI e reinicia estado
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self._set_status("Verificando...", "running")
        self._cancel_event.clear()
        self._converting = False

        self._running = True
        self._show_bars()
        self._set_buttons_running(True)

        # Fase 0: verificações pré-execução
        threading.Thread(target=self._worker_preflight, args=(date_str,), daemon=True).start()

    def _cancel(self):
        if not self._running:
            return
        self._cancel_event.set()
        self._converting = False
        self._append_log("Cancelamento solicitado...")
        self._set_status("Cancelando...", "running")
        self._hide_bars()
        self.cancel_btn.configure(state="disabled")

    def _set_buttons_running(self, running: bool):
        """Alterna entre estado idle e running nos botões."""
        if running:
            self.run_btn.configure(state="disabled", text="Processando...")
            self.cancel_btn.pack(side="right", padx=(0, 16), before=self.run_btn)
        else:
            self.cancel_btn.pack_forget()
            self.run_btn.configure(state="normal", text="Processar")
            self.cancel_btn.configure(state="normal")

    # -----------------------------------------------------------------------
    # Workers (threads de background)
    # -----------------------------------------------------------------------

    def _on_close(self):
        self.destroy()

    def _on_wizard_complete(self):
        """Chamado pelo SetupWizard ao concluir — exibe a janela principal."""
        self._check_auth_visibility()
        self.deiconify()

    # -----------------------------------------------------------------------
    # Autorização Google Drive
    # -----------------------------------------------------------------------

    def _open_settings(self):
        win = SettingsWindow(self)
        win.grab_set()
        win.focus_force()
        # Quando a janela de configurações fechar, reavalia o banner de auth
        win.bind("<Destroy>", lambda _: self.after(100, self._check_auth_visibility))

    def _check_auth_visibility(self):
        """Exibe o banner laranja se o Drive não estiver autorizado."""
        if baixar_audio.check_auth_status():
            self._auth_banner.pack_forget()
        else:
            self._auth_banner.pack(fill="x", padx=28, pady=(0, 12))

    def _start_auth(self):
        self._auth_btn.configure(state="disabled", text="Autorizando...")
        self._append_log("Abrindo navegador para autorização do Google Drive...")
        _file_log("Iniciando fluxo OAuth do Drive.")
        threading.Thread(target=self._run_auth_worker, daemon=True).start()

    def _run_auth_worker(self):
        try:
            baixar_audio.run_auth(on_log=lambda m: self._queue.put(("log", m)))
            self._queue.put(("auth_done", None))
        except Exception as e:
            self._queue.put(("auth_error", str(e)))

    # -----------------------------------------------------------------------
    # yt-dlp update
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
                on_download_progress=lambda p: self._queue.put(("download_progress", p)),
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

        def _cancelar():
            popup.destroy()
            self._on_cancelled()

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

        popup.protocol("WM_DELETE_WINDOW", _cancelar)

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
        self._set_status("Erro — veja o log abaixo", "error")
        self._append_log(f"ERRO: {msg}")
        _file_log(f"ERRO pré-execução: {msg}")
        self._show_error(msg)

    def _on_cancelled(self):
        self._running = False
        self._set_buttons_running(False)
        self._hide_bars()
        self._set_status("Operação cancelada.", "idle")
        self._append_log("Operação cancelada pelo usuário.")
        _file_log("Operação cancelada pelo usuário.")

    def _on_done(self, date_str=None, video_titles=None):
        self._running = False
        self._converting = False
        self._set_buttons_running(False)
        self.download_bar.set(1)
        self.convert_bar.set(1)
        self.progress_bar.set(1)
        self.convert_stats.configure(text="")

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
        self._converting = False
        self._set_buttons_running(False)
        self._set_status("Erro — veja o log abaixo", "error")
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
# Janela de configurações
# ---------------------------------------------------------------------------
class SettingsWindow(ctk.CTkToplevel):

    def __init__(self, master):
        super().__init__(master)
        self.title("Configurações")
        self.geometry("540x490")
        self.resizable(False, False)

        self._auth_running = False
        self._build_ui()

    # -----------------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------------
    def _build_ui(self):
        # ── Título ───────────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="Configurações",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=(22, 16))

        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=28)

        # ── Seção: Google Drive ───────────────────────────────────────────────
        self._section_label(content, "Google Drive")

        auth_row = ctk.CTkFrame(content, fg_color=("gray92", "gray17"), corner_radius=8)
        auth_row.pack(fill="x", pady=(4, 12))

        self._auth_status_label = ctk.CTkLabel(
            auth_row,
            text="",
            font=ctk.CTkFont(size=12),
            anchor="w",
        )
        self._auth_status_label.pack(side="left", padx=14, pady=12)

        self._auth_action_btn = ctk.CTkButton(
            auth_row,
            text="",
            width=110,
            font=ctk.CTkFont(size=12),
            command=self._toggle_auth,
        )
        self._auth_action_btn.pack(side="right", padx=12, pady=8)

        self._refresh_auth_status()

        # ── Seção: Canal do YouTube ───────────────────────────────────────────
        self._section_label(content, "Canal do YouTube")

        cfg = baixar_audio.load_config()

        self._channel_entry = ctk.CTkEntry(
            content,
            font=ctk.CTkFont(size=12),
            height=36,
        )
        self._channel_entry.insert(0, cfg["channel_url"])
        self._channel_entry.pack(fill="x", pady=(4, 2))

        ctk.CTkLabel(
            content,
            text="Ex: https://www.youtube.com/@SeuCanal/streams",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
        ).pack(fill="x", pady=(0, 12))

        # ── Seção: Pasta do Google Drive ──────────────────────────────────────
        self._section_label(content, "Pasta do Google Drive")

        self._folder_entry = ctk.CTkEntry(
            content,
            font=ctk.CTkFont(size=12),
            height=36,
        )
        self._folder_entry.insert(0, cfg["drive_folder_id"])
        self._folder_entry.pack(fill="x", pady=(4, 2))

        ctk.CTkLabel(
            content,
            text="ID da pasta raiz no Drive (encontrado no final da URL da pasta)",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
        ).pack(fill="x", pady=(0, 16))

        # ── Botões ────────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(content, fg_color="transparent")
        btn_row.pack(fill="x", pady=(0, 4))

        ctk.CTkButton(
            btn_row,
            text="Fechar",
            width=110,
            fg_color=("gray75", "gray30"),
            hover_color=("gray65", "gray25"),
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_row,
            text="Salvar",
            width=110,
            font=ctk.CTkFont(weight="bold"),
            command=self._save,
        ).pack(side="right")

        self._feedback_label = ctk.CTkLabel(
            content,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="#2fa84f",
            anchor="w",
        )
        self._feedback_label.pack(fill="x", pady=(6, 0))

    # -----------------------------------------------------------------------
    # Helpers de layout
    # -----------------------------------------------------------------------
    def _section_label(self, parent, text):
        ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 2))

    # -----------------------------------------------------------------------
    # Auth
    # -----------------------------------------------------------------------
    def _refresh_auth_status(self):
        authorized = baixar_audio.check_auth_status()
        if authorized:
            self._auth_status_label.configure(
                text="✓  Autorizado",
                text_color="#2fa84f",
            )
            self._auth_action_btn.configure(
                text="Logout",
                fg_color=("#c0392b", "#922b21"),
                hover_color=("#922b21", "#7b241c"),
            )
        else:
            self._auth_status_label.configure(
                text="✗  Não autorizado",
                text_color="#e05252",
            )
            self._auth_action_btn.configure(
                text="Autorizar",
                fg_color=("#1f6aa5", "#144870"),
                hover_color=("#144870", "#0f3555"),
            )

    def _toggle_auth(self):
        if baixar_audio.check_auth_status():
            self._do_logout()
        else:
            self._do_authorize()

    def _do_logout(self):
        baixar_audio.logout_drive()
        self._refresh_auth_status()
        self._feedback_label.configure(
            text="Logout realizado. Autorize novamente antes de processar.",
            text_color="#e0a020",
        )

    def _do_authorize(self):
        if self._auth_running:
            return
        self._auth_running = True
        self._auth_action_btn.configure(state="disabled", text="Autorizando...")
        threading.Thread(target=self._auth_worker, daemon=True).start()

    def _auth_worker(self):
        try:
            baixar_audio.run_auth()
            self.after(0, self._on_auth_done)
        except Exception as e:
            self.after(0, lambda: self._on_auth_error(str(e)))

    def _on_auth_done(self):
        self._auth_running = False
        self._auth_action_btn.configure(state="normal")
        self._refresh_auth_status()
        self._feedback_label.configure(
            text="Google Drive autorizado com sucesso!",
            text_color="#2fa84f",
        )

    def _on_auth_error(self, msg):
        self._auth_running = False
        self._auth_action_btn.configure(state="normal")
        self._refresh_auth_status()
        self._feedback_label.configure(
            text=f"Erro na autorização: {msg}",
            text_color="#e05252",
        )

    # -----------------------------------------------------------------------
    # Salvar configurações
    # -----------------------------------------------------------------------
    def _save(self):
        channel = self._channel_entry.get().strip()
        folder  = self._folder_entry.get().strip()

        if not channel:
            self._feedback_label.configure(
                text="URL do canal não pode estar vazia.",
                text_color="#e05252",
            )
            return
        if not folder:
            self._feedback_label.configure(
                text="ID da pasta não pode estar vazio.",
                text_color="#e05252",
            )
            return

        baixar_audio.save_config(channel_url=channel, drive_folder_id=folder)
        self._feedback_label.configure(
            text="Configurações salvas com sucesso!",
            text_color="#2fa84f",
        )


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
