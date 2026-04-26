"""
IPMadalena — Cultos para o Drive  (interface PyQt6)
"""

# ---------------------------------------------------------------------------
# Modo subprocesso do player — verificar ANTES de qualquer import Qt/Tk
# ---------------------------------------------------------------------------
import sys as _sys

if "--player-mode-qt" in _sys.argv:
    _idx = _sys.argv.index("--player-mode-qt")
    _sys.argv = [_sys.argv[0]] + _sys.argv[_idx + 1:]
    from player_subprocess_qt import main as _player_qt_main
    _player_qt_main()
    _sys.exit(0)

import logging
import os
import queue
import socket
import sys
import threading
from datetime import datetime

from PyQt6.QtCore import QDate, QTimer, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget, QCalendarWidget,
)

import baixar_audio
from setup_wizard import SetupWizard
from player_window_qt import PlayerWindowQt as PlayerWindow


# ---------------------------------------------------------------------------
# Instância única — impede abrir dois apps ao mesmo tempo
# ---------------------------------------------------------------------------
_LOCK_PORT = 47892
_lock_socket = None


def _acquire_single_instance():
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
        handlers=[logging.FileHandler(log_file, encoding="utf-8")],
    )
    logging.info("App iniciado.")


def _file_log(msg: str):
    logging.info(msg)


# ---------------------------------------------------------------------------
# Qt Stylesheet (dark theme)
# ---------------------------------------------------------------------------
_QSS = """
QMainWindow, QWidget {
    background-color: #212121;
    color: #e0e0e0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QLabel  { color: #e0e0e0; }
QDialog { background-color: #212121; }
QLineEdit {
    background: #333; color: #e0e0e0;
    border: 1px solid #555; border-radius: 4px;
    padding: 4px 8px;
}
QLineEdit:focus { border: 1px solid #1f6aa5; }
QPushButton {
    background: #1f6aa5; color: #fff;
    border: none; border-radius: 4px;
    padding: 6px 18px;
}
QPushButton:hover    { background: #2980b9; }
QPushButton:disabled { background: #444; color: #888; }
QPushButton#cancel_btn  { background: #c0392b; }
QPushButton#cancel_btn:hover    { background: #e74c3c; }
QPushButton#cancel_btn:disabled { background: #555; color: #888; }
QPushButton#icon_btn {
    background: transparent; font-size: 16px;
    border: none; border-radius: 4px; padding: 4px 8px;
}
QPushButton#icon_btn:hover { background: #444; }
QPushButton#gray_btn { background: #555; }
QPushButton#gray_btn:hover { background: #666; }
QPushButton#red_btn  { background: #c0392b; }
QPushButton#red_btn:hover { background: #e74c3c; }
QProgressBar {
    background: #333; border: none;
    border-radius: 3px; max-height: 12px;
    text-align: center;
}
QProgressBar::chunk { background: #1f6aa5; border-radius: 3px; }
QPlainTextEdit {
    background: #1a1a1a; color: #c8c8c8;
    border: 1px solid #333; border-radius: 4px;
    font-family: Consolas, monospace; font-size: 11px;
}
QFrame#auth_banner { background: #5a3500; border-radius: 8px; }
QFrame#date_frame  { background: #2b2b2b; border-radius: 8px; }
QFrame#sep         { background: #444; }
QFrame#card        { background: #2b2b2b; border-radius: 6px; }
QScrollArea        { border: none; }
QScrollBar:vertical {
    background: #2b2b2b; width: 8px; border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #555; border-radius: 4px; min-height: 20px;
}
QCalendarWidget { background: #2b2b2b; color: #e0e0e0; }
"""


# ---------------------------------------------------------------------------
# Barra de progresso com interface get()/set() em escala 0.0–1.0
# ---------------------------------------------------------------------------
class _ProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimum(0)
        self.setMaximum(100)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(12)

    def get(self) -> float:
        return self.value() / 100.0

    def set(self, value: float):
        self.setValue(int(max(0.0, min(1.0, value)) * 100))


# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------
class App(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPMadalena — Cultos para o Drive")
        self.setFixedSize(660, 700)

        _icon = os.path.join(
            getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
            "icon.ico",
        )
        if os.path.exists(_icon):
            self.setWindowIcon(QIcon(_icon))

        # Estado interno
        self._queue            = queue.Queue()
        self._running          = False
        self._converting       = False
        self._cancel_event     = threading.Event()
        self._dot_pulsing      = False
        self._dot_pulse_bright = True
        self._conv_value       = 0.0
        self._status_text_color = "gray"   # exposto para testes

        from composition_root import build_notifier
        self._notifier = build_notifier()

        self._build_ui()

        # Timer de polling da fila (worker → GUI)
        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._process_queue)
        self._queue_timer.start(100)

        # Atualiza yt-dlp em background
        threading.Thread(target=self._init_update_ytdlp, daemon=True).start()

        # Wizard na primeira execução
        if not baixar_audio.check_auth_status():
            self.hide()
            wizard = SetupWizard(self, on_complete=self._on_wizard_complete)
            wizard.show()
        else:
            self._check_auth_visibility()

    # -----------------------------------------------------------------------
    # Layout
    # -----------------------------------------------------------------------
    def _build_ui(self):
        PAD = 28

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(PAD, 24, PAD, 24)
        root.setSpacing(0)

        # ── Cabeçalho ──────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("IPMadalena — Cultos para o Drive")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        gear = QPushButton("⚙")
        gear.setObjectName("icon_btn")
        gear.setFixedSize(34, 34)
        gear.clicked.connect(self._open_settings)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(gear)
        root.addLayout(hdr)
        root.addSpacing(4)

        sub = QLabel("Baixa o áudio dos cultos do YouTube e envia para o Google Drive")
        sub.setStyleSheet("color: #888; font-size: 12px;")
        root.addWidget(sub)
        root.addSpacing(12)

        # ── Banner de autorização (inicialmente oculto) ─────────────────────
        self._auth_banner = QFrame()
        self._auth_banner.setObjectName("auth_banner")
        ab = QHBoxLayout(self._auth_banner)
        ab.setContentsMargins(14, 6, 14, 6)
        ab_lbl = QLabel("⚠  Google Drive não autorizado")
        ab_lbl.setStyleSheet("font-weight: bold; color: #f0a830;")
        self._auth_btn = QPushButton("Autorizar")
        self._auth_btn.setStyleSheet(
            "background: #d4820a; padding: 4px 14px; border-radius: 4px;"
        )
        self._auth_btn.clicked.connect(self._start_auth)
        ab.addWidget(ab_lbl)
        ab.addStretch()
        ab.addWidget(self._auth_btn)
        self._auth_banner.hide()
        root.addWidget(self._auth_banner)

        # ── Seleção de data ────────────────────────────────────────────────
        date_frame = QFrame()
        date_frame.setObjectName("date_frame")
        dr = QHBoxLayout(date_frame)
        dr.setContentsMargins(16, 8, 16, 8)
        dr.setSpacing(8)
        dr.addWidget(QLabel("Data do culto:"))

        self.date_entry = QLineEdit()
        self.date_entry.setPlaceholderText("DD/MM/AAAA")
        self.date_entry.setFixedWidth(130)
        dr.addWidget(self.date_entry)

        cal_btn = QPushButton("📅")
        cal_btn.setObjectName("icon_btn")
        cal_btn.setFixedWidth(40)
        cal_btn.clicked.connect(self._open_calendar)
        dr.addWidget(cal_btn)

        dr.addStretch()

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.setFixedWidth(100)
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.hide()
        dr.addWidget(self.cancel_btn)

        self.run_btn = QPushButton("Processar")
        self.run_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self.run_btn.setFixedWidth(120)
        self.run_btn.clicked.connect(self._start)
        dr.addWidget(self.run_btn)

        root.addWidget(date_frame)
        root.addSpacing(16)

        # ── Separador ──────────────────────────────────────────────────────
        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)
        root.addSpacing(12)

        # ── Status ─────────────────────────────────────────────────────────
        sr = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setFixedWidth(16)
        self._status_dot.setStyleSheet("color: gray; font-size: 11px;")
        self.status_label = QLabel("Pronto")
        self.status_label.setStyleSheet("color: gray;")
        sr.addWidget(self._status_dot)
        sr.addWidget(self.status_label, stretch=1)
        root.addLayout(sr)
        root.addSpacing(8)

        # ── Progresso (oculto no idle) ──────────────────────────────────────
        self._progress_frame = QWidget()
        pfl = QVBoxLayout(self._progress_frame)
        pfl.setContentsMargins(0, 0, 0, 0)
        pfl.setSpacing(6)

        LABEL_W = 78

        def _bar_row(text):
            row = QHBoxLayout()
            lbl = QLabel(text)
            lbl.setFixedWidth(LABEL_W)
            lbl.setStyleSheet("color: #666; font-size: 11px;")
            bar = _ProgressBar()
            stats = QLabel("")
            stats.setFixedWidth(190)
            stats.setStyleSheet(
                "color: gray; font-family: Consolas; font-size: 11px;"
            )
            row.addWidget(lbl)
            row.addWidget(bar, stretch=1)
            row.addWidget(stats)
            pfl.addLayout(row)
            return bar, stats

        self.download_bar,  self.download_stats       = _bar_row("Download")
        self.convert_bar,   self.convert_stats        = _bar_row("Conversão")
        self.progress_bar,  self.upload_stats_label   = _bar_row("Upload")

        self._progress_frame.hide()
        root.addWidget(self._progress_frame)

        # ── Log ────────────────────────────────────────────────────────────
        log_hdr = QLabel("Log de execução:")
        log_hdr.setStyleSheet("color: #888; font-size: 12px;")
        root.addWidget(log_hdr)
        root.addSpacing(4)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        root.addWidget(self.log_box, stretch=1)

    # -----------------------------------------------------------------------
    # Calendário popup
    # -----------------------------------------------------------------------
    def _open_calendar(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Selecionar data")
        dlg.setFixedSize(310, 340)
        layout = QVBoxLayout(dlg)

        cal = QCalendarWidget()
        cal.setGridVisible(True)
        initial = QDate.currentDate()
        try:
            d = datetime.strptime(self.date_entry.text().strip(), "%d/%m/%Y")
            initial = QDate(d.year, d.month, d.day)
        except ValueError:
            pass
        cal.setSelectedDate(initial)
        layout.addWidget(cal)

        btn = QPushButton("Confirmar")
        btn.clicked.connect(lambda: (
            self.date_entry.setText(
                cal.selectedDate().toString("dd/MM/yyyy")
            ),
            dlg.accept(),
        ))
        layout.addWidget(btn)
        dlg.exec()

    # -----------------------------------------------------------------------
    # Fila de mensagens (workers → GUI)
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
                    lo = value.lower()
                    if "convertendo" in lo:
                        if not self._converting:
                            self._converting = True
                            self._conv_value = 0.0
                            self.convert_stats.setText("aguardando...")
                            self._animate_conversion()
                    elif self._converting:
                        self._converting = False
                        self.convert_bar.set(1.0)
                        self.convert_stats.setText("")

                elif kind == "download_progress":
                    self.download_bar.set(value)
                    self.download_stats.setText(f"{value * 100:.0f}%")

                elif kind == "progress":
                    self.progress_bar.set(value / 100)

                elif kind == "upload_stats":
                    mb_done, mb_total, rate = value
                    if mb_done == 0 and rate == 0:
                        self.upload_stats_label.setText("")
                    elif rate > 0:
                        self.upload_stats_label.setText(
                            f"{mb_done:.1f} / {mb_total:.1f} MB  {rate:.2f} MB/s"
                        )
                    else:
                        self.upload_stats_label.setText(
                            f"{mb_done:.1f} / {mb_total:.1f} MB"
                        )

                elif kind == "select_videos":
                    self._show_video_selection(*value)

                elif kind == "open_player":
                    self._show_player_window(*value)

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
                    self._auth_banner.hide()
                    self._append_log("Google Drive autorizado com sucesso!")
                    _file_log("Google Drive autorizado com sucesso.")

                elif kind == "auth_error":
                    self._auth_btn.setEnabled(True)
                    self._auth_btn.setText("Autorizar")
                    self._append_log(f"Erro na autorização: {value}")
                    _file_log(f"Erro na autorização Drive: {value}")

        except queue.Empty:
            pass

    def _append_log(self, msg: str):
        now = datetime.now().strftime("%H:%M:%S")
        self.log_box.appendPlainText(f"[{now}]  {msg}")

    # -----------------------------------------------------------------------
    # Status dot
    # -----------------------------------------------------------------------
    def _set_status(self, text: str, state: str = "running"):
        _colors = {
            "idle":    ("gray",    "gray"),
            "running": ("white",   "#4a9edd"),
            "done":    ("#2fa84f", "#2fa84f"),
            "error":   ("#e05252", "#e05252"),
        }
        tc, dc = _colors.get(state, ("white", "#4a9edd"))
        self._status_text_color = tc
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {tc};")
        self._status_dot.setStyleSheet(f"color: {dc}; font-size: 11px;")
        if state == "running":
            self._start_dot_pulse()
        else:
            self._stop_dot_pulse(dc)

    def _start_dot_pulse(self):
        if not self._dot_pulsing:
            self._dot_pulsing = True
            self._dot_pulse_bright = True
            self._animate_dot_pulse()

    def _stop_dot_pulse(self, final_color: str):
        self._dot_pulsing = False
        self._status_dot.setStyleSheet(f"color: {final_color}; font-size: 11px;")

    def _animate_dot_pulse(self):
        if not self._dot_pulsing:
            return
        color = "#4a9edd" if self._dot_pulse_bright else "#1a5a8c"
        self._dot_pulse_bright = not self._dot_pulse_bright
        self._status_dot.setStyleSheet(f"color: {color}; font-size: 11px;")
        QTimer.singleShot(500, self._animate_dot_pulse)

    # -----------------------------------------------------------------------
    # Barras de progresso
    # -----------------------------------------------------------------------
    def _hide_bars(self):
        self._converting = False
        self._conv_value = 0.0
        self._progress_frame.hide()
        self.download_bar.set(0)
        self.convert_bar.set(0)
        self.progress_bar.set(0)
        self.download_stats.setText("")
        self.convert_stats.setText("")
        self.upload_stats_label.setText("")

    def _show_bars(self):
        self._conv_value = 0.0
        self.download_bar.set(0)
        self.convert_bar.set(0)
        self.progress_bar.set(0)
        self.download_stats.setText("")
        self.convert_stats.setText("")
        self.upload_stats_label.setText("")
        self._progress_frame.show()

    def _animate_conversion(self):
        if not self._converting:
            return
        self._conv_value = min(self._conv_value + 0.018, 0.90)
        self.convert_bar.set(self._conv_value)
        QTimer.singleShot(160, self._animate_conversion)

    # -----------------------------------------------------------------------
    # Iniciar / Cancelar
    # -----------------------------------------------------------------------
    def _start(self):
        date_str = self.date_entry.text().strip()
        if not date_str:
            self._show_error("Informe a data do culto.")
            return
        try:
            datetime.strptime(date_str, "%d/%m/%Y")
        except ValueError:
            self._show_error(
                "Data inválida.\nUse o formato DD/MM/AAAA  (ex: 19/04/2026)."
            )
            return
        if not baixar_audio.check_auth_status():
            self._show_error(
                "Google Drive não autorizado.\n\n"
                "Clique em 'Autorizar' no banner acima ou acesse ⚙ Configurações."
            )
            return

        self.log_box.clear()
        self._set_status("Verificando...", "running")
        self._cancel_event.clear()
        self._converting = False
        self._running = True
        self._show_bars()
        self._set_buttons_running(True)

        threading.Thread(
            target=self._worker_preflight, args=(date_str,), daemon=True
        ).start()

    def _cancel(self):
        if not self._running:
            return
        self._cancel_event.set()
        self._converting = False
        self._append_log("Cancelamento solicitado...")
        self._set_status("Cancelando...", "running")
        self._hide_bars()
        self.cancel_btn.setEnabled(False)

    def _set_buttons_running(self, running: bool):
        if running:
            self.run_btn.setEnabled(False)
            self.run_btn.setText("Processando...")
            self.cancel_btn.show()
        else:
            self.cancel_btn.hide()
            self.run_btn.setEnabled(True)
            self.run_btn.setText("Processar")
            self.cancel_btn.setEnabled(True)

    # -----------------------------------------------------------------------
    # Workers de background
    # -----------------------------------------------------------------------
    def _init_update_ytdlp(self):
        baixar_audio.update_ytdlp(
            on_log=lambda m: self._queue.put(("log", m))
        )

    def _worker_preflight(self, date_str: str):
        log = lambda m: self._queue.put(("log", m))

        log("Verificando conexão com a internet...")
        if not baixar_audio.check_internet():
            self._queue.put((
                "preflight_error",
                "Sem conexão com a internet.\nVerifique sua rede e tente novamente.",
            ))
            return

        log("Verificando espaço em disco...")
        ok, free_mb = baixar_audio.check_disk_space(min_mb=500)
        if not ok:
            self._queue.put((
                "preflight_error",
                f"Espaço insuficiente em disco: {free_mb:.0f} MB livres.\n"
                "São necessários pelo menos 500 MB.",
            ))
            return
        log(f"Espaço livre: {free_mb:.0f} MB — OK.")

        baixar_audio.cleanup_downloads(on_log=log)

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
            self._queue.put(("history_warning", (date_str, videos, processado_em)))
            return

        self._queue.put(("status", "Buscando vídeos..."))
        threading.Thread(
            target=self._worker, args=(date_str,), daemon=True
        ).start()

    def _build_presenter(self):
        from composition_root import build_processing_presenter
        return build_processing_presenter()

    def _worker(self, date_str: str):
        try:
            videos = self._build_presenter().list_videos(
                date_str,
                cancel_event=self._cancel_event,
                on_log=lambda m: self._queue.put(("log", m)),
                on_status=lambda m: self._queue.put(("status", m)),
            )
            self._queue.put(("select_videos", (date_str, videos)))
        except baixar_audio.OperacaoCancelada:
            self._queue.put(("cancelled", None))
        except Exception as e:
            self._queue.put(("error", str(e)))

    def _show_player_window(self, date_str: str, selected_videos: list):
        def _on_complete(segments):
            self._append_log("Trechos confirmados. Iniciando download...")
            threading.Thread(
                target=self._worker_phase2,
                args=(date_str, segments),
                daemon=True,
            ).start()

        def _on_cancel():
            self._on_cancelled()

        PlayerWindow(
            self, selected_videos,
            on_complete=_on_complete, on_cancel=_on_cancel,
        )

    def _worker_phase2(self, date_str: str, segments: list):
        try:
            titles = self._build_presenter().process_segments(
                date_str,
                segments,
                cancel_event=self._cancel_event,
                on_log=lambda m: self._queue.put(("log", m)),
                on_status=lambda m: self._queue.put(("status", m)),
                on_download_progress=lambda p: self._queue.put(("download_progress", p)),
                on_upload_progress=lambda p: self._queue.put(("progress", p)),
                on_upload_stats=lambda d, t, r: self._queue.put(("upload_stats", (d, t, r))),
            )
            self._queue.put(("done", (date_str, titles)))
        except baixar_audio.OperacaoCancelada:
            self._queue.put(("cancelled", None))
        except Exception as e:
            self._queue.put(("error", str(e)))

    # -----------------------------------------------------------------------
    # Configurações e autorização
    # -----------------------------------------------------------------------
    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.finished.connect(lambda _: self._check_auth_visibility())
        dlg.exec()

    def _check_auth_visibility(self):
        if baixar_audio.check_auth_status():
            self._auth_banner.hide()
        else:
            self._auth_banner.show()

    def _start_auth(self):
        self._auth_btn.setEnabled(False)
        self._auth_btn.setText("Autorizando...")
        self._append_log("Abrindo navegador para autorização do Google Drive...")
        _file_log("Iniciando fluxo OAuth do Drive.")
        threading.Thread(target=self._run_auth_worker, daemon=True).start()

    def _run_auth_worker(self):
        try:
            baixar_audio.run_auth(
                on_log=lambda m: self._queue.put(("log", m))
            )
            self._queue.put(("auth_done", None))
        except Exception as e:
            self._queue.put(("auth_error", str(e)))

    # -----------------------------------------------------------------------
    # Popups (modais — executados no thread principal via queue)
    # -----------------------------------------------------------------------
    def _show_history_warning(self, date_str: str, videos: list, processado_em: str):
        dlg = QDialog(self)
        dlg.setWindowTitle("Data já processada")
        dlg.setFixedSize(480, 280)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        lbl = QLabel("⚠  Data já processada")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #e0a020;")
        layout.addWidget(lbl)
        layout.addWidget(QLabel(
            f"A data {date_str} já foi processada em {processado_em}."
        ))
        if videos:
            nomes = "\n".join(f"  • {v}" for v in videos[:5])
            if len(videos) > 5:
                nomes += f"\n  … e mais {len(videos) - 5} vídeo(s)"
            v_lbl = QLabel(nomes)
            v_lbl.setStyleSheet("color: gray; font-family: Consolas; font-size: 11px;")
            layout.addWidget(v_lbl)
        layout.addWidget(QLabel("Deseja processar novamente?"))

        btn_row = QHBoxLayout()
        btn_sim = QPushButton("Sim, continuar")
        btn_nao = QPushButton("Não, cancelar")
        btn_nao.setObjectName("gray_btn")
        btn_row.addWidget(btn_sim)
        btn_row.addWidget(btn_nao)
        layout.addLayout(btn_row)

        _result = {"action": "cancel"}

        def _continuar():
            _result["action"] = "continue"
            dlg.accept()

        def _cancelar():
            _result["action"] = "cancel"
            dlg.reject()

        btn_sim.clicked.connect(_continuar)
        btn_nao.clicked.connect(_cancelar)
        dlg.exec()

        if _result["action"] == "continue":
            threading.Thread(
                target=self._worker, args=(date_str,), daemon=True
            ).start()
        else:
            self._on_cancelled()

    def _show_video_selection(self, date_str: str, videos: list):
        dlg = QDialog(self)
        dlg.setWindowTitle("Vídeos encontrados")
        dlg.setFixedSize(560, 420)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(8)

        t_lbl = QLabel(f"Vídeos encontrados para {date_str}")
        t_lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(t_lbl)
        s_lbl = QLabel("Selecione os vídeos que deseja baixar e enviar para o Drive:")
        s_lbl.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(s_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        cl = QVBoxLayout(container)
        cl.setSpacing(4)

        check_boxes = []
        for video in videos:
            card = QFrame()
            card.setObjectName("card")
            ch = QHBoxLayout(card)
            ch.setContentsMargins(10, 8, 10, 8)
            chk = QCheckBox()
            chk.setChecked(True)
            check_boxes.append(chk)
            ch.addWidget(chk)
            info = QVBoxLayout()
            vt = QLabel(video["title"])
            vt.setStyleSheet("font-weight: bold; font-size: 12px;")
            vt.setWordWrap(True)
            info.addWidget(vt)
            try:
                d = datetime.strptime(video["upload_date"], "%Y%m%d")
                date_fmt = f"Publicado em {d.strftime('%d/%m/%Y')}"
            except Exception:
                date_fmt = video["upload_date"]
            dl = QLabel(date_fmt)
            dl.setStyleSheet("color: gray; font-size: 11px;")
            info.addWidget(dl)
            ch.addLayout(info, stretch=1)
            cl.addWidget(card)

        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        _result = {"action": "cancel", "selected": []}

        def _prosseguir():
            selected = [v for v, chk in zip(videos, check_boxes) if chk.isChecked()]
            if not selected:
                return
            _result["action"] = "proceed"
            _result["selected"] = selected
            dlg.accept()

        def _cancelar():
            _result["action"] = "cancel"
            dlg.reject()

        btn_proc = QPushButton("Prosseguir")
        btn_proc.setStyleSheet("font-weight: bold;")
        btn_proc.clicked.connect(_prosseguir)
        layout.addWidget(btn_proc)
        dlg.rejected.connect(_cancelar)
        dlg.exec()

        if _result["action"] == "proceed":
            selected = _result["selected"]
            self._append_log(
                f"{len(selected)} vídeo(s) selecionado(s). "
                "Abrindo player para seleção de trecho..."
            )
            self._queue.put(("open_player", (date_str, selected)))
        else:
            self._on_cancelled()

    def _show_error(self, msg: str):
        QMessageBox.critical(self, "Erro", msg)

    # -----------------------------------------------------------------------
    # Callbacks de finalização
    # -----------------------------------------------------------------------
    def _on_preflight_error(self, msg: str):
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
        self._stop_dot_pulse("#2fa84f")
        self._set_buttons_running(False)
        self.download_bar.set(1)
        self.convert_bar.set(1)
        self.progress_bar.set(1)
        self.convert_stats.setText("")

        if date_str and video_titles:
            baixar_audio.save_history(date_str, video_titles)
            _file_log(f"Histórico salvo: {date_str} — {len(video_titles)} vídeo(s).")

        n = len(video_titles) if video_titles else 0
        self._notifier.notify(
            title="IPMadalena — Concluído ✓",
            message=f"{n} vídeo(s) enviado(s) ao Drive com sucesso!",
        )

    def _on_error(self, msg: str):
        self._running = False
        self._converting = False
        self._set_buttons_running(False)
        self._hide_bars()
        self._set_status("Erro — veja o log abaixo", "error")
        self._append_log(f"ERRO: {msg}")
        _file_log(f"ERRO: {msg}")
        self._show_error(msg)

    def _on_wizard_complete(self):
        self._check_auth_visibility()
        self.show()

    # -----------------------------------------------------------------------
    # Fechar
    # -----------------------------------------------------------------------
    def closeEvent(self, event):
        self._queue_timer.stop()
        event.accept()


# ---------------------------------------------------------------------------
# Configurações (dialog modal)
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setFixedSize(540, 490)
        self._auth_running = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(10)

        title = QLabel("Configurações")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # ── Google Drive ────────────────────────────────────────────────────
        layout.addWidget(self._section_label("Google Drive"))

        auth_card = QFrame()
        auth_card.setObjectName("card")
        ac = QHBoxLayout(auth_card)
        ac.setContentsMargins(14, 10, 14, 10)
        self._auth_status_label = QLabel("")
        self._auth_action_btn = QPushButton("")
        self._auth_action_btn.setFixedWidth(110)
        self._auth_action_btn.clicked.connect(self._toggle_auth)
        ac.addWidget(self._auth_status_label, stretch=1)
        ac.addWidget(self._auth_action_btn)
        layout.addWidget(auth_card)

        self._refresh_auth_status()

        # ── Canal do YouTube ────────────────────────────────────────────────
        layout.addWidget(self._section_label("Canal do YouTube"))
        cfg = baixar_audio.load_config()
        self._channel_entry = QLineEdit(cfg["channel_url"])
        layout.addWidget(self._channel_entry)
        yt_hint = QLabel("Ex: https://www.youtube.com/@SeuCanal/streams")
        yt_hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(yt_hint)

        # ── Pasta do Google Drive ───────────────────────────────────────────
        layout.addWidget(self._section_label("Pasta do Google Drive"))
        self._folder_entry = QLineEdit(cfg["drive_folder_id"])
        layout.addWidget(self._folder_entry)
        dr_hint = QLabel(
            "ID da pasta raiz no Drive (encontrado no final da URL da pasta)"
        )
        dr_hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(dr_hint)

        layout.addStretch()

        # ── Botões ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_save = QPushButton("Salvar")
        btn_save.setStyleSheet("font-weight: bold;")
        btn_save.clicked.connect(self._save)
        btn_close = QPushButton("Fechar")
        btn_close.setObjectName("gray_btn")
        btn_close.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._feedback_label = QLabel("")
        self._feedback_label.setStyleSheet("color: #2fa84f; font-size: 11px;")
        layout.addWidget(self._feedback_label)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        return lbl

    def _refresh_auth_status(self):
        if baixar_audio.check_auth_status():
            self._auth_status_label.setText("✓  Autorizado")
            self._auth_status_label.setStyleSheet("color: #2fa84f;")
            self._auth_action_btn.setText("Logout")
            self._auth_action_btn.setStyleSheet(
                "background: #c0392b; border-radius: 4px;"
            )
        else:
            self._auth_status_label.setText("✗  Não autorizado")
            self._auth_status_label.setStyleSheet("color: #e05252;")
            self._auth_action_btn.setText("Autorizar")
            self._auth_action_btn.setStyleSheet(
                "background: #1f6aa5; border-radius: 4px;"
            )

    def _toggle_auth(self):
        if baixar_audio.check_auth_status():
            self._do_logout()
        else:
            self._do_authorize()

    def _do_logout(self):
        baixar_audio.logout_drive()
        self._refresh_auth_status()
        self._feedback_label.setText(
            "Logout realizado. Autorize novamente antes de processar."
        )
        self._feedback_label.setStyleSheet("color: #e0a020; font-size: 11px;")

    def _do_authorize(self):
        if self._auth_running:
            return
        self._auth_running = True
        self._auth_action_btn.setEnabled(False)
        self._auth_action_btn.setText("Autorizando...")
        threading.Thread(target=self._auth_worker, daemon=True).start()

    def _auth_worker(self):
        try:
            baixar_audio.run_auth()
            QTimer.singleShot(0, self._on_auth_done)
        except Exception as e:
            QTimer.singleShot(0, lambda: self._on_auth_error(str(e)))

    def _on_auth_done(self):
        self._auth_running = False
        self._auth_action_btn.setEnabled(True)
        self._refresh_auth_status()
        self._feedback_label.setText("Google Drive autorizado com sucesso!")
        self._feedback_label.setStyleSheet("color: #2fa84f; font-size: 11px;")

    def _on_auth_error(self, msg: str):
        self._auth_running = False
        self._auth_action_btn.setEnabled(True)
        self._refresh_auth_status()
        self._feedback_label.setText(f"Erro na autorização: {msg}")
        self._feedback_label.setStyleSheet("color: #e05252; font-size: 11px;")

    def _save(self):
        channel = self._channel_entry.text().strip()
        folder  = self._folder_entry.text().strip()
        if not channel:
            self._feedback_label.setText("URL do canal não pode estar vazia.")
            self._feedback_label.setStyleSheet("color: #e05252; font-size: 11px;")
            return
        if not folder:
            self._feedback_label.setText("ID da pasta não pode estar vazio.")
            self._feedback_label.setStyleSheet("color: #e05252; font-size: 11px;")
            return
        baixar_audio.save_config(channel_url=channel, drive_folder_id=folder)
        self._feedback_label.setText("Configurações salvas com sucesso!")
        self._feedback_label.setStyleSheet("color: #2fa84f; font-size: 11px;")


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not _acquire_single_instance():
        _q = QApplication(sys.argv)
        QMessageBox.critical(
            None,
            "IPMadalena já está aberto",
            "O aplicativo já está em execução.\n"
            "Feche a janela existente antes de abrir novamente.",
        )
        sys.exit(1)
    else:
        _setup_file_logging()
        _q = QApplication(sys.argv)
        _q.setStyle("Fusion")
        _q.setStyleSheet(_QSS)
        win = App()
        win.show()
        sys.exit(_q.exec())
