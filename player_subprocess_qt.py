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

from PyQt6.QtCore import Qt, QTimer, QUrl
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
# Paleta — alinhada ao tema escuro do app principal (app.py / _Palette)
# ---------------------------------------------------------------------------
_BG          = "#1e1e1e"
_PANEL       = "#272727"
_CARD        = "#222222"
_INPUT       = "#2c2c2c"
_BORDER      = "#3a3a3a"
_SEP         = "#2c2c2c"
_TEXT        = "#f0f0f0"
_TEXT_SUB    = "#888"
_TEXT_MUTED  = "#666"

_GREEN       = "#2ea84f"
_GREEN_HOVER = "#37c15e"
_RED         = "#c0392b"
_RED_HOVER   = "#e74c3c"
_YELLOW      = "#e0a020"
_GRAY_BTN    = "#3a3a3a"
_GRAY_HOV    = "#4a4a4a"
_BTN_DIS     = "#2a2a2a"
_BTN_DIS_T   = "#555"

_QSS = f"""
QMainWindow, QWidget {{
    background-color: {_BG};
    color: {_TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QLabel {{ background: transparent; color: {_TEXT}; }}

/* ── Cartões e separadores ── */
QFrame#panel    {{ background: {_PANEL}; border-top: 1px solid {_SEP}; }}
QFrame#card     {{ background: {_CARD}; border-radius: 8px; }}
QFrame#sep      {{ background: {_SEP}; }}
QFrame#vsep     {{ background: {_BORDER}; }}

/* ── Labels semânticas ── */
QLabel#title    {{ color: {_TEXT}; font-size: 14px; font-weight: bold; }}
QLabel#counter  {{ color: {_TEXT_SUB}; font-size: 12px; }}
QLabel#caption  {{
    color: {_TEXT_SUB}; font-size: 10px; font-weight: bold;
    letter-spacing: 1px;
}}
QLabel#duration {{
    color: {_TEXT}; font-family: 'Consolas', 'Courier New', monospace;
    font-size: 22px; font-weight: bold;
}}
QLabel#status   {{ color: {_TEXT_SUB}; font-size: 12px; }}
QLabel#dot      {{ font-size: 13px; }}

/* ── Campos de tempo (grandes, monoespaçados) ── */
QLineEdit#time {{
    background: {_INPUT}; color: {_TEXT};
    border: 1px solid {_BORDER}; border-radius: 6px;
    padding: 6px 10px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 22px; font-weight: bold;
    selection-background-color: {_GREEN};
}}
QLineEdit#time:focus {{ border: 1px solid {_GREEN}; }}

/* ── Botão padrão (verde primário) ── */
QPushButton {{
    background: {_GREEN}; color: #fff;
    border: none; border-radius: 5px;
    padding: 7px 18px; font-size: 13px; font-weight: bold;
}}
QPushButton:hover    {{ background: {_GREEN_HOVER}; }}
QPushButton:disabled {{ background: {_BTN_DIS}; color: {_BTN_DIS_T}; }}

/* ── Botão "marcar tempo" (cinza, captura vídeo atual) ── */
QPushButton#mark {{
    background: {_GRAY_BTN}; color: {_TEXT};
    font-size: 13px; font-weight: bold;
    padding: 0 14px; min-width: 96px; min-height: 42px;
    border-radius: 6px;
    text-align: center;
}}
QPushButton#mark:hover    {{ background: {_GRAY_HOV}; }}
QPushButton#mark:disabled {{ background: {_BTN_DIS}; color: {_BTN_DIS_T}; }}

/* ── Botão secundário cinza ── */
QPushButton#gray {{
    background: {_GRAY_BTN}; color: {_TEXT};
    font-weight: normal;
}}
QPushButton#gray:hover    {{ background: {_GRAY_HOV}; }}
QPushButton#gray:disabled {{ background: {_BTN_DIS}; color: {_BTN_DIS_T}; }}

/* ── Botão cancelar (vermelho transparente, ícone) ── */
QPushButton#cancel {{
    background: transparent; color: {_TEXT_SUB};
    border: 1px solid {_BORDER}; border-radius: 5px;
    padding: 7px 12px; font-weight: normal;
}}
QPushButton#cancel:hover {{
    background: {_RED}; color: #fff; border: 1px solid {_RED};
}}
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

_HIDE_CHAT_JS = """
(function tryHideChat(n) {
    var frame = document.querySelector('ytd-live-chat-frame');
    if (frame) {
        if (frame.hasAttribute('collapsed')) return;          // já fechado
        var btn = frame.querySelector('#show-hide-button button');
        if (btn) { try { btn.click(); } catch (e) {} return; }
    }
    if (n > 0) setTimeout(function() { tryHideChat(n - 1); }, 700);
})(25);
"""


# ---------------------------------------------------------------------------
# Helpers de construção de widgets
# ---------------------------------------------------------------------------

def _vsep() -> QFrame:
    """Separador vertical fino para dividir blocos no card."""
    f = QFrame()
    f.setObjectName("vsep")
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedWidth(1)
    return f


def _time_block(caption: str, entry: QLineEdit, mark_btn: QPushButton) -> QWidget:
    """Bloco vertical: label de seção + entry monoespaçado + botão de marcar."""
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    v = QVBoxLayout(container)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)

    cap = QLabel(caption)
    cap.setObjectName("caption")
    v.addWidget(cap)

    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(entry)
    row.addWidget(mark_btn)
    v.addLayout(row)

    return container


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
        self.setMinimumSize(960, 640)
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
        panel_layout.setContentsMargins(20, 14, 20, 14)
        panel_layout.setSpacing(12)

        # ── linha 1: título + contador ──────────────────────────────────────
        header_row = QHBoxLayout()
        self._title_lbl = QLabel("")
        self._title_lbl.setObjectName("title")
        self._title_lbl.setWordWrap(False)
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Preferred)
        self._counter_lbl = QLabel("")
        self._counter_lbl.setObjectName("counter")
        header_row.addWidget(self._title_lbl, stretch=1)
        header_row.addWidget(self._counter_lbl)
        panel_layout.addLayout(header_row)

        # ── card de marcação de trecho ──────────────────────────────────────
        card = QFrame()
        card.setObjectName("card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(18, 14, 18, 14)
        card_layout.setSpacing(20)

        # Início
        self._start_entry = QLineEdit("00:00:00")
        self._start_entry.setObjectName("time")
        self._start_entry.setFixedWidth(150)
        self._start_entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._start_entry.textChanged.connect(self._update_duration)

        self._btn_mark_start = QPushButton("⏱  Marcar")
        self._btn_mark_start.setObjectName("mark")
        self._btn_mark_start.setToolTip("Capturar tempo atual do vídeo como Início")
        self._btn_mark_start.setEnabled(False)
        self._btn_mark_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mark_start.clicked.connect(lambda: self._mark("start"))

        card_layout.addWidget(_time_block("INÍCIO", self._start_entry, self._btn_mark_start))
        card_layout.addWidget(_vsep())

        # Fim
        self._end_entry = QLineEdit("00:00:00")
        self._end_entry.setObjectName("time")
        self._end_entry.setFixedWidth(150)
        self._end_entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._end_entry.textChanged.connect(self._update_duration)

        self._btn_mark_end = QPushButton("⏱  Marcar")
        self._btn_mark_end.setObjectName("mark")
        self._btn_mark_end.setToolTip("Capturar tempo atual do vídeo como Fim")
        self._btn_mark_end.setEnabled(False)
        self._btn_mark_end.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_mark_end.clicked.connect(lambda: self._mark("end"))

        card_layout.addWidget(_time_block("FIM", self._end_entry, self._btn_mark_end))
        card_layout.addWidget(_vsep())

        # Duração
        dur_box = QWidget()
        dur_box.setStyleSheet("background: transparent;")
        dur_v = QVBoxLayout(dur_box)
        dur_v.setContentsMargins(0, 0, 0, 0)
        dur_v.setSpacing(6)
        dur_cap = QLabel("DURAÇÃO")
        dur_cap.setObjectName("caption")
        self._dur_lbl = QLabel("--:--:--")
        self._dur_lbl.setObjectName("duration")
        self._dur_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        dur_v.addWidget(dur_cap)
        dur_v.addWidget(self._dur_lbl)
        card_layout.addWidget(dur_box, stretch=1)

        panel_layout.addWidget(card)

        # ── linha 3: status (esquerda) + ações (direita) ─────────────────────
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self._dot = QLabel("●")
        self._dot.setObjectName("dot")
        self._dot.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 13px;")
        self._status_lbl = QLabel("Carregando vídeo...")
        self._status_lbl.setObjectName("status")
        action_row.addWidget(self._dot)
        action_row.addWidget(self._status_lbl, stretch=1)

        self._btn_cancel = QPushButton("✕  Cancelar")
        self._btn_cancel.setObjectName("cancel")
        self._btn_cancel.setToolTip("Cancelar e fechar")
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.clicked.connect(self._cancel)
        action_row.addWidget(self._btn_cancel)

        self._btn_full = QPushButton("Usar vídeo completo")
        self._btn_full.setObjectName("gray")
        self._btn_full.setEnabled(False)
        self._btn_full.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_full.clicked.connect(self._use_full)
        action_row.addWidget(self._btn_full)

        self._btn_confirm = QPushButton("Confirmar trecho  →")
        self._btn_confirm.setEnabled(False)
        self._btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_confirm.clicked.connect(self._confirm)
        action_row.addWidget(self._btn_confirm)

        panel_layout.addLayout(action_row)

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
        self._set_status("Carregando vídeo...", _TEXT_MUTED)
        self._set_controls_enabled(False)
        self._view.load(QUrl(f"https://www.youtube.com/watch?v={video['id']}"))

    # -----------------------------------------------------------------------
    # Callbacks do webview
    # -----------------------------------------------------------------------

    def _on_loaded(self, ok: bool):
        if not ok:
            self._set_status("Erro ao carregar o vídeo.", _RED)
            self._set_controls_enabled(True)
            return
        self._set_status(
            "Pronto — assista e clique em ⏱ Marcar para capturar Início e Fim.",
            _GREEN,
        )
        self._ready = True
        self._set_controls_enabled(True)
        QTimer.singleShot(800,  self._hide_chat)
        QTimer.singleShot(2500, self._activate_theater)
        QTimer.singleShot(3000, self._inject_overlay)

    def _activate_theater(self):
        self._view.page().runJavaScript(_THEATER_JS)

    def _inject_overlay(self):
        self._view.page().runJavaScript(_OVERLAY_JS)

    def _hide_chat(self):
        self._view.page().runJavaScript(_HIDE_CHAT_JS)

    # -----------------------------------------------------------------------
    # Marcação de tempo via runJavaScript
    # -----------------------------------------------------------------------

    def _mark(self, target: str):
        def _got_time(t):
            try:
                if t is None or t < 0:
                    self._set_status("Vídeo não encontrado na página.", _YELLOW)
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
                self._set_status(f"Erro ao marcar tempo: {e}", _RED)

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
            self._dur_lbl.setStyleSheet(f"color: {_GREEN};")
        else:
            self._dur_lbl.setText("--:--:--")
            self._dur_lbl.setStyleSheet(f"color: {_TEXT_MUTED};")

    # -----------------------------------------------------------------------
    # Ações do usuário
    # -----------------------------------------------------------------------

    def _confirm(self):
        start_str = self._start_entry.text().strip()
        end_str   = self._end_entry.text().strip()
        start_s   = _hms_to_seconds(start_str)
        end_s     = _hms_to_seconds(end_str)
        if start_s is None or end_s is None:
            self._set_status("Tempo inválido — use HH:MM:SS.", _RED)
            return
        if end_s <= start_s:
            self._set_status("O tempo de fim deve ser maior que o início.", _RED)
            return
        if start_s == 0 and end_s == 0:
            self._set_status(
                "Informe o trecho ou clique em 'Usar vídeo completo'.", _RED
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

    def _set_status(self, text: str, color: str = _TEXT_SUB):
        self._status_lbl.setText(text)
        self._status_lbl.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._dot.setStyleSheet(f"color: {color}; font-size: 13px;")


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
