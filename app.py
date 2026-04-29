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
import urllib.request
from datetime import datetime

from PyQt6.QtCore import QDate, QTimer, Qt
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea,
    QStackedWidget, QVBoxLayout, QWidget,
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
# Paleta de cores — única fonte da verdade
# ---------------------------------------------------------------------------
class _Palette:
    # Semântica
    GREEN        = "#2ea84f"   # ação principal
    GREEN_HOVER  = "#37c15e"   # hover primário
    GREEN_DIM    = "#1c6630"   # pulse escuro do dot
    RED          = "#c0392b"
    RED_HOVER    = "#e74c3c"
    ERROR        = "#e05252"
    WARN         = "#e0a020"
    WARN_LABEL   = "#f0a830"
    WARN_BTN_BG  = "#c87800"
    HINT         = "#888"      # texto secundário neutro (legível em dark e light)

    # Dark (prefixo D_)
    D_BG         = "#1e1e1e"
    D_SIDEBAR    = "#161616"
    D_CARD       = "#272727"
    D_CARD2      = "#222222"
    D_INPUT      = "#2c2c2c"
    D_SEP        = "#2c2c2c"
    D_LOG        = "#181818"
    D_BORDER     = "#272727"
    D_TEXT       = "#f0f0f0"
    D_TEXT_SUB   = "#777"
    D_TEXT_BRAND = "#bbb"
    D_TEXT_VER   = "#383838"
    D_GRAY_BTN   = "#444"
    D_GRAY_HOV   = "#555"
    D_GRAY_TEXT  = "#ccc"
    D_GRAY_HTEXT = "#eee"
    D_SCROLL_T   = "#1e1e1e"
    D_SCROLL_H   = "#444"
    D_THUMB      = "#191919"
    D_WARN_BG    = "#5a3500"
    D_HOVER_NAV  = "#232323"
    D_HOVER_THEME = "#252525"
    D_HOVER_ICON = "#333"
    D_BTN_DIS    = "#333"
    D_BTN_DIS_T  = "#555"
    D_CAN_DIS    = "#3a3a3a"
    D_CAN_DIS_T  = "#666"

    # Light (prefixo L_)
    L_BG         = "#ffffff"
    L_SIDEBAR    = "#f3f3f3"
    L_CARD       = "#f7f7f7"
    L_CARD2      = "#fafafa"
    L_CARD_BD    = "#e8e8e8"
    L_INPUT      = "#ffffff"
    L_INPUT_BD   = "#d0d0d0"
    L_SEP        = "#e4e4e4"
    L_LOG        = "#f8f8f8"
    L_BORDER     = "#e0e0e0"
    L_TEXT       = "#1a1a1a"
    L_TEXT_SUB   = "#666"
    L_TEXT_BRAND = "#666"
    L_TEXT_VER   = "#aaa"
    L_GRAY_BTN   = "#e0e0e0"
    L_GRAY_HOV   = "#d0d0d0"
    L_GRAY_TEXT  = "#333"
    L_GRAY_HTEXT = "#111"
    L_SCROLL_T   = "#f0f0f0"
    L_SCROLL_H   = "#c0c0c0"
    L_THUMB      = "#e8e8e8"
    L_WARN_BG    = "#fff3cd"
    L_WARN_BD    = "#ffd060"
    L_HOVER_NAV  = "#eaeaea"
    L_HOVER_THEME = "#e8e8e8"
    L_HOVER_ICON = "#e8e8e8"
    L_BTN_DIS    = "#d8d8d8"
    L_BTN_DIS_T  = "#aaa"
    L_CAN_DIS    = "#e0e0e0"
    L_CAN_DIS_T  = "#aaa"


P = _Palette  # alias curto para uso nos QSS


# ---------------------------------------------------------------------------
# Stylesheet — Modo Escuro
# ---------------------------------------------------------------------------
_QSS_DARK = f"""
QMainWindow, QWidget {{
    background-color: {P.D_BG};
    color: {P.D_TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QLabel  {{ background: transparent; color: {P.D_TEXT}; }}
QDialog {{ background-color: {P.D_BG}; }}

/* ── Sidebar ── */
QWidget#sidebar {{
    background-color: {P.D_SIDEBAR};
    border-right: 1px solid {P.D_BORDER};
}}
QPushButton#nav_btn {{
    background: transparent; color: {P.D_TEXT_SUB};
    text-align: left; padding: 0 0 0 20px;
    border: none; border-left: 3px solid transparent;
    border-radius: 0; font-size: 13px; font-weight: normal; min-height: 44px;
}}
QPushButton#nav_btn:hover {{ background: {P.D_HOVER_NAV}; color: {P.D_TEXT_BRAND}; }}
QPushButton#theme_btn {{
    background: transparent; color: {P.D_BTN_DIS_T};
    border: none; border-radius: 4px;
    font-size: 18px; padding: 4px;
    min-height: 32px;
}}
QPushButton#theme_btn:hover {{ background: {P.D_HOVER_THEME}; color: {P.L_TEXT_VER}; }}

/* ── Inputs ── */
QLineEdit {{
    background: {P.D_INPUT}; color: {P.D_TEXT};
    border: 1px solid {P.D_GRAY_BTN}; border-radius: 5px; padding: 5px 9px;
}}
QLineEdit:focus {{ border: 1px solid {P.GREEN}; }}

/* ── Buttons ── */
QPushButton {{
    background: {P.GREEN}; color: #fff;
    border: none; border-radius: 5px; padding: 6px 18px;
}}
QPushButton:hover    {{ background: {P.GREEN_HOVER}; }}
QPushButton:disabled {{ background: {P.D_BTN_DIS}; color: {P.D_BTN_DIS_T}; }}
QPushButton#cancel_btn          {{ background: {P.RED}; }}
QPushButton#cancel_btn:hover    {{ background: {P.RED_HOVER}; }}
QPushButton#cancel_btn:disabled {{ background: {P.D_CAN_DIS}; color: {P.D_CAN_DIS_T}; }}
QPushButton#icon_btn {{
    background: transparent; font-size: 16px;
    border: none; border-radius: 4px; padding: 4px 8px;
}}
QPushButton#icon_btn:hover {{ background: {P.D_HOVER_ICON}; }}
QPushButton#gray_btn       {{ background: {P.D_GRAY_BTN}; color: {P.D_GRAY_TEXT}; }}
QPushButton#gray_btn:hover {{ background: {P.D_GRAY_HOV}; color: {P.D_GRAY_HTEXT}; }}
QPushButton#red_btn        {{ background: {P.RED}; }}
QPushButton#red_btn:hover  {{ background: {P.RED_HOVER}; }}

/* ── Progress ── */
QProgressBar {{
    background: {P.D_INPUT}; border: none;
    border-radius: 3px; max-height: 12px;
}}
QProgressBar::chunk {{ background: {P.GREEN}; border-radius: 3px; }}

/* ── Log ── */
QPlainTextEdit {{
    background: {P.D_LOG}; color: #c0c0c0;
    border: 1px solid {P.D_SEP}; border-radius: 5px;
    font-family: Consolas, monospace; font-size: 11px;
}}

/* ── Frames / cards ── */
QFrame#auth_banner {{ background: {P.D_WARN_BG}; border-radius: 8px; }}
QFrame#date_frame  {{ background: {P.D_CARD}; border-radius: 8px; }}
QFrame#section_sep {{ background: {P.D_SEP}; }}
QFrame#card        {{ background: {P.D_CARD}; border-radius: 8px; }}
QFrame#cfg_card    {{ background: {P.D_CARD2}; border-radius: 8px; border: 1px solid {P.D_SEP}; }}

/* ── Scroll ── */
QScrollArea             {{ border: none; background: transparent; }}
QWidget#scroll_contents {{ background: transparent; }}
QScrollBar:vertical {{ background: {P.D_SCROLL_T}; width: 6px; border-radius: 3px; }}
QScrollBar::handle:vertical {{ background: {P.D_SCROLL_H}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* ── Thumb ── */
QLabel#thumb {{ background: {P.D_THUMB}; border-radius: 5px; color: {P.D_GRAY_BTN}; font-size: 20px; }}
"""

