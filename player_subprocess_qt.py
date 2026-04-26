#!/usr/bin/env python3
"""
player_subprocess_qt.py — Player YouTube embutido (processo filho).

Recebe a lista de vídeos via stdin (primeira linha JSON), exibe cada um em
QWebEngineView com painel de controles integrado e devolve o resultado ao
processo pai via stdout (JSON).

Protocolo stdin ← pai (primeira linha após iniciar):
  {"videos": [{"id": "...", "title": "...", "upload_date": "..."}, ...]}

Protocolo stdout → pai (ao concluir):
  {"type": "segments",  "segments": [{"id","title","start","end"}, ...]}
  {"type": "cancelled"}
"""

import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Paleta de cores
# ---------------------------------------------------------------------------
_BG       = "#1e1e1e"
_PANEL    = "#2b2b2b"
_TEXT     = "#e0e0e0"
_GRAY     = "#888888"
_GREEN    = "#2fa84f"
_RED      = "#e05252"
_YELLOW   = "#e0a020"
_BLUE     = "#1565c0"
_PURPLE   = "#6a1b9a"
_BTN_DARK = "#3a3a3a"

_QSS = f"""
QMainWindow, QWidget {{ background: {_BG}; color: {_TEXT}; }}
QFrame#panel {{ background: {_PANEL}; }}
QLabel {{ color: {_TEXT}; }}
QLineEdit {{
    background: #3c3c3c; color: {_TEXT}; border: 1px solid #555;
    border-radius: 3px; padding: 2px 6px; font-family: monospace; font-size: 13px;
}}
QLineEdit:focus {{ border: 1px solid #1e88e5; }}
QPushButton {{
    background: {_BTN_DARK}; color: {_TEXT}; border: none;
    border-radius: 4px; padding: 5px 14px; font-size: 13px;
}}
QPushButton:hover   {{ background: #4a4a4a; }}
QPushButton:disabled {{ background: #2a2a2a; color: #555; }}
QPushButton#btnConfirm {{
    background: {_BLUE}; color: #fff; font-weight: bold; padding: 5px 18px;
}}
QPushButton#btnConfirm:hover    {{ background: #1976d2; }}
QPushButton#btnConfirm:disabled {{ background: #1a3a5c; color: #555; }}
QPushButton#btnFull  {{ background: #37474f; color: {_TEXT}; }}
QPushButton#btnFull:hover    {{ background: #455a64; }}
QPushButton#btnFull:disabled {{ background: #2a2a2a; color: #555; }}
QPushButton#btnCancel {{
    background: transparent; color: #aaa; border: 1px solid #555;
    border-radius: 4px; padding: 5px 10px;
}}
QPushButton#btnCancel:hover {{ background: #3a3a3a; color: {_TEXT}; }}
QFrame#sep {{ background: #444; }}
"""


# ---------------------------------------------------------------------------
# Utilitários de tempo (mesmo contrato de player_window.py)
# ---------------------------------------------------------------------------