# ---------------------------------------------------------------------------
# Stylesheet — Modo Claro
# ---------------------------------------------------------------------------
_QSS_LIGHT = f"""
QMainWindow, QWidget {{
    background-color: {P.L_BG};
    color: {P.L_TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QLabel  {{ background: transparent; color: {P.L_TEXT}; }}
QDialog {{ background-color: {P.L_BG}; }}

/* ── Sidebar ── */
QWidget#sidebar {{
    background-color: {P.L_SIDEBAR};
    border-right: 1px solid {P.L_BORDER};
}}
QPushButton#nav_btn {{
    background: transparent; color: {P.L_TEXT_SUB};
    text-align: left; padding: 0 0 0 20px;
    border: none; border-left: 3px solid transparent;
    border-radius: 0; font-size: 13px; font-weight: normal; min-height: 44px;
}}
QPushButton#nav_btn:hover {{ background: {P.L_HOVER_NAV}; color: {P.L_GRAY_TEXT}; }}
QPushButton#theme_btn {{
    background: transparent; color: {P.L_TEXT_VER};
    border: none; border-radius: 4px;
    font-size: 18px; padding: 4px;
    min-height: 32px;
}}
QPushButton#theme_btn:hover {{ background: {P.L_HOVER_THEME}; color: {P.L_TEXT_SUB}; }}

/* ── Inputs ── */
QLineEdit {{
    background: {P.L_INPUT}; color: {P.L_TEXT};
    border: 1px solid {P.L_INPUT_BD}; border-radius: 5px; padding: 5px 9px;
}}
QLineEdit:focus {{ border: 1px solid {P.GREEN}; }}

/* ── Buttons ── */
QPushButton {{
    background: {P.GREEN}; color: #fff;
    border: none; border-radius: 5px; padding: 6px 18px;
}}
QPushButton:hover    {{ background: {P.GREEN_HOVER}; }}
QPushButton:disabled {{ background: {P.L_BTN_DIS}; color: {P.L_BTN_DIS_T}; }}
QPushButton#cancel_btn          {{ background: {P.RED}; }}
QPushButton#cancel_btn:hover    {{ background: {P.RED_HOVER}; }}
QPushButton#cancel_btn:disabled {{ background: {P.L_CAN_DIS}; color: {P.L_CAN_DIS_T}; }}
QPushButton#icon_btn {{
    background: transparent; font-size: 16px;
    border: none; border-radius: 4px; padding: 4px 8px;
}}
QPushButton#icon_btn:hover {{ background: {P.L_HOVER_ICON}; }}
QPushButton#gray_btn       {{ background: {P.L_GRAY_BTN}; color: {P.L_GRAY_TEXT}; }}
QPushButton#gray_btn:hover {{ background: {P.L_GRAY_HOV}; color: {P.L_GRAY_HTEXT}; }}
QPushButton#red_btn        {{ background: {P.RED}; color: #fff; }}
QPushButton#red_btn:hover  {{ background: {P.RED_HOVER}; }}

/* ── Progress ── */
QProgressBar {{
    background: {P.L_CARD_BD}; border: none;
    border-radius: 3px; max-height: 12px;
}}
QProgressBar::chunk {{ background: {P.GREEN}; border-radius: 3px; }}

/* ── Log ── */
QPlainTextEdit {{
    background: {P.L_LOG}; color: {P.L_GRAY_TEXT};
    border: 1px solid {P.L_BORDER}; border-radius: 5px;
    font-family: Consolas, monospace; font-size: 11px;
}}

/* ── Frames / cards ── */
QFrame#auth_banner {{ background: {P.L_WARN_BG}; border-radius: 8px; border: 1px solid {P.L_WARN_BD}; }}
QFrame#date_frame  {{ background: {P.L_CARD}; border-radius: 8px; border: 1px solid {P.L_CARD_BD}; }}
QFrame#section_sep {{ background: {P.L_SEP}; }}
QFrame#card        {{ background: {P.L_CARD}; border-radius: 8px; border: 1px solid {P.L_CARD_BD}; }}
QFrame#cfg_card    {{ background: {P.L_CARD2}; border-radius: 8px; border: 1px solid {P.L_SEP}; }}

/* ── Scroll ── */
QScrollArea             {{ border: none; background: transparent; }}
QWidget#scroll_contents {{ background: transparent; }}
QScrollBar:vertical {{ background: {P.L_SCROLL_T}; width: 6px; border-radius: 3px; }}
QScrollBar::handle:vertical {{ background: {P.L_SCROLL_H}; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* ── Thumb ── */
QLabel#thumb {{ background: {P.L_THUMB}; border-radius: 5px; color: {P.L_TEXT_VER}; font-size: 20px; }}
"""