def _seconds_to_hms(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def _hms_to_seconds(hms: str):
    """'HH:MM:SS' → float ou None se inválido."""
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
# JavaScript injetado no player
# ---------------------------------------------------------------------------

_THEATER_JS = """
(function tryTheater(n) {
    var btn = document.querySelector('.ytp-size-button');
    if (btn) {
        var p = document.getElementById('movie_player');
        if (p && !p.classList.contains('ytp-modern-api-theater-mode-player'))
            btn.click();
    } else if (n > 0) {
        setTimeout(function() { tryTheater(n - 1); }, 800);
    }
})(15);
"""

_OVERLAY_JS = """
(function() {
    if (document.getElementById('_ipm_ov')) return;
    var v = document.querySelector('video');
    if (!v) { setTimeout(arguments.callee, 700); return; }
    var d = document.createElement('div');
    d.id = '_ipm_ov';
    d.style.cssText = [
        'position:fixed', 'bottom:72px', 'left:50%',
        'transform:translateX(-50%)',
        'background:rgba(0,0,0,0.70)', 'border-radius:8px',
        'padding:6px 18px', 'z-index:99999',
        'pointer-events:none', 'font-family:sans-serif'
    ].join(';');
    window._ipm_info = document.createElement('span');
    window._ipm_info.style.cssText = 'color:#fff;font-size:13px';
    window._ipm_info.textContent = '';
    d.appendChild(window._ipm_info);
    document.body.appendChild(d);
})();
"""

_UPDATE_INFO_JS = "if(window._ipm_info) window._ipm_info.textContent = {!r};"


# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------

class _PlayerWindow(QMainWindow):
    def __init__(self, videos: list):
        super().__init__()
        self._videos   = videos
        self._idx      = 0
        self._segments: list = []
        self._marked_start: float | None = None
        self._marked_end:   float | None = None
        self._ready    = False
        self._finished = False

        self.setWindowTitle("IPMadalena — Seleção de Trecho")
        self.resize(1200, 820)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(_QSS)

        # user-agent Chrome para evitar bloqueios do YouTube
        QWebEngineProfile.defaultProfile().setHttpUserAgent(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

        self._build_ui()
        self._load_video(0)

    # -----------------------------------------------------------------------
    # Construção da UI
    # -----------------------------------------------------------------------

    def _build_ui(self):
        # ── webview ─────────────────────────────────────────────────────────
        self._view = QWebEngineView()
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self._view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
        self._view.loadFinished.connect(self._on_loaded)

        # ── painel de controle ───────────────────────────────────────────────
        panel = QFrame()
        panel.setObjectName("panel")
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 6, 12, 8)
        panel_layout.setSpacing(4)

        # separador
        sep = QFrame()
        sep.setObjectName("sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        panel_layout.addWidget(sep)

        # linha 1: título + contador
        row1 = QHBoxLayout()
        self._title_lbl = QLabel("")
        self._title_lbl.setStyleSheet("font-weight:bold; font-size:13px;")
        self._counter_lbl = QLabel("")
        self._counter_lbl.setStyleSheet(f"color:{_GRAY}; font-size:12px;")
        row1.addWidget(self._title_lbl, stretch=1)
        row1.addWidget(self._counter_lbl)
        panel_layout.addLayout(row1)

        # linha 2: controles de tempo + botões de ação
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        # Início
        row2.addWidget(QLabel("Início:"))
        self._start_entry = QLineEdit("00:00:00")
        self._start_entry.setFixedWidth(88)
        self._start_entry.textChanged.connect(self._update_duration)
        row2.addWidget(self._start_entry)

        self._btn_mark_start = QPushButton("◄")
        self._btn_mark_start.setFixedWidth(34)
        self._btn_mark_start.setToolTip("Capturar tempo atual do vídeo como Início")
        self._btn_mark_start.setEnabled(False)
        self._btn_mark_start.clicked.connect(lambda: self._mark("start"))
        row2.addWidget(self._btn_mark_start)

        row2.addSpacing(12)

        # Fim
        row2.addWidget(QLabel("Fim:"))
        self._end_entry = QLineEdit("00:00:00")
        self._end_entry.setFixedWidth(88)
        self._end_entry.textChanged.connect(self._update_duration)
        row2.addWidget(self._end_entry)

        self._btn_mark_end = QPushButton("◄")
        self._btn_mark_end.setFixedWidth(34)
        self._btn_mark_end.setToolTip("Capturar tempo atual do vídeo como Fim")
        self._btn_mark_end.setEnabled(False)
        self._btn_mark_end.clicked.connect(lambda: self._mark("end"))
        row2.addWidget(self._btn_mark_end)

        row2.addSpacing(12)

        # Duração
        row2.addWidget(QLabel("Dur:"))
        self._dur_lbl = QLabel("--:--:--")
        self._dur_lbl.setStyleSheet("font-family:monospace; font-weight:bold; font-size:13px;")
        row2.addWidget(self._dur_lbl)

        row2.addStretch()

        # Botões de ação
        self._btn_full = QPushButton("Usar completo")
        self._btn_full.setObjectName("btnFull")
        self._btn_full.setEnabled(False)
        self._btn_full.clicked.connect(self._use_full)
        row2.addWidget(self._btn_full)

        self._btn_confirm = QPushButton("Confirmar trecho →")
        self._btn_confirm.setObjectName("btnConfirm")
        self._btn_confirm.setEnabled(False)
        self._btn_confirm.clicked.connect(self._confirm)
        row2.addWidget(self._btn_confirm)

        btn_cancel = QPushButton("✕")
        btn_cancel.setObjectName("btnCancel")
        btn_cancel.setFixedWidth(34)
        btn_cancel.setToolTip("Cancelar")
        btn_cancel.clicked.connect(self._cancel)
        row2.addWidget(btn_cancel)

        panel_layout.addLayout(row2)

        # linha 3: status
        self._status_lbl = QLabel("⏳ Carregando vídeo...")
        self._status_lbl.setStyleSheet(f"color:{_GRAY}; font-size:11px;")
        panel_layout.addWidget(self._status_lbl)

        # ── layout principal ─────────────────────────────────────────────────
        central = QWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self._view, stretch=1)
        main_layout.addWidget(panel)
        self.setCentralWidget(central)

    # -----------------------------------------------------------------------
    # Carregamento de vídeo
    # -----------------------------------------------------------------------

    def _load_video(self, idx: int):
        video = self._videos[idx]
        self._marked_start = None
        self._marked_end   = None
        self._ready        = False
        self._title_lbl.setText(video["title"])
        self._counter_lbl.setText(f"Vídeo {idx + 1} de {len(self._videos)}")
        self._start_entry.setText("00:00:00")
        self._end_entry.setText("00:00:00")
        self._dur_lbl.setText("--:--:--")
        self._set_status(f"⏳ Carregando vídeo...", _GRAY)
        self._set_controls_enabled(False)
        self._view.load(QUrl(f"https://www.youtube.com/watch?v={video['id']}"))

    # -----------------------------------------------------------------------
    # Callbacks do webview
    # -----------------------------------------------------------------------

    def _on_loaded(self, ok: bool):
        if not ok:
            self._set_status("⚠ Erro ao carregar o vídeo.", _RED)
            self._set_controls_enabled(True)
            return
        self._set_status(
            "✓ Pronto — assista e clique em ◄ para marcar os tempos.", _GREEN
        )
        self._ready = True
        self._set_controls_enabled(True)
        QTimer.singleShot(2500, self._activate_theater)
        QTimer.singleShot(3000, self._inject_overlay)

    def _activate_theater(self):
        self._view.page().runJavaScript(_THEATER_JS)

    def _inject_overlay(self):
        self._view.page().runJavaScript(_OVERLAY_JS)

    # -----------------------------------------------------------------------
    # Marcação de tempo via runJavaScript
    # -----------------------------------------------------------------------

    def _mark(self, target: str):
        def _got_time(t):
            try:
                if t is None or t < 0:
                    self._set_status("⚠ Vídeo não encontrado na página.", _YELLOW)
                    return
                hms = _seconds_to_hms(t)
                if target == "start":
                    self._marked_start = t
                    self._start_entry.setText(hms)
                else:
                    self._marked_end = t
                    self._end_entry.setText(hms)
                # diferir JS aninhado para evitar crash
                QTimer.singleShot(0, self._update_overlay)
            except Exception as e:
                self._set_status(f"⚠ Erro ao marcar tempo: {e}", _RED)

        self._view.page().runJavaScript(
            "var v = document.querySelector('video'); v ? v.currentTime : -1;",
            _got_time,
        )

    def _update_overlay(self):
        s = self._start_entry.text() if self._marked_start is not None else "--:--:--"
        e = self._end_entry.text()   if self._marked_end   is not None else "--:--:--"
        self._view.page().runJavaScript(
            _UPDATE_INFO_JS.format(f"início: {s}   fim: {e}")
        )

    # -----------------------------------------------------------------------
    # Duração calculada
    # -----------------------------------------------------------------------

    def _update_duration(self):
        start_s = _hms_to_seconds(self._start_entry.text())
        end_s   = _hms_to_seconds(self._end_entry.text())
        if start_s is not None and end_s is not None and end_s > start_s:
            self._dur_lbl.setText(_seconds_to_hms(end_s - start_s))
        else:
            self._dur_lbl.setText("--:--:--")

    # -----------------------------------------------------------------------
    # Ações do usuário
    # -----------------------------------------------------------------------

    def _confirm(self):
        start_str = self._start_entry.text().strip()
        end_str   = self._end_entry.text().strip()
        start_s   = _hms_to_seconds(start_str)
        end_s     = _hms_to_seconds(end_str)
        if start_s is None or end_s is None:
            self._set_status("⚠ Tempo inválido — use HH:MM:SS.", _RED)
            return
        if end_s <= start_s:
            self._set_status("⚠ O tempo de fim deve ser maior que o início.", _RED)
            return
        if start_s == 0 and end_s == 0:
            self._set_status(
                "⚠ Informe o trecho ou clique em 'Usar completo'.", _RED
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

    # -----------------------------------------------------------------------
    # Finalização
    # -----------------------------------------------------------------------

    def _finish(self):
        self._finished = True
        _send({"type": "segments", "segments": self._segments})
        QApplication.quit()

    def _cancel(self):
        if not self._finished:
            self._finished = True
            _send({"type": "cancelled"})
        QApplication.quit()

    def closeEvent(self, event):
        self._cancel()
        event.accept()

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _set_controls_enabled(self, enabled: bool):
        self._btn_mark_start.setEnabled(enabled)
        self._btn_mark_end.setEnabled(enabled)
        self._btn_confirm.setEnabled(enabled)
        self._btn_full.setEnabled(enabled)

    def _set_status(self, text: str, color: str = _GRAY):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(f"color:{color}; font-size:11px;")


# ---------------------------------------------------------------------------
# Comunicação com o processo pai
# ---------------------------------------------------------------------------

def _send(obj: dict):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    # Lê a lista de vídeos do stdin (enviada pelo processo pai logo após Popen)
    try:
        raw = sys.stdin.readline().strip()
        data = json.loads(raw)
        videos = data["videos"]
    except Exception as e:
        _send({"type": "cancelled"})
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    win = _PlayerWindow(videos)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