# Estilos de nav ativo/inativo por tema (aplicados inline em _switch_page)
_NAV_ACTIVE = {
    True: (   # dark
        f"background: {P.D_HOVER_NAV}; color: {P.D_TEXT}; "
        f"text-align: left; padding: 0 0 0 17px; "
        f"border: none; border-left: 3px solid {P.GREEN}; "
        f"border-radius: 0; font-size: 13px; font-weight: bold; min-height: 44px;"
    ),
    False: (   # light
        f"background: {P.L_HOVER_NAV}; color: {P.L_TEXT}; "
        f"text-align: left; padding: 0 0 0 17px; "
        f"border: none; border-left: 3px solid {P.GREEN}; "
        f"border-radius: 0; font-size: 13px; font-weight: bold; min-height: 44px;"
    ),
}
_NAV_IDLE = {
    True: (   # dark
        f"background: transparent; color: {P.D_TEXT_SUB}; "
        f"text-align: left; padding: 0 0 0 20px; "
        f"border: none; border-left: 3px solid transparent; "
        f"border-radius: 0; font-size: 13px; font-weight: normal; min-height: 44px;"
    ),
    False: (   # light
        f"background: transparent; color: {P.L_TEXT_SUB}; "
        f"text-align: left; padding: 0 0 0 20px; "
        f"border: none; border-left: 3px solid transparent; "
        f"border-radius: 0; font-size: 13px; font-weight: normal; min-height: 44px;"
    ),
}


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
# Calendário customizado — QLabel clicável (evita problemas de cascade do
# QPushButton com o Fusion style que impedia a renderização do texto)
# ---------------------------------------------------------------------------
class _DayCell(QLabel):
    """Célula de dia: QLabel com cursor de mão e callback de clique."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(38, 38)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cb = None

    def mousePressEvent(self, event):
        if self._cb and self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self._cb()
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Toggle de seleção (substitui QCheckBox — evita problemas de cascade do
# Fusion style que afetava cor e tamanho)
# ---------------------------------------------------------------------------
class _CheckCell(QLabel):
    """Toggle de seleção: QLabel estilizado como checkbox verde/cinza."""

    def __init__(self):
        super().__init__("✓")
        self._checked = True
        self.setFixedSize(28, 28)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh()

    def isChecked(self) -> bool:
        return self._checked

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self._refresh()
        super().mousePressEvent(event)

    def _refresh(self):
        if self._checked:
            self.setStyleSheet(
                f"color: #fff; font-size: 15px; font-weight: bold;"
                f"background: {P.GREEN}; border-radius: 7px;"
            )
        else:
            self.setStyleSheet(
                f"color: transparent; font-size: 15px;"
                f"background: transparent;"
                f"border: 2px solid {P.HINT}; border-radius: 7px;"
            )


class _CalendarDialog(QDialog):

    _MONTHS = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
    ]
    _DOW = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"]

    def __init__(self, parent=None, initial_date: QDate = None, dark_mode: bool = True):
        super().__init__(parent)
        self.setWindowTitle("Selecionar data")
        self.setFixedSize(296, 358)
        self._selected  = initial_date or QDate.currentDate()
        self._viewing   = QDate(self._selected.year(), self._selected.month(), 1)
        self._dark_mode = dark_mode
        self._build_ui()
        self._render()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(6)

        # ── Navegação de mês ────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(0)

        self._prev_btn = QPushButton("‹")
        self._prev_btn.setObjectName("icon_btn")
        self._prev_btn.setFixedSize(32, 32)
        self._prev_btn.clicked.connect(self._prev_month)

        self._month_lbl = QLabel()
        self._month_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._month_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")

        self._next_btn = QPushButton("›")
        self._next_btn.setObjectName("icon_btn")
        self._next_btn.setFixedSize(32, 32)
        self._next_btn.clicked.connect(self._next_month)

        hdr.addWidget(self._prev_btn)
        hdr.addWidget(self._month_lbl, stretch=1)
        hdr.addWidget(self._next_btn)
        root.addLayout(hdr)

        # ── Cabeçalho dos dias da semana ────────────────────────────────────
        dow_row = QHBoxLayout()
        dow_row.setSpacing(2)
        for d in self._DOW:
            lbl = QLabel(d)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedWidth(38)
            lbl.setStyleSheet(
                f"color: {P.HINT}; font-size: 10px; font-weight: bold;"
            )
            dow_row.addWidget(lbl)
        root.addLayout(dow_row)

        # Separador
        sep = QFrame()
        sep.setObjectName("section_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        # ── Grade 6 × 7 de _DayCell ─────────────────────────────────────────
        self._grid = QGridLayout()
        self._grid.setSpacing(2)
        self._grid.setContentsMargins(0, 2, 0, 2)

        self._cells: list[list[_DayCell]] = []
        for row in range(6):
            row_cells: list[_DayCell] = []
            for col in range(7):
                cell = _DayCell()
                self._grid.addWidget(cell, row, col)
                row_cells.append(cell)
            self._cells.append(row_cells)
        root.addLayout(self._grid)

        root.addStretch()

        # ── Confirmar ───────────────────────────────────────────────────────
        confirm = QPushButton("Confirmar")
        confirm.setStyleSheet("font-weight: bold; padding: 7px;")
        confirm.clicked.connect(self.accept)
        root.addWidget(confirm)

    def _render(self):
        import calendar as _cal

        yr    = self._viewing.year()
        mo    = self._viewing.month()
        today = QDate.currentDate()
        txt   = P.D_TEXT if self._dark_mode else P.L_TEXT

        self._month_lbl.setText(f"{self._MONTHS[mo - 1]}  {yr}")

        weeks = _cal.Calendar(firstweekday=6).monthdayscalendar(yr, mo)

        # Faixa discreta na coluna do domingo (col 0)
        sun_bg = "rgba(255, 90, 90, 0.07)"

        for row in range(6):
            for col in range(7):
                cell = self._cells[row][col]
                cell._cb = None
                is_sun = (col == 0)

                if row < len(weeks) and weeks[row][col] != 0:
                    day  = weeks[row][col]
                    date = QDate(yr, mo, day)
                    is_sel   = (date == self._selected)
                    is_today = (date == today)

                    cell.setText(str(day))
                    cell.setVisible(True)
                    cell.setEnabled(True)

                    if is_sel:
                        cell.setStyleSheet(
                            f"color: #fff; font-size: 13px; font-weight: bold;"
                            f"background: {P.GREEN}; border-radius: 19px;"
                        )
                    elif is_today:
                        cell.setStyleSheet(
                            f"color: {P.GREEN}; font-size: 13px; font-weight: bold;"
                            f"background: {sun_bg if is_sun else 'transparent'};"
                            f"border: 2px solid {P.GREEN}; border-radius: 19px;"
                        )
                    else:
                        bg = sun_bg if is_sun else "transparent"
                        cell.setStyleSheet(
                            f"color: {txt}; font-size: 13px;"
                            f"background: {bg}; border: none;"
                        )

                    cell._cb = lambda d=date: self._select(d)
                else:
                    cell.setText("")
                    cell.setVisible(False)
                    cell.setEnabled(False)

    def _select(self, date: QDate):
        self._selected = date
        self._render()

    def _prev_month(self):
        self._viewing = self._viewing.addMonths(-1)
        self._render()

    def _next_month(self):
        self._viewing = self._viewing.addMonths(1)
        self._render()

    def selected_date(self) -> QDate:
        return self._selected


# ---------------------------------------------------------------------------
# Helpers de thumbnail — nível de módulo para facilitar mock nos testes
# ---------------------------------------------------------------------------

def _ssl_ctx():
    """Contexto SSL sem verificação de certificado.

    Necessário em redes corporativas com proxies de inspeção SSL (MITM),
    onde o certificado do servidor intermediário não é reconhecido pela
    cadeia padrão do Python.
    """
    import ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _try_cdn_thumbnail(video_id: str):
    """Tenta baixar thumbnail do YouTube CDN em múltiplas qualidades.

    Retorna ``bytes`` com a imagem ou ``None`` se todas as tentativas falharem.
    Imagens menores que 500 bytes são descartadas (placeholders de 404).
    Usa contexto SSL sem verificação para lidar com proxies corporativos.
    """
    ctx = _ssl_ctx()
    for quality in ("maxresdefault", "hqdefault", "mqdefault", "sddefault", "default"):
        try:
            url = f"https://img.youtube.com/vi/{video_id}/{quality}.jpg"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
                data = bytes(resp.read())
            if len(data) > 500:   # filtra placeholder de 404 (<500 B)
                return data
        except Exception:
            continue
    return None


def _try_ytdlp_thumbnail(video_id: str):
    """Extrai frame de thumbnail baixando ~10 s de vídeo com yt-dlp + ffmpeg.

    Usa exatamente o mesmo caminho de rede do download de áudio
    (--extractor-args youtube:player_client=ios,android,web + format 18),
    que é comprovadamente funcional neste ambiente.
    Nenhuma requisição HTTP direta ao CDN do YouTube é realizada.

    Fluxo:
      1. yt-dlp baixa os primeiros 10 segundos do vídeo (05:00-05:10) em formato
         18 (MP4 com áudio) para um diretório temporário.
      2. ffmpeg extrai 1 frame (-vframes 1) como JPEG.
      3. Os bytes do JPEG são retornados; arquivos temporários são limpos.

    Retorna ``bytes`` com a imagem JPEG ou ``None`` em qualquer falha.
    """
    import subprocess
    import tempfile
    from infrastructure.youtube._utils import ytdlp_exe, ffmpeg_dir

    try:
        ytdlp = ytdlp_exe()
        ffmpeg_bin = os.path.join(ffmpeg_dir(), "ffmpeg.exe") if sys.platform == "win32" \
            else "ffmpeg"
        flags = 0x08000000 if sys.platform == "win32" else 0
        url = f"https://www.youtube.com/watch?v={video_id}"

        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = os.path.join(tmpdir, "clip.mp4")
            frame_path = os.path.join(tmpdir, "thumb.jpg")

            # Passo 1: baixar ~10 s do vídeo no mesmo formato do download de áudio
            subprocess.run(
                [ytdlp,
                 "--download-sections", "*00:05:00-00:05:10",
                 "-f", "18",
                 "--no-playlist",
                 "--extractor-args", "youtube:player_client=ios,android,web",
                 "--encoding", "utf-8",
                 "--output", video_path,
                 url],
                capture_output=True, timeout=60,
                creationflags=flags,
            )

            if not os.path.isfile(video_path) or os.path.getsize(video_path) < 1000:
                return None

            # Passo 2: extrair 1 frame com ffmpeg
            subprocess.run(
                [ffmpeg_bin,
                 "-y", "-i", video_path,
                 "-vframes", "1",
                 "-q:v", "2",
                 frame_path],
                capture_output=True, timeout=15,
                creationflags=flags,
            )

            if os.path.isfile(frame_path) and os.path.getsize(frame_path) > 500:
                with open(frame_path, "rb") as fh:
                    return fh.read()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Janela principal
# ---------------------------------------------------------------------------
class App(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPMadalena — Cultos para o Drive")
        self.setFixedSize(900, 680)

        _icon = os.path.join(
            getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))),
            "icon.ico",
        )
        self._icon_path = _icon if os.path.exists(_icon) else None
        if self._icon_path:
            self.setWindowIcon(QIcon(self._icon_path))

        # Estado interno
        self._queue             = queue.Queue()
        self._running           = False
        self._converting        = False
        self._cancel_event      = threading.Event()
        self._dot_pulsing       = False
        self._dot_pulse_bright  = True
        self._conv_value        = 0.0
        self._status_text_color = "gray"   # exposto para testes
        self._cfg_auth_running  = False
        self._dark_mode         = True     # tema inicial

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
    # Layout raiz — sidebar + stack
    # -----------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()
        root.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_processar_page())   # 0
        self._stack.addWidget(self._build_historico_page())   # 1
        self._stack.addWidget(self._build_config_page())      # 2

        self._switch_page(0)

    # -----------------------------------------------------------------------
    # Sidebar
    # -----------------------------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(170)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Logo ────────────────────────────────────────────────────────────
        logo_box = QWidget()
        logo_box.setFixedHeight(90)
        ll = QHBoxLayout(logo_box)
        ll.setContentsMargins(16, 0, 12, 0)
        ll.setSpacing(10)
        ll.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        logo_lbl = QLabel()
        logo_lbl.setFixedSize(36, 36)
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self._icon_path:
            pix = QIcon(self._icon_path).pixmap(36, 36)
            logo_lbl.setPixmap(pix)
        else:
            logo_lbl.setText("IPM")
            logo_lbl.setStyleSheet(
                f"font-size: 15px; font-weight: bold; color: {P.GREEN};"
            )
        ll.addWidget(logo_lbl)

        self._brand_label = QLabel("IP Madalena")
        self._brand_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._brand_label.setStyleSheet(
            f"color: {P.D_TEXT_BRAND}; font-size: 12px; font-weight: bold; letter-spacing: 0.5px;"
        )
        ll.addWidget(self._brand_label, stretch=1)
        layout.addWidget(logo_box)

        # Separador
        sep = QFrame()
        sep.setObjectName("section_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(6)

        # ── Navegação ───────────────────────────────────────────────────────
        self._nav_buttons = []
        nav_items = [
            ("▶", "Processar"),
            ("⏱", "Histórico"),
            ("⚙", "Configurações"),
        ]
        for idx, (icon, label) in enumerate(nav_items):
            btn = QPushButton(f"  {icon}   {label}")
            btn.setObjectName("nav_btn")
            btn.setFixedHeight(44)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda checked=False, i=idx: self._switch_page(i)
            )
            layout.addWidget(btn)
            self._nav_buttons.append(btn)

        layout.addStretch()

        # ── Alternador de tema ───────────────────────────────────────────────
        theme_row = QHBoxLayout()
        theme_row.setContentsMargins(16, 0, 16, 0)

        self._theme_btn = QPushButton("☀")
        self._theme_btn.setObjectName("theme_btn")
        self._theme_btn.setToolTip("Alternar modo claro / escuro")
        self._theme_btn.setFixedHeight(32)
        self._theme_btn.setFixedWidth(36)
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.clicked.connect(self._toggle_theme)
        theme_row.addWidget(self._theme_btn)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        # Versão
        ver = QLabel("v2.1.0")
        ver.setContentsMargins(16, 2, 0, 10)
        ver.setAlignment(Qt.AlignmentFlag.AlignLeft)
        ver.setStyleSheet(
            f"color: {P.D_TEXT_VER}; font-size: 10px;"
        )
        layout.addWidget(ver)

        return sidebar

    def _switch_page(self, idx: int):
        self._stack.setCurrentIndex(idx)
        active = _NAV_ACTIVE[self._dark_mode]
        idle   = _NAV_IDLE[self._dark_mode]
        for i, btn in enumerate(self._nav_buttons):
            btn.setStyleSheet(active if i == idx else idle)
        self._current_page = idx

        if idx == 1:
            self._refresh_history()
        elif idx == 2:
            self._refresh_config_auth()

    def _toggle_theme(self):
        """Alterna entre modo escuro e modo claro."""
        self._dark_mode = not self._dark_mode
        qss = _QSS_DARK if self._dark_mode else _QSS_LIGHT
        QApplication.instance().setStyleSheet(qss)

        # Atualiza ícone do botão
        self._theme_btn.setText("☀" if self._dark_mode else "🌙")

        # Atualiza cor do brand label (inline, fora do QSS)
        brand_color = P.D_TEXT_BRAND if self._dark_mode else P.L_TEXT_BRAND
        self._brand_label.setStyleSheet(
            f"color: {brand_color}; font-size: 12px; font-weight: bold; letter-spacing: 0.5px;"
        )

        # Reaplica estilos inline do nav
        page = getattr(self, "_current_page", 0)
        self._switch_page(page)

    # -----------------------------------------------------------------------
    # Página 0 — Processar
    # -----------------------------------------------------------------------
    def _build_processar_page(self) -> QWidget:
        PAD = 26
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PAD, 22, PAD, 22)
        layout.setSpacing(0)

        # ── Cabeçalho ──────────────────────────────────────────────────────
        title = QLabel("Processar culto")
        title.setStyleSheet("font-size: 19px; font-weight: bold;")
        layout.addWidget(title)
        layout.addSpacing(2)

        sub = QLabel(
            "Selecione a data e clique em Processar para buscar os cultos publicados"
        )
        sub.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        layout.addWidget(sub)
        layout.addSpacing(14)

        # ── Banner de autorização (oculto quando autorizado) ────────────────
        self._auth_banner = QFrame()
        self._auth_banner.setObjectName("auth_banner")
        ab = QHBoxLayout(self._auth_banner)
        ab.setContentsMargins(14, 8, 14, 8)
        ab_lbl = QLabel("⚠  Google Drive não autorizado")
        ab_lbl.setStyleSheet(f"font-weight: bold; color: {P.WARN_LABEL};")
        self._auth_btn = QPushButton("Autorizar")
        self._auth_btn.setStyleSheet(
            f"background: {P.WARN_BTN_BG}; padding: 4px 14px; border-radius: 4px;"
        )
        self._auth_btn.clicked.connect(self._start_auth)
        ab.addWidget(ab_lbl)
        ab.addStretch()
        ab.addWidget(self._auth_btn)
        self._auth_banner.hide()
        layout.addWidget(self._auth_banner)

        # ── Card de data ───────────────────────────────────────────────────
        date_frame = QFrame()
        date_frame.setObjectName("date_frame")
        dr = QHBoxLayout(date_frame)
        dr.setContentsMargins(16, 10, 16, 10)
        dr.setSpacing(8)

        dr.addWidget(QLabel("📅  Data do culto:"))

        self.date_entry = QLineEdit()
        self.date_entry.setPlaceholderText("DD/MM/AAAA")
        self.date_entry.setFixedWidth(130)
        dr.addWidget(self.date_entry)

        cal_btn = QPushButton("📅")
        cal_btn.setObjectName("icon_btn")
        cal_btn.setFixedWidth(38)
        cal_btn.clicked.connect(self._open_calendar)
        dr.addWidget(cal_btn)

        dr.addStretch()

        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.setObjectName("cancel_btn")
        self.cancel_btn.setFixedWidth(100)
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.hide()
        dr.addWidget(self.cancel_btn)

        self.run_btn = QPushButton("▶  Processar")
        self.run_btn.setStyleSheet("font-weight: bold; padding: 7px 18px;")
        self.run_btn.setFixedWidth(130)
        self.run_btn.clicked.connect(self._start)
        dr.addWidget(self.run_btn)

        layout.addWidget(date_frame)
        layout.addSpacing(14)

        # ── Separador ──────────────────────────────────────────────────────
        sep = QFrame()
        sep.setObjectName("section_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(10)

        # ── Status ─────────────────────────────────────────────────────────
        sr = QHBoxLayout()
        self._status_dot = QLabel("●")
        self._status_dot.setFixedWidth(16)
        self._status_dot.setStyleSheet("color: gray; font-size: 11px;")
        self.status_label = QLabel("Pronto")
        self.status_label.setStyleSheet("color: gray;")
        sr.addWidget(self._status_dot)
        sr.addWidget(self.status_label, stretch=1)
        layout.addLayout(sr)
        layout.addSpacing(8)

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
            lbl.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
            bar = _ProgressBar()
            stats = QLabel("")
            stats.setFixedWidth(190)
            stats.setStyleSheet(
                f"color: {P.HINT}; font-family: Consolas; font-size: 11px;"
            )
            row.addWidget(lbl)
            row.addWidget(bar, stretch=1)
            row.addWidget(stats)
            pfl.addLayout(row)
            return bar, stats

        self.download_bar,  self.download_stats     = _bar_row("Download")
        self.convert_bar,   self.convert_stats      = _bar_row("Conversão")
        self.progress_bar,  self.upload_stats_label = _bar_row("Upload")

        self._progress_frame.hide()
        layout.addWidget(self._progress_frame)

        # ── Log ────────────────────────────────────────────────────────────
        log_hdr = QLabel("Log de execução")
        log_hdr.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        layout.addWidget(log_hdr)
        layout.addSpacing(4)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        layout.addWidget(self.log_box, stretch=1)

        return page

    # -----------------------------------------------------------------------
    # Página 1 — Histórico
    # -----------------------------------------------------------------------
    def _build_historico_page(self) -> QWidget:
        PAD = 26
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PAD, 22, PAD, 22)
        layout.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("Histórico de processamentos")
        title.setStyleSheet("font-size: 19px; font-weight: bold;")
        refresh_btn = QPushButton("↻  Atualizar")
        refresh_btn.setObjectName("gray_btn")
        refresh_btn.setFixedWidth(120)
        refresh_btn.clicked.connect(self._refresh_history)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(refresh_btn)
        layout.addLayout(hdr)

        sub = QLabel("Datas já processadas e enviadas ao Google Drive")
        sub.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        layout.addWidget(sub)

        sep = QFrame()
        sep.setObjectName("section_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_container = QWidget()
        self._history_container.setObjectName("scroll_contents")
        self._history_layout = QVBoxLayout(self._history_container)
        self._history_layout.setSpacing(8)
        self._history_layout.setContentsMargins(0, 4, 0, 4)
        self._history_layout.addStretch()
        self._history_scroll.setWidget(self._history_container)
        layout.addWidget(self._history_scroll, stretch=1)

        return page

    def _refresh_history(self):
        while self._history_layout.count():
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        history = baixar_audio.load_history()
        if not history:
            empty = QLabel("Nenhum processamento registrado ainda.")
            empty.setStyleSheet(f"color: {P.HINT}; font-size: 13px; padding: 20px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._history_layout.addWidget(empty)
            self._history_layout.addStretch()
            return

        entries = sorted(history.items(), key=lambda x: x[0], reverse=True)
        for date_str, entry in entries:
            self._history_layout.addWidget(
                self._build_history_card(date_str, entry)
            )
        self._history_layout.addStretch()

    def _build_history_card(self, date_str: str, entry: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(5)

        hdr = QHBoxLayout()
        date_lbl = QLabel(f"📅  {date_str}")
        date_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        hdr.addWidget(date_lbl)

        processado_em = entry.get("processado_em", "")
        if processado_em:
            try:
                dt = datetime.fromisoformat(processado_em)
                processado_em = dt.strftime("Processado em %d/%m/%Y às %H:%M")
            except Exception:
                pass
            time_lbl = QLabel(processado_em)
            time_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
            hdr.addStretch()
            hdr.addWidget(time_lbl)
        layout.addLayout(hdr)

        for v in entry.get("videos", []):
            v_lbl = QLabel(f"  ▸  {v}")
            v_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
            layout.addWidget(v_lbl)

        return card

    # -----------------------------------------------------------------------
    # Página 2 — Configurações (inline, card-based)
    # -----------------------------------------------------------------------
    def _build_config_page(self) -> QWidget:
        PAD = 26
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PAD, 22, PAD, 22)
        layout.setSpacing(10)

        title = QLabel("Configurações")
        title.setStyleSheet("font-size: 19px; font-weight: bold;")
        layout.addWidget(title)

        sub = QLabel("Ajuste o canal, a pasta do Drive e a autorização Google")
        sub.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        layout.addWidget(sub)

        sep = QFrame()
        sep.setObjectName("section_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(4)

        # ── Card: Autorização Google Drive ──────────────────────────────────
        auth_card = QFrame()
        auth_card.setObjectName("cfg_card")
        ac = QVBoxLayout(auth_card)
        ac.setContentsMargins(20, 16, 20, 16)
        ac.setSpacing(8)

        tr = QHBoxLayout()
        tr.addWidget(self._icon_label("🔑", 22))
        lbl = QLabel("Autorização Google Drive")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr.addWidget(lbl)
        tr.addStretch()
        ac.addLayout(tr)

        hint = QLabel(
            "Permite que o app envie arquivos para o seu Google Drive."
        )
        hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        hint.setWordWrap(True)
        ac.addWidget(hint)

        sr = QHBoxLayout()
        self._cfg_auth_status_label = QLabel("")
        self._cfg_auth_action_btn = QPushButton("")
        self._cfg_auth_action_btn.setFixedWidth(110)
        self._cfg_auth_action_btn.clicked.connect(self._cfg_toggle_auth)
        sr.addWidget(self._cfg_auth_status_label, stretch=1)
        sr.addWidget(self._cfg_auth_action_btn)
        ac.addLayout(sr)
        layout.addWidget(auth_card)

        # ── Card: Canal do YouTube ──────────────────────────────────────────
        yt_card = QFrame()
        yt_card.setObjectName("cfg_card")
        yc = QVBoxLayout(yt_card)
        yc.setContentsMargins(20, 16, 20, 16)
        yc.setSpacing(8)

        tr2 = QHBoxLayout()
        tr2.addWidget(self._icon_label("📺", 22))
        lbl2 = QLabel("Canal do YouTube")
        lbl2.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr2.addWidget(lbl2)
        tr2.addStretch()
        yc.addLayout(tr2)

        cfg = baixar_audio.load_config()
        self._cfg_channel_entry = QLineEdit(cfg["channel_url"])
        yc.addWidget(self._cfg_channel_entry)

        yt_hint = QLabel("Ex: https://www.youtube.com/@SeuCanal/streams")
        yt_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        yc.addWidget(yt_hint)
        layout.addWidget(yt_card)

        # ── Card: Pasta do Google Drive ─────────────────────────────────────
        dr_card = QFrame()
        dr_card.setObjectName("cfg_card")
        dc = QVBoxLayout(dr_card)
        dc.setContentsMargins(20, 16, 20, 16)
        dc.setSpacing(8)

        tr3 = QHBoxLayout()
        tr3.addWidget(self._icon_label("📁", 22))
        lbl3 = QLabel("Pasta do Google Drive")
        lbl3.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr3.addWidget(lbl3)
        tr3.addStretch()
        dc.addLayout(tr3)

        self._cfg_folder_entry = QLineEdit(cfg["drive_folder_id"])
        dc.addWidget(self._cfg_folder_entry)

        dr_hint = QLabel(
            "ID da pasta raiz no Drive (encontrado no final da URL da pasta)"
        )
        dr_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        dc.addWidget(dr_hint)
        layout.addWidget(dr_card)

        layout.addStretch()

        # ── Salvar ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_save = QPushButton("💾  Salvar configurações")
        btn_save.setStyleSheet("font-weight: bold; padding: 8px 24px;")
        btn_save.clicked.connect(self._cfg_save)
        btn_row.addStretch()
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        self._cfg_feedback_label = QLabel("")
        self._cfg_feedback_label.setStyleSheet(
            f"color: {P.GREEN}; font-size: 11px;"
        )
        self._cfg_feedback_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._cfg_feedback_label)

        return page

    @staticmethod
    def _icon_label(icon: str, size: int = 20) -> QLabel:
        lbl = QLabel(icon)
        lbl.setStyleSheet(f"font-size: {size}px;")
        lbl.setFixedWidth(size + 10)
        return lbl

    def _refresh_config_auth(self):
        if baixar_audio.check_auth_status():
            self._cfg_auth_status_label.setText("✓  Autorizado")
            self._cfg_auth_status_label.setStyleSheet(
                f"color: {P.GREEN}; font-weight: bold;"
            )
            self._cfg_auth_action_btn.setText("Logout")
            self._cfg_auth_action_btn.setStyleSheet(
                f"background: {P.RED}; border-radius: 4px;"
            )
        else:
            self._cfg_auth_status_label.setText("✗  Não autorizado")
            self._cfg_auth_status_label.setStyleSheet(
                f"color: {P.ERROR}; font-weight: bold;"
            )
            self._cfg_auth_action_btn.setText("Autorizar")
            self._cfg_auth_action_btn.setStyleSheet(
                f"background: {P.GREEN}; border-radius: 4px;"
            )

    def _cfg_toggle_auth(self):
        if baixar_audio.check_auth_status():
            baixar_audio.logout_drive()
            self._refresh_config_auth()
            self._cfg_feedback_label.setText(
                "Logout realizado. Autorize novamente antes de processar."
            )
            self._cfg_feedback_label.setStyleSheet(
                f"color: {P.WARN}; font-size: 11px;"
            )
            self._check_auth_visibility()
        else:
            self._cfg_do_authorize()

    def _cfg_do_authorize(self):
        if self._cfg_auth_running:
            return
        self._cfg_auth_running = True
        self._cfg_auth_action_btn.setEnabled(False)
        self._cfg_auth_action_btn.setText("Autorizando...")
        threading.Thread(target=self._cfg_auth_worker, daemon=True).start()

    def _cfg_auth_worker(self):
        try:
            baixar_audio.run_auth()
            QTimer.singleShot(0, self._cfg_on_auth_done)
        except Exception as e:
            QTimer.singleShot(0, lambda: self._cfg_on_auth_error(str(e)))

    def _cfg_on_auth_done(self):
        self._cfg_auth_running = False
        self._cfg_auth_action_btn.setEnabled(True)
        self._refresh_config_auth()
        self._cfg_feedback_label.setText("Google Drive autorizado com sucesso!")
        self._cfg_feedback_label.setStyleSheet(f"color: {P.GREEN}; font-size: 11px;")
        self._check_auth_visibility()

    def _cfg_on_auth_error(self, msg: str):
        self._cfg_auth_running = False
        self._cfg_auth_action_btn.setEnabled(True)
        self._refresh_config_auth()
        self._cfg_feedback_label.setText(f"Erro na autorização: {msg}")
        self._cfg_feedback_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")

    def _cfg_save(self):
        channel = self._cfg_channel_entry.text().strip()
        folder  = self._cfg_folder_entry.text().strip()
        if not channel:
            self._cfg_feedback_label.setText("URL do canal não pode estar vazia.")
            self._cfg_feedback_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")
            return
        if not folder:
            self._cfg_feedback_label.setText("ID da pasta não pode estar vazio.")
            self._cfg_feedback_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")
            return
        baixar_audio.save_config(channel_url=channel, drive_folder_id=folder)
        self._cfg_feedback_label.setText("Configurações salvas com sucesso!")
        self._cfg_feedback_label.setStyleSheet(f"color: {P.GREEN}; font-size: 11px;")

    # -----------------------------------------------------------------------
    # Calendário popup
    # -----------------------------------------------------------------------
    def _open_calendar(self):
        initial = QDate.currentDate()
        try:
            d = datetime.strptime(self.date_entry.text().strip(), "%d/%m/%Y")
            initial = QDate(d.year, d.month, d.day)
        except ValueError:
            pass

        dlg = _CalendarDialog(self, initial_date=initial, dark_mode=self._dark_mode)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.date_entry.setText(dlg.selected_date().toString("dd/MM/yyyy"))

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

                elif kind == "thumbnail":
                    _lbl, _data = value
                    try:
                        _pix = QPixmap()
                        _pix.loadFromData(_data)
                        if not _pix.isNull():
                            _pix = _pix.scaled(
                                120, 68,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                            _lbl.setPixmap(_pix)
                            _lbl.setText("")
                            _bg = P.D_THUMB if self._dark_mode else P.L_THUMB
                            _lbl.setStyleSheet(
                                f"background: {_bg}; border-radius: 5px;"
                            )
                    except RuntimeError:
                        pass   # widget destruído (dialog fechou antes da thumbnail)
                    except Exception:
                        pass

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
        # Cor do texto "running" adapta ao tema para ser legível em fundo claro
        _txt_running = P.D_TEXT if self._dark_mode else P.L_TEXT
        _colors = {
            "idle":    ("gray",        "gray"),
            "running": (_txt_running,  P.GREEN),
            "done":    (P.GREEN,       P.GREEN),
            "error":   (P.ERROR,       P.ERROR),
        }
        tc, dc = _colors.get(state, (_txt_running, P.GREEN))
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
        color = P.GREEN if self._dot_pulse_bright else P.GREEN_DIM
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
                "Clique em 'Autorizar' no banner acima ou acesse Configurações."
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
            self.run_btn.setText("▶  Processar")
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
    # Configurações e autorização (banner + gear/nav)
    # -----------------------------------------------------------------------
    def _open_settings(self):
        self._switch_page(2)
        self._refresh_config_auth()

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
    # Thumbnail YouTube — carregamento assíncrono
    # -----------------------------------------------------------------------
    def _fetch_thumbnail(self, video_id: str, label: QLabel):
        """Busca thumbnail em background e despacha via fila para o main thread.

        Usa ``self._queue`` em vez de ``QTimer.singleShot`` porque PyQt6 não
        oferece a sobrecarga com QObject de contexto — e a fila já é polling
        pelo ``_queue_timer``, que continua rodando dentro de ``dlg.exec()``.
        """

        def _worker():
            data = _try_cdn_thumbnail(video_id)
            if data is None:
                data = _try_ytdlp_thumbnail(video_id)
            if data is not None:
                self._queue.put(("thumbnail", (label, data)))

        threading.Thread(target=_worker, daemon=True).start()

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
        lbl.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {P.WARN};")
        layout.addWidget(lbl)
        layout.addWidget(QLabel(
            f"A data {date_str} já foi processada em {processado_em}."
        ))
        if videos:
            nomes = "\n".join(f"  • {v}" for v in videos[:5])
            if len(videos) > 5:
                nomes += f"\n  … e mais {len(videos) - 5} vídeo(s)"
            v_lbl = QLabel(nomes)
            v_lbl.setStyleSheet(
                "color: gray; font-family: Consolas; font-size: 11px;"
            )
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
        dlg.setWindowTitle("Selecionar vídeo")
        dlg.setFixedSize(620, 520)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        # Cabeçalho
        t_lbl = QLabel(f"📅  Vídeos publicados em {date_str}")
        t_lbl.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(t_lbl)

        s_lbl = QLabel(
            "Selecione os vídeos que deseja baixar e enviar para o Drive:"
        )
        s_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        layout.addWidget(s_lbl)

        sep = QFrame()
        sep.setObjectName("section_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)

        # Lista de vídeos com thumbnails
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        container.setObjectName("scroll_contents")
        cl = QVBoxLayout(container)
        cl.setSpacing(8)
        cl.setContentsMargins(2, 4, 8, 4)

        # Fila LOCAL para thumbnails desta dialog.
        # Não usamos self._queue porque _show_video_selection é chamado de dentro
        # de _process_queue: enquanto dlg.exec() bloqueia esse frame de execução,
        # o self._queue_timer tenta chamar _process_queue de forma re-entrante,
        # mas o PyQt6 pode descartar essa chamada sem garantias. Um timer filho
        # do próprio dialog opera no event loop criado por dlg.exec() sem nenhuma
        # ambiguidade de re-entrância.
        _thumb_q: queue.Queue = queue.Queue()

        def _apply_pending_thumbs():
            """Drena _thumb_q e aplica pixmaps nos QLabels — roda no main thread."""
            try:
                while True:
                    _lbl, _data = _thumb_q.get_nowait()
                    try:
                        _pix = QPixmap()
                        _pix.loadFromData(_data)
                        if not _pix.isNull():
                            _pix = _pix.scaled(
                                120, 68,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                            _lbl.setPixmap(_pix)
                            _lbl.setText("")
                            _bg = P.D_THUMB if self._dark_mode else P.L_THUMB
                            _lbl.setStyleSheet(f"background: {_bg}; border-radius: 5px;")
                    except RuntimeError:
                        pass   # widget destruído (dialog fechou antes da thumbnail)
                    except Exception:
                        pass
            except queue.Empty:
                pass

        # Timer filho do dialog — dispara dentro do event loop de dlg.exec()
        _thumb_timer = QTimer(dlg)
        _thumb_timer.timeout.connect(_apply_pending_thumbs)
        _thumb_timer.start(100)

        check_boxes = []
        for video in videos:
            card = QFrame()
            card.setObjectName("card")
            ch = QHBoxLayout(card)
            ch.setContentsMargins(12, 10, 12, 10)
            ch.setSpacing(14)

            # Thumbnail
            thumb = QLabel()
            thumb.setFixedSize(120, 68)
            thumb.setObjectName("thumb")
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setText("⏳")
            ch.addWidget(thumb)

            # Carrega thumbnail em background; resultado vai para _thumb_q local
            _vid_id = video["id"]
            _thumb_lbl = thumb
            def _start_fetch(vid_id=_vid_id, lbl=_thumb_lbl):
                def _w():
                    data = _try_cdn_thumbnail(vid_id)
                    if data is None:
                        data = _try_ytdlp_thumbnail(vid_id)
                    if data is not None:
                        _thumb_q.put((lbl, data))
                threading.Thread(target=_w, daemon=True).start()
            _start_fetch()

            # Informações do vídeo
            info = QVBoxLayout()
            info.setSpacing(3)

            vt = QLabel(video["title"])
            vt.setStyleSheet("font-weight: bold; font-size: 13px;")
            vt.setWordWrap(True)
            info.addWidget(vt)

            try:
                d = datetime.strptime(video["upload_date"], "%Y%m%d")
                date_fmt = d.strftime("Publicado em %d/%m/%Y")
            except Exception:
                date_fmt = video["upload_date"]
            dl = QLabel(date_fmt)
            dl.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
            info.addWidget(dl)
            info.addStretch()

            # Toggle de seleção
            chk = _CheckCell()
            check_boxes.append(chk)

            row = QHBoxLayout()
            row.addLayout(info, stretch=1)
            row.addWidget(chk, alignment=Qt.AlignmentFlag.AlignVCenter)
            ch.addLayout(row, stretch=1)
            cl.addWidget(card)

        cl.addStretch()
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

        # NÃO chamar dlg.reject() aqui: o sinal rejected é emitido pelo Qt
        # antes deste slot ser invocado (X ou escape). Chamar reject() de dentro
        # do handler de rejected causa recursão infinita → RecursionError.
        dlg.rejected.connect(lambda: _result.update({"action": "cancel"}))

        btn_proc = QPushButton("▶  Prosseguir")
        btn_proc.setStyleSheet("font-weight: bold; font-size: 13px; padding: 8px 0;")
        btn_proc.clicked.connect(_prosseguir)
        layout.addWidget(btn_proc)
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
        self._stop_dot_pulse(P.GREEN)
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
# Configurações (dialog modal) — mantido para compatibilidade
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

        layout.addWidget(self._section_label("Canal do YouTube"))
        cfg = baixar_audio.load_config()
        self._channel_entry = QLineEdit(cfg["channel_url"])
        layout.addWidget(self._channel_entry)
        yt_hint = QLabel("Ex: https://www.youtube.com/@SeuCanal/streams")
        yt_hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(yt_hint)

        layout.addWidget(self._section_label("Pasta do Google Drive"))
        self._folder_entry = QLineEdit(cfg["drive_folder_id"])
        layout.addWidget(self._folder_entry)
        dr_hint = QLabel(
            "ID da pasta raiz no Drive (encontrado no final da URL da pasta)"
        )
        dr_hint.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(dr_hint)

        layout.addStretch()

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
        self._feedback_label.setStyleSheet(f"color: {P.GREEN}; font-size: 11px;")
        layout.addWidget(self._feedback_label)

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        return lbl

    def _refresh_auth_status(self):
        if baixar_audio.check_auth_status():
            self._auth_status_label.setText("✓  Autorizado")
            self._auth_status_label.setStyleSheet(f"color: {P.GREEN};")
            self._auth_action_btn.setText("Logout")
            self._auth_action_btn.setStyleSheet(
                f"background: {P.RED}; border-radius: 4px;"
            )
        else:
            self._auth_status_label.setText("✗  Não autorizado")
            self._auth_status_label.setStyleSheet(f"color: {P.ERROR};")
            self._auth_action_btn.setText("Autorizar")
            self._auth_action_btn.setStyleSheet(
                f"background: {P.GREEN}; border-radius: 4px;"
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
        self._feedback_label.setStyleSheet(f"color: {P.WARN}; font-size: 11px;")

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
        self._feedback_label.setStyleSheet(f"color: {P.GREEN}; font-size: 11px;")

    def _on_auth_error(self, msg: str):
        self._auth_running = False
        self._auth_action_btn.setEnabled(True)
        self._refresh_auth_status()
        self._feedback_label.setText(f"Erro na autorização: {msg}")
        self._feedback_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")

    def _save(self):
        channel = self._channel_entry.text().strip()
        folder  = self._folder_entry.text().strip()
        if not channel:
            self._feedback_label.setText("URL do canal não pode estar vazia.")
            self._feedback_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")
            return
        if not folder:
            self._feedback_label.setText("ID da pasta não pode estar vazio.")
            self._feedback_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")
            return
        baixar_audio.save_config(channel_url=channel, drive_folder_id=folder)
        self._feedback_label.setText("Configurações salvas com sucesso!")
        self._feedback_label.setStyleSheet(f"color: {P.GREEN}; font-size: 11px;")


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
        _q.setStyleSheet(_QSS_DARK)
        win = App()
        win.show()
        sys.exit(_q.exec())
