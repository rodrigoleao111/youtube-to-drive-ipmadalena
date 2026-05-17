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

from PyQt6.QtCore import QDate, QObject, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QRadioButton, QScrollArea, QSlider,
    QStackedWidget, QStyle, QTabWidget, QVBoxLayout, QWidget,
)

import baixar_audio
from setup_wizard import SetupWizard
from player_window_qt import PlayerWindowQt as PlayerWindow


APP_VERSION = "v3.2.0"

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
    """
    Configura logging:
      - SEMPRE escreve em `logs/DD-MM-YYYY.log`
      - QUANDO RODANDO COMO SCRIPT (não frozen), também imprime no terminal
        (stderr) para ajudar no debug do dev — `_log.info(...)` em
        `infrastructure/audio/...` aparece direto no console.
    """
    os.makedirs(baixar_audio.LOGS_DIR, exist_ok=True)
    log_file = os.path.join(
        baixar_audio.LOGS_DIR,
        datetime.now().strftime("%d-%m-%Y") + ".log",
    )
    handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    # Console handler só faz sentido fora do .exe (frozen não tem terminal)
    if not getattr(sys, "frozen", False):
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        handlers.append(console_handler)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
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
# Helpers de UI
# ---------------------------------------------------------------------------

def _wrap_elide(text: str, fm, max_width: int, max_lines: int) -> str:
    """Quebra `text` em até `max_lines` linhas de `max_width` px; última com '…'."""
    from PyQt6.QtCore import Qt
    words = text.split()
    lines: list[str] = []
    current = ""
    i = 0
    while i < len(words):
        word = words[i]
        candidate = (current + " " + word).strip() if current else word
        if fm.horizontalAdvance(candidate) <= max_width:
            current = candidate
            i += 1
        else:
            if not current:          # palavra única mais larga que a coluna
                current = word
                i += 1
            lines.append(current)
            current = ""
            if len(lines) == max_lines - 1:
                remaining = " ".join(words[i:])
                lines.append(fm.elidedText(remaining, Qt.TextElideMode.ElideRight, max_width))
                return "\n".join(lines)
    if current:
        lines.append(current)
    return "\n".join(lines[:max_lines])


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

        self._stack.addWidget(self._build_home_page())         # 0
        self._stack.addWidget(self._build_processar_page())   # 1
        self._stack.addWidget(self._build_historico_page())   # 2
        self._stack.addWidget(self._build_config_page())      # 3

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
            ("🏠", "Início"),
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
        ver = QLabel(APP_VERSION)
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

        if idx == 0:
            self._refresh_home()
        elif idx == 2:
            self._refresh_history()
        elif idx == 3:
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
    # Página 0 — Início (Home)
    # -----------------------------------------------------------------------
    def _build_home_page(self) -> QWidget:
        PAD = 26
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(PAD, 22, PAD, 22)
        layout.setSpacing(0)

        # ── Topbar ──────────────────────────────────────────────────────────
        self._home_sort_order = 0   # 0 = Mais recentes, 1 = A–Z
        hdr = QHBoxLayout()
        title = QLabel("Arquivos baixados")
        title.setStyleSheet("font-size: 19px; font-weight: bold;")
        hdr.addWidget(title)
        hdr.addStretch()

        sort_combo = QComboBox()
        sort_combo.addItems(["Mais recentes", "A–Z"])
        sort_combo.setFixedWidth(130)
        sort_combo.currentIndexChanged.connect(self._on_home_sort_changed)
        self._home_sort_combo = sort_combo
        hdr.addWidget(sort_combo)

        layout.addLayout(hdr)
        layout.addSpacing(2)

        self._home_sub = QLabel("Carregando...")
        self._home_sub.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        layout.addWidget(self._home_sub)
        layout.addSpacing(14)

        sep = QFrame()
        sep.setObjectName("section_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(10)

        # ── Área de scroll + grid de cards ──────────────────────────────────
        self._home_scroll = QScrollArea()
        self._home_scroll.setWidgetResizable(True)
        self._home_container = QWidget()
        self._home_container.setObjectName("scroll_contents")
        self._home_outer_layout = QVBoxLayout(self._home_container)
        self._home_outer_layout.setContentsMargins(0, 4, 8, 4)
        self._home_outer_layout.setSpacing(0)
        self._home_scroll.setWidget(self._home_container)
        layout.addWidget(self._home_scroll, stretch=1)

        return page

    def _refresh_home(self):
        import glob as _glob

        # Remove widgets anteriores
        while self._home_outer_layout.count():
            item = self._home_outer_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Busca arquivos MP3 em DOWNLOAD_DIR
        os.makedirs(baixar_audio.DOWNLOAD_DIR, exist_ok=True)
        all_files = _glob.glob(os.path.join(baixar_audio.DOWNLOAD_DIR, "*.mp3"))
        sort_idx = getattr(self, "_home_sort_order", 0)
        if sort_idx == 1:
            mp3_files = sorted(all_files, key=lambda f: os.path.basename(f).lower())
        else:
            mp3_files = sorted(all_files, key=os.path.getmtime, reverse=True)

        if not mp3_files:
            empty_w = QWidget()
            ev = QVBoxLayout(empty_w)
            ev.setContentsMargins(20, 60, 20, 20)
            ev.setSpacing(10)
            ev.setAlignment(Qt.AlignmentFlag.AlignHCenter)

            icon_lbl = QLabel("🎵")
            icon_lbl.setStyleSheet("font-size: 48px;")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            ev.addWidget(icon_lbl)

            main_lbl = QLabel("Nenhum áudio baixado")
            main_lbl.setStyleSheet("font-size: 15px; font-weight: bold;")
            main_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            ev.addWidget(main_lbl)

            hint_lbl = QLabel(
                "Ative 'Manter arquivos no dispositivo' em Configurações → Geral\n"
                "e vá em Processar para baixar o primeiro culto."
            )
            hint_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
            hint_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            hint_lbl.setWordWrap(True)
            ev.addWidget(hint_lbl)

            self._home_outer_layout.addWidget(empty_w)
            self._home_sub.setText("Nenhum arquivo encontrado")
            return

        n = len(mp3_files)
        total_mb = sum(os.path.getsize(f) for f in mp3_files) / (1024 * 1024)
        arq = "arquivo" if n == 1 else "arquivos"
        self._home_sub.setText(f"{n} {arq}  ·  {total_mb:.1f} MB no disco")

        # Grid 3 colunas
        COLS = 3
        grid_widget = QWidget()
        grid_widget.setObjectName("scroll_contents")
        grid = QGridLayout(grid_widget)
        grid.setSpacing(12)
        grid.setContentsMargins(0, 0, 0, 0)

        history = baixar_audio.load_history()
        uploaded_titles = {
            t.lower()
            for entry in history.values()
            for t in entry.get("videos", [])
        }

        for i, fpath in enumerate(mp3_files):
            row, col = divmod(i, COLS)
            grid.addWidget(self._build_home_card(fpath, uploaded_titles), row, col)

        # Preenchimento de colunas restantes na última linha
        remainder = len(mp3_files) % COLS
        if remainder:
            for col in range(remainder, COLS):
                placeholder = QWidget()
                grid.addWidget(placeholder, len(mp3_files) // COLS, col)

        self._home_outer_layout.addWidget(grid_widget)
        self._home_outer_layout.addStretch()

    def _build_home_card(self, fpath: str, uploaded_titles: set | None = None) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setFixedSize(220, 262)
        v = QVBoxLayout(card)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # Thumbnail (16:9 — fallback emoji)
        thumb = QLabel("🎵")
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setFixedHeight(118)
        bg = P.D_THUMB if self._dark_mode else P.L_THUMB
        thumb.setStyleSheet(
            f"font-size: 36px; background: {bg};"
            f"border-top-left-radius: 8px; border-top-right-radius: 8px;"
        )
        v.addWidget(thumb)

        # Body
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(4)

        # Título (basename sem extensão, máx 3 linhas com reticências)
        title_text = os.path.splitext(os.path.basename(fpath))[0]
        title_lbl = QLabel()
        title_lbl.setStyleSheet("font-size: 12px; font-weight: bold;")
        from PyQt6.QtGui import QFont, QFontMetrics
        _font = QFont()
        _font.setPixelSize(12)
        _font.setBold(True)
        _fm = QFontMetrics(_font)
        _text_w = 220 - 12 - 12   # largura do card menos margens horizontais
        title_lbl.setText(_wrap_elide(title_text, _fm, _text_w, 3))
        title_lbl.setFixedHeight(_fm.lineSpacing() * 3 + 2)
        bl.addWidget(title_lbl)

        # Meta: data + tamanho
        try:
            size_mb = os.path.getsize(fpath) / (1024 * 1024)
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
            meta_text = f"{mtime.strftime('%d/%m/%Y')}  ·  {size_mb:.1f} MB"
        except Exception:
            meta_text = ""
        meta_lbl = QLabel(meta_text)
        meta_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        bl.addWidget(meta_lbl)

        # Badge de status (Enviado/Local)
        title_key = title_text.lower()
        uploaded = uploaded_titles is not None and title_key in uploaded_titles
        badge = QLabel("✓ Enviado ao Drive" if uploaded else "● Local")
        badge_color = P.GREEN if uploaded else P.HINT
        badge.setStyleSheet(f"color: {badge_color}; font-size: 10px;")
        bl.addWidget(badge)

        # Botões
        acts = QHBoxLayout()
        acts.setSpacing(6)
        acts.setContentsMargins(0, 6, 0, 0)

        _fp = fpath
        btn_play = QPushButton("▶  Tocar")
        btn_play.setStyleSheet("font-weight: bold; padding: 6px 0;")
        btn_play.clicked.connect(lambda: self._play_local_file(_fp))
        acts.addWidget(btn_play, stretch=1)

        if not uploaded:
            btn_upload = QPushButton()
            btn_upload.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp))
            btn_upload.setObjectName("gray_btn")
            btn_upload.setFixedWidth(32)
            btn_upload.setToolTip("Enviar ao Drive")
            btn_upload.clicked.connect(lambda: self._reupload_file(_fp, btn_upload))
            acts.addWidget(btn_upload)

        btn_del = QPushButton()
        btn_del.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        btn_del.setObjectName("gray_btn")
        btn_del.setFixedWidth(38)
        btn_del.setToolTip("Excluir arquivo local")
        btn_del.clicked.connect(lambda: self._delete_local_file(_fp))
        acts.addWidget(btn_del)

        bl.addLayout(acts)
        v.addWidget(body)
        return card

    def _on_home_sort_changed(self, idx: int):
        self._home_sort_order = idx
        self._refresh_home()

    def _play_local_file(self, fpath: str):
        dlg = _AudioPlayerDialog(fpath, parent=self)
        dlg.exec()

    def _delete_local_file(self, fpath: str):
        fname = os.path.basename(fpath)
        msg = QMessageBox(self)
        msg.setWindowTitle("Excluir arquivo")
        msg.setText(f"Deseja excluir '{fname}'?\nEsta ação não pode ser desfeita.")
        msg.setIcon(QMessageBox.Icon.Question)
        btn_sim = msg.addButton("Sim", QMessageBox.ButtonRole.YesRole)
        msg.addButton("Não", QMessageBox.ButtonRole.NoRole)
        msg.exec()
        if msg.clickedButton() is btn_sim:
            try:
                os.remove(fpath)
                self._refresh_home()
            except Exception as e:
                QMessageBox.critical(
                    self, "Erro", f"Não foi possível excluir o arquivo:\n{e}"
                )

    def _reupload_file(self, fpath: str, btn: QPushButton):
        fname = os.path.basename(fpath)
        msg = QMessageBox(self)
        msg.setWindowTitle("Enviar ao Drive")
        msg.setText(f"Deseja enviar '{fname}' ao Google Drive?")
        msg.setIcon(QMessageBox.Icon.Question)
        btn_sim = msg.addButton("Enviar", QMessageBox.ButtonRole.YesRole)
        msg.addButton("Cancelar", QMessageBox.ButtonRole.NoRole)
        msg.exec()
        if msg.clickedButton() is not btn_sim:
            return

        btn.setEnabled(False)
        btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))

        def worker():
            try:
                from composition_root import build_processing_presenter
                from domain.entities import AudioFile
                presenter = build_processing_presenter()
                title = os.path.splitext(fname)[0]
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                date_str = mtime.strftime("%d/%m/%Y")
                audio_file = AudioFile(path=fpath, title=title, video_id="")
                presenter.upload_uc.execute(
                    audio_files=[audio_file],
                    date_str=date_str,
                    on_log=lambda m: None,
                    on_status=lambda s: None,
                )
                QTimer.singleShot(0, self._refresh_home)
            except Exception as e:
                QTimer.singleShot(
                    0,
                    lambda: QMessageBox.critical(
                        self, "Erro no upload", f"Não foi possível enviar o arquivo:\n{e}"
                    ),
                )
                QTimer.singleShot(0, lambda: (
                    btn.setEnabled(True),
                    btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowUp)),
                ))

        threading.Thread(target=worker, daemon=True).start()

    # -----------------------------------------------------------------------
    # Página 1 — Processar
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
    # Página 2 — Configurações (inline, com sub-abas Geral / Edição de áudio)
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

        sub = QLabel(
            "Ajuste o canal, a pasta do Drive, a autorização Google e a "
            "edição de áudio (vinhetas, fade, EQ e redução de ruído)."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        layout.addWidget(sub)

        sep = QFrame()
        sep.setObjectName("section_sep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        layout.addWidget(sep)
        layout.addSpacing(4)

        # ── Sub-abas ────────────────────────────────────────────────────────
        self._cfg_tabs = QTabWidget()
        self._cfg_tabs.addTab(self._build_general_tab(), "⚙  Geral")
        self._audio_tab = _AudioSettingsTab(self)
        self._cfg_tabs.addTab(self._audio_tab, "🎚  Edição de áudio")
        layout.addWidget(self._cfg_tabs, stretch=1)

        # ── Save unificado (persiste AMBAS as abas em uma chamada) ──────────
        btn_row = QHBoxLayout()
        self._cfg_feedback_label = QLabel("")
        self._cfg_feedback_label.setStyleSheet(
            f"color: {P.GREEN}; font-size: 11px;"
        )
        btn_row.addWidget(self._cfg_feedback_label, stretch=1)

        btn_save = QPushButton("💾  Salvar configurações")
        btn_save.setStyleSheet("font-weight: bold; padding: 8px 24px;")
        btn_save.clicked.connect(self._cfg_save)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

        return page

    def _build_general_tab(self) -> QWidget:
        """Sub-aba 'Geral' — autorização Drive, canal YouTube e pasta Drive."""
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 14, 4, 14)
        layout.setSpacing(10)

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

        # ── Card: Capítulo automático ───────────────────────────────────────
        ch_card = QFrame()
        ch_card.setObjectName("cfg_card")
        cc = QVBoxLayout(ch_card)
        cc.setContentsMargins(20, 16, 20, 16)
        cc.setSpacing(8)

        tr4 = QHBoxLayout()
        tr4.addWidget(self._icon_label("📑", 22))
        lbl4 = QLabel("Capítulo automático")
        lbl4.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr4.addWidget(lbl4)
        tr4.addStretch()
        cc.addLayout(tr4)

        ch_hint = QLabel(
            "Nome (ou parte do nome) do capítulo a baixar automaticamente. "
            "Deixe em branco para sempre abrir a seleção manual."
        )
        ch_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        ch_hint.setWordWrap(True)
        cc.addWidget(ch_hint)

        self._cfg_chapter_entry = QLineEdit(cfg.get("chapter_name", ""))
        self._cfg_chapter_entry.setPlaceholderText("Ex: Sermão, Culto da manhã...")
        cc.addWidget(self._cfg_chapter_entry)

        layout.addWidget(ch_card)

        # ── Card: Manter arquivos no dispositivo ────────────────────────────
        kf_card = QFrame()
        kf_card.setObjectName("cfg_card")
        kfc = QVBoxLayout(kf_card)
        kfc.setContentsMargins(20, 16, 20, 16)
        kfc.setSpacing(8)

        tr5 = QHBoxLayout()
        tr5.addWidget(self._icon_label("💾", 22))
        lbl5 = QLabel("Manter arquivos no dispositivo")
        lbl5.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr5.addWidget(lbl5)
        tr5.addStretch()
        kfc.addLayout(tr5)

        kf_hint = QLabel(
            "Se habilitado, os arquivos de áudio processados são mantidos no "
            "dispositivo após o upload e ficam visíveis na tela Início."
        )
        kf_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        kf_hint.setWordWrap(True)
        kfc.addWidget(kf_hint)

        self._cfg_keep_files_check = QCheckBox("Manter arquivos após upload")
        self._cfg_keep_files_check.setChecked(bool(cfg.get("keep_files", False)))
        kfc.addWidget(self._cfg_keep_files_check)

        layout.addWidget(kf_card)
        layout.addStretch()

        # ── Rodapé: log + versão ────────────────────────────────────────────
        footer = QHBoxLayout()
        footer.setContentsMargins(4, 8, 4, 0)

        btn_log = QPushButton("📄  Abrir log de hoje")
        btn_log.setObjectName("gray_btn")
        btn_log.clicked.connect(self._open_today_log)
        footer.addWidget(btn_log)
        footer.addStretch()

        ver_lbl = QLabel(f"IPMadalena  ·  {APP_VERSION}")
        ver_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        footer.addWidget(ver_lbl)

        layout.addLayout(footer)

        scroll.setWidget(container)
        outer.addWidget(scroll)
        return tab

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

    def _open_today_log(self):
        log_path = os.path.join(
            baixar_audio.LOGS_DIR,
            datetime.now().strftime("%d-%m-%Y") + ".log",
        )
        if os.path.exists(log_path):
            os.startfile(log_path)
        else:
            QMessageBox.information(self, "Log", "Nenhum log gerado hoje ainda.")

    def _cfg_save(self):
        """
        Save unificado: persiste a aba GERAL (canal/pasta) e a aba EDIÇÃO DE
        ÁUDIO (vinhetas/fade/EQ/denoise) em uma única gravação. Evita o
        footgun de o usuário clicar Save com a aba errada visível e perder
        mudanças que fez na outra.

        Paths de vinheta dentro de VINHETAS_DIR são convertidos para basename
        antes de gravar (portabilidade — `audio_edit_persist_paths`).
        """
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

        try:
            audio_cfg = self._audio_tab.read_config_from_ui()
            audio_dict = baixar_audio.audio_edit_persist_paths(audio_cfg.to_dict())

            repo = baixar_audio.config_repo()
            current = repo.load() or {}
            current["channel_url"]     = channel
            current["drive_folder_id"] = folder
            current["audio_edit"]      = audio_dict
            current["chapter_name"]    = self._cfg_chapter_entry.text().strip()
            current["keep_files"]      = self._cfg_keep_files_check.isChecked()
            repo.save(current)
        except Exception as e:
            self._cfg_feedback_label.setText(f"Erro ao salvar: {e}")
            self._cfg_feedback_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")
            return

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

                elif kind == "edit_progress":
                    # Reaproveita a barra de Conversão para mostrar progresso real
                    # da edição de áudio (substitui a animação ate-90% do yt-dlp).
                    self._converting = False
                    self.convert_bar.set(value)
                    self.convert_stats.setText(f"{value * 100:.0f}%")

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

                elif kind == "check_chapters":
                    date_str, selected = value
                    threading.Thread(
                        target=self._worker_check_chapters,
                        args=(date_str, selected),
                        daemon=True,
                    ).start()

                elif kind == "open_player_extra":
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

    def _worker_check_chapters(self, date_str: str, selected_videos: list):
        """
        Verifica capítulos para cada vídeo selecionado.

        - Se chapter_name estiver configurado: busca capítulos via presenter e
          faz match por substring (case-insensitive) para cada vídeo.
            • Vídeos COM capítulo encontrado → segment auto-criado.
            • Vídeos SEM capítulo → enviados ao player para seleção manual.
        - Se chapter_name não estiver configurado → abre player para todos.
        """
        chapter_name = baixar_audio.load_config().get("chapter_name", "").strip()

        if not chapter_name:
            self._queue.put(("open_player", (date_str, selected_videos)))
            return

        presenter = self._build_presenter()
        auto_segments: list = []
        manual_videos: list = []

        for video in selected_videos:
            vid_id = video["id"]
            self._queue.put(("log", f"Verificando capítulos de '{video['title']}'..."))
            try:
                chapters = presenter.get_chapters(
                    vid_id,
                    cancel_event=self._cancel_event,
                    on_log=lambda m: self._queue.put(("log", m)),
                )
            except Exception:
                chapters = []

            match = next(
                (ch for ch in chapters if chapter_name.lower() in ch["title"].lower()),
                None,
            )
            if match:
                self._queue.put(("log",
                    f"  Capítulo encontrado: '{match['title']}' "
                    f"({match['start']} → {match['end']})"
                ))
                auto_segments.append({
                    "id":    vid_id,
                    "title": match["title"],
                    "start": match["start"],
                    "end":   match["end"],
                })
            else:
                self._queue.put(("log",
                    f"  Capítulo '{chapter_name}' não encontrado — "
                    "abrindo seleção manual."
                ))
                manual_videos.append(video)

        if not manual_videos:
            # Todos os vídeos tiveram capítulo encontrado → download automático
            self._queue.put(("log",
                f"Capítulos detectados em todos os vídeos. "
                "Iniciando download automático..."
            ))
            threading.Thread(
                target=self._worker_phase2,
                args=(date_str, auto_segments),
                daemon=True,
            ).start()
        else:
            # Alguns precisam de seleção manual; auto_segments são extras
            self._queue.put(("open_player_extra",
                (date_str, manual_videos, auto_segments)
            ))

    def _show_player_window(
        self,
        date_str: str,
        selected_videos: list,
        extra_segments: list = None,
    ):
        extra = extra_segments or []

        def _on_complete(segments):
            all_segments = extra + segments
            self._append_log("Trechos confirmados. Iniciando download...")
            threading.Thread(
                target=self._worker_phase2,
                args=(date_str, all_segments),
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
                on_edit_progress=lambda p: self._queue.put(("edit_progress", p)),
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
        self._switch_page(3)
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
            self._append_log(f"{len(selected)} vídeo(s) selecionado(s).")
            self._queue.put(("check_chapters", (date_str, selected)))
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
        if self._running:
            msg = QMessageBox(self)
            msg.setWindowTitle("Fechar o app")
            msg.setText("Uma operação está em andamento.\nDeseja realmente sair?")
            msg.setIcon(QMessageBox.Icon.Warning)
            btn_sair = msg.addButton("Sair assim mesmo", QMessageBox.ButtonRole.YesRole)
            msg.addButton("Cancelar", QMessageBox.ButtonRole.NoRole)
            msg.exec()
            if msg.clickedButton() is not btn_sair:
                event.ignore()
                return
        self._queue_timer.stop()
        event.accept()


# ---------------------------------------------------------------------------
# Player de áudio em popup — usado pelo botão "Tocar" do preview de teste
# ---------------------------------------------------------------------------
class _AudioPlayerDialog(QDialog):
    """
    Diálogo modal com player de áudio simples:
      - Slider de posição (draggable para seek)
      - Botões: ⏪ -10s | ▶/⏸ | +10s ⏩
      - Display de tempo: 00:00 / total

    O player começa a tocar automaticamente ao abrir. Ao fechar o diálogo
    (X, Esc, botão Fechar), a reprodução é interrompida.
    """

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self._file_path = file_path
        self._duration_ms = 0
        self._slider_dragging = False

        self.setWindowTitle("Reproduzindo: " + os.path.basename(file_path))
        self.setMinimumSize(480, 200)
        self.setModal(True)

        self._build_ui()
        self._init_player()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        # Filename
        title = QLabel(os.path.basename(self._file_path))
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        title.setWordWrap(True)
        layout.addWidget(title)

        # Slider de posição
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        # Click-to-seek: ao mover via teclado/click direto, segue até soltar
        self._slider.valueChanged.connect(self._on_slider_value_changed)
        layout.addWidget(self._slider)

        # Linha de tempo: 00:15  ----  01:30
        time_row = QHBoxLayout()
        self._time_label = QLabel("00:00")
        self._time_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
        )
        self._duration_label = QLabel("00:00")
        self._duration_label.setStyleSheet(
            f"font-family: Consolas, monospace; font-size: 11px; color: {P.HINT};"
        )
        time_row.addWidget(self._time_label)
        time_row.addStretch()
        time_row.addWidget(self._duration_label)
        layout.addLayout(time_row)

        layout.addSpacing(6)

        # Botões de controle
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(10)
        ctrl_row.addStretch()

        self._btn_back = QPushButton("⏪  -10s")
        self._btn_back.setObjectName("gray_btn")
        self._btn_back.setFixedWidth(95)
        self._btn_back.clicked.connect(lambda: self._skip(-10))
        ctrl_row.addWidget(self._btn_back)

        self._btn_play = QPushButton("⏸  Pausar")
        self._btn_play.setFixedWidth(120)
        self._btn_play.setStyleSheet("font-weight: bold;")
        self._btn_play.clicked.connect(self._toggle_play)
        ctrl_row.addWidget(self._btn_play)

        self._btn_fwd = QPushButton("+10s  ⏩")
        self._btn_fwd.setObjectName("gray_btn")
        self._btn_fwd.setFixedWidth(95)
        self._btn_fwd.clicked.connect(lambda: self._skip(10))
        ctrl_row.addWidget(self._btn_fwd)

        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # Espaço + botão de fechar
        layout.addSpacing(4)
        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("Fechar")
        btn_close.setObjectName("gray_btn")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

    # -----------------------------------------------------------------------
    # Player (QMediaPlayer)
    # -----------------------------------------------------------------------

    def _init_player(self):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
        self._audio_output = QAudioOutput()
        self._player = QMediaPlayer()
        self._player.setAudioOutput(self._audio_output)
        self._player.setSource(QUrl.fromLocalFile(self._file_path))
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        # Auto-play ao abrir o diálogo
        self._player.play()

    def _toggle_play(self):
        from PyQt6.QtMultimedia import QMediaPlayer
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _skip(self, secs: int):
        """Avança/retorna `secs` segundos (clampado entre 0 e duração total)."""
        target = self._player.position() + secs * 1000
        target = max(0, min(self._duration_ms or target, target))
        self._player.setPosition(target)

    # -----------------------------------------------------------------------
    # Sincronização player ↔ slider
    # -----------------------------------------------------------------------

    def _on_position_changed(self, ms: int):
        if not self._slider_dragging:
            # Bloqueia o sinal valueChanged para não chamar setPosition em loop
            self._slider.blockSignals(True)
            self._slider.setValue(ms)
            self._slider.blockSignals(False)
        self._time_label.setText(self._fmt(ms))

    def _on_duration_changed(self, ms: int):
        self._duration_ms = ms
        self._slider.setRange(0, max(0, ms))
        self._duration_label.setText(self._fmt(ms))

    def _on_state_changed(self, state):
        from PyQt6.QtMultimedia import QMediaPlayer
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._btn_play.setText("⏸  Pausar")
        else:
            self._btn_play.setText("▶  Tocar")

    def _on_slider_pressed(self):
        self._slider_dragging = True

    def _on_slider_released(self):
        self._player.setPosition(self._slider.value())
        self._slider_dragging = False

    def _on_slider_value_changed(self, value: int):
        # Só faz seek quando o usuário interage diretamente — durante
        # reprodução normal, o player atualiza o slider mas blockSignals
        # impede que esse callback dispare.
        if self._slider_dragging:
            # Atualiza display de tempo enquanto arrasta (mas só commita no release)
            self._time_label.setText(self._fmt(value))

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _fmt(ms: int) -> str:
        s = max(0, int(ms)) // 1000
        return f"{s // 60:02d}:{s % 60:02d}"

    def hideEvent(self, event):
        """Para o player sempre que o diálogo sai de cena (X, Esc, accept, reject)."""
        try:
            self._player.stop()
        except Exception:
            pass
        super().hideEvent(event)


# ---------------------------------------------------------------------------
# Dispatcher cross-thread para o card de teste de áudio
#
# Por que isso existe: `QTimer.singleShot(0, callable)` chamado de uma
# `threading.Thread` Python NÃO dispara — não há event loop nessa thread,
# então o timer fica órfão. A forma confiável de comunicar thread→GUI no
# PyQt é via sinal num QObject criado no thread principal: o Qt usa
# `QueuedConnection` automaticamente quando um sinal é emitido de outra
# thread, garantindo que o slot rode no event loop principal.
# ---------------------------------------------------------------------------
class _AudioPreviewDispatcher(QObject):
    """Bridge thread→GUI para os callbacks do AudioTestPresenter."""
    log_received     = pyqtSignal(str)
    progress_changed = pyqtSignal(float)
    completed        = pyqtSignal(str)   # preview_path
    cancelled        = pyqtSignal()
    failed           = pyqtSignal(str)   # mensagem de erro


# ---------------------------------------------------------------------------
# Sub-aba "Edição de áudio" — embed dentro da página Configurações do App
# ---------------------------------------------------------------------------
class _AudioSettingsTab(QWidget):
    """
    Widget que renderiza a sub-aba "Edição de áudio" da página Configurações.

    Carrega `audio_edit` do `config.json` no construtor (basenames persistidos
    são expandidos para abs paths dentro de VINHETAS_DIR), constrói os 4 cards
    funcionais (vinhetas, fade, EQ, redução de ruído) + card de teste de
    configuração, e expõe `read_config_from_ui()` para o save unificado da
    página principal — que persiste em uma única gravação as duas abas.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # QMediaPlayer para preview das vinhetas e do teste (lazy)
        self._media_player = None
        self._media_audio_output = None
        self._currently_playing = None  # 'intro' | 'outro' | '_test_' | None
        # Dispatcher criado na thread principal — sinais emitidos do worker
        # são entregues via QueuedConnection automático.
        self._dispatcher = _AudioPreviewDispatcher(self)
        self._build_ui()
        # Conexões dos sinais → slots (após o _build_ui criar os widgets alvo)
        self._dispatcher.log_received.connect(self._set_test_status)
        self._dispatcher.progress_changed.connect(self._test_progress.set)
        self._dispatcher.completed.connect(self._on_test_done)
        self._dispatcher.cancelled.connect(self._on_test_cancelled)
        self._dispatcher.failed.connect(self._on_test_error)

    # -----------------------------------------------------------------------
    # API pública (chamada pelo App._cfg_save)
    # -----------------------------------------------------------------------

    def read_config_from_ui(self):
        """Constrói um AudioEditConfig a partir do estado atual dos controles."""
        return self._read_audio_config_from_ui()

    # -----------------------------------------------------------------------
    # Construção do conteúdo (4 cards + card de teste)
    # -----------------------------------------------------------------------

    def _build_ui(self):
        from domain.entities import AudioEditConfig

        # Carrega config atual (ou defaults). Expande basenames persistidos
        # (ex.: "intro.mp3") em paths absolutos dentro de VINHETAS_DIR — caso
        # contrário a UI exibiria só o nome do arquivo e o player não tocaria.
        cfg = baixar_audio.load_config()
        audio_dict = baixar_audio.audio_edit_resolve_paths(cfg.get("audio_edit") or {})
        audio_cfg = AudioEditConfig.from_dict(audio_dict)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Conteúdo dentro de QScrollArea (vários cards + card de teste podem
        # passar da altura da janela em telas menores)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        body = QWidget()
        body.setObjectName("scroll_contents")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 14, 4, 4)
        layout.setSpacing(12)

        # ── Cards funcionais ──────────────────────────────────────────────
        layout.addWidget(self._build_card_vinhetas(audio_cfg))
        layout.addWidget(self._build_card_fade(audio_cfg))
        layout.addWidget(self._build_card_eq(audio_cfg))
        layout.addWidget(self._build_card_noise(audio_cfg))
        layout.addWidget(self._build_card_norm(audio_cfg))
        layout.addWidget(self._build_card_test())

        layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)

    # -----------------------------------------------------------------------
    # Cards da página de áudio
    # -----------------------------------------------------------------------

    def _build_card_vinhetas(self, audio_cfg) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        v.addWidget(self._section_label("Vinhetas"))

        # Estado por vinheta — paths atuais
        self._intro_path = audio_cfg.intro_path or ""
        self._outro_path = audio_cfg.outro_path or ""

        # ---- Intro ----
        intro_block = self._build_vinheta_block(
            label="Vinheta de entrada",
            kind="intro",
            initial_path=self._intro_path,
            initial_overlap=audio_cfg.intro_overlap_secs,
        )
        v.addLayout(intro_block)

        # Separador horizontal
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setObjectName("section_sep")
        sep.setFixedHeight(1)
        v.addWidget(sep)

        # ---- Outro ----
        outro_block = self._build_vinheta_block(
            label="Vinheta de saída",
            kind="outro",
            initial_path=self._outro_path,
            initial_overlap=audio_cfg.outro_overlap_secs,
        )
        v.addLayout(outro_block)

        return card

    def _build_vinheta_block(self, label, kind, initial_path, initial_overlap):
        """Bloco de uma vinheta (intro ou outro): label + path + ações + overlap."""
        block = QVBoxLayout()
        block.setSpacing(6)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 12px; font-weight: bold;")
        block.addWidget(lbl)

        row = QHBoxLayout()
        row.setSpacing(6)

        path_label = QLabel(self._truncate(initial_path) or "Nenhum arquivo selecionado")
        path_label.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        path_label.setMinimumWidth(220)

        btn_select = QPushButton("Selecionar")
        btn_select.setObjectName("gray_btn")
        btn_select.setFixedWidth(110)
        btn_select.clicked.connect(lambda: self._select_vinheta(kind))

        btn_play = QPushButton("▶ Tocar")
        btn_play.setObjectName("gray_btn")
        btn_play.setFixedWidth(90)
        btn_play.clicked.connect(lambda: self._toggle_play_vinheta(kind))
        btn_play.setEnabled(bool(initial_path))

        btn_remove = QPushButton("Remover")
        btn_remove.setObjectName("gray_btn")
        btn_remove.setFixedWidth(90)
        btn_remove.clicked.connect(lambda: self._remove_vinheta(kind))
        btn_remove.setEnabled(bool(initial_path))

        row.addWidget(path_label, stretch=1)
        row.addWidget(btn_select)
        row.addWidget(btn_play)
        row.addWidget(btn_remove)
        block.addLayout(row)

        overlap_row = QHBoxLayout()
        overlap_row.addWidget(QLabel("Sobreposição com áudio:"))
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 10.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSuffix(" s")
        spin.setValue(float(initial_overlap or 0.0))
        spin.setFixedWidth(90)
        overlap_row.addWidget(spin)
        overlap_row.addStretch()
        block.addLayout(overlap_row)

        # Salva referências para uso posterior
        if kind == "intro":
            self._intro_path_label   = path_label
            self._intro_btn_select   = btn_select
            self._intro_btn_play     = btn_play
            self._intro_btn_remove   = btn_remove
            self._intro_overlap_spin = spin
        else:
            self._outro_path_label   = path_label
            self._outro_btn_select   = btn_select
            self._outro_btn_play     = btn_play
            self._outro_btn_remove   = btn_remove
            self._outro_overlap_spin = spin

        return block

    def _build_card_fade(self, audio_cfg) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        v.addWidget(self._section_label("Fade"))

        # Fade in
        row_in = QHBoxLayout()
        self._fade_in_check = QCheckBox("Fade in")
        self._fade_in_check.setChecked(audio_cfg.fade_in_enabled)
        row_in.addWidget(self._fade_in_check)
        row_in.addSpacing(12)
        row_in.addWidget(QLabel("Duração:"))
        self._fade_in_spin = QDoubleSpinBox()
        self._fade_in_spin.setRange(0.0, 10.0)
        self._fade_in_spin.setSingleStep(0.5)
        self._fade_in_spin.setDecimals(1)
        self._fade_in_spin.setSuffix(" s")
        self._fade_in_spin.setValue(float(audio_cfg.fade_in_secs))
        self._fade_in_spin.setFixedWidth(90)
        row_in.addWidget(self._fade_in_spin)
        row_in.addStretch()
        v.addLayout(row_in)

        # Fade out
        row_out = QHBoxLayout()
        self._fade_out_check = QCheckBox("Fade out")
        self._fade_out_check.setChecked(audio_cfg.fade_out_enabled)
        row_out.addWidget(self._fade_out_check)
        row_out.addSpacing(8)
        row_out.addWidget(QLabel("Duração:"))
        self._fade_out_spin = QDoubleSpinBox()
        self._fade_out_spin.setRange(0.0, 10.0)
        self._fade_out_spin.setSingleStep(0.5)
        self._fade_out_spin.setDecimals(1)
        self._fade_out_spin.setSuffix(" s")
        self._fade_out_spin.setValue(float(audio_cfg.fade_out_secs))
        self._fade_out_spin.setFixedWidth(90)
        row_out.addWidget(self._fade_out_spin)
        row_out.addStretch()
        v.addLayout(row_out)

        return card

    def _build_card_eq(self, audio_cfg) -> QFrame:
        from domain.audio_presets import (
            EQ_FREQS, EQ_GAIN_MAX_DB, EQ_GAIN_MIN_DB,
        )

        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        # Header: section label + checkbox + preset combo
        hdr = QHBoxLayout()
        hdr.addWidget(self._section_label("Equalização"))
        hdr.addStretch()

        self._eq_check = QCheckBox("Aplicar EQ")
        self._eq_check.setChecked(audio_cfg.eq_enabled)
        hdr.addWidget(self._eq_check)

        hdr.addSpacing(14)
        hdr.addWidget(QLabel("Preset:"))
        self._eq_preset_combo = QComboBox()
        self._eq_preset_combo.addItems(["Voz Masculina", "Personalizado"])
        self._eq_preset_combo.setFixedWidth(150)
        # Inicialmente: se as bandas batem com o preset, seleciona "Voz Masculina"
        from domain.audio_presets import EQ_PRESET_VOZ_MASCULINA
        is_default = tuple(
            (b.freq_hz, b.gain_db) for b in audio_cfg.eq_bands
        ) == EQ_PRESET_VOZ_MASCULINA
        self._eq_preset_combo.setCurrentIndex(0 if is_default else 1)
        self._eq_preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        hdr.addWidget(self._eq_preset_combo)
        v.addLayout(hdr)

        # 5 sliders verticais
        sliders_row = QHBoxLayout()
        sliders_row.setSpacing(10)
        self._eq_sliders = []
        self._eq_value_labels = []

        # Mapa freq → gain das bandas atuais
        bands_by_freq = {b.freq_hz: b.gain_db for b in audio_cfg.eq_bands}

        for freq in EQ_FREQS:
            col = QVBoxLayout()
            col.setSpacing(4)
            col.setContentsMargins(0, 0, 0, 0)

            value_lbl = QLabel(f"{bands_by_freq.get(freq, 0.0):+.1f} dB")
            value_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            value_lbl.setStyleSheet("font-size: 10px;")

            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(int(EQ_GAIN_MIN_DB * 10), int(EQ_GAIN_MAX_DB * 10))
            slider.setValue(int(bands_by_freq.get(freq, 0.0) * 10))
            slider.setFixedHeight(120)
            slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
            slider.setTickInterval(30)  # tick a cada 3 dB

            # Atualiza label e marca preset = "Personalizado"
            slider.valueChanged.connect(
                lambda val, lbl=value_lbl: lbl.setText(f"{val/10:+.1f} dB")
            )
            slider.valueChanged.connect(self._on_slider_moved)

            freq_lbl = QLabel(self._fmt_freq(freq))
            freq_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            freq_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 10px;")

            col.addWidget(value_lbl)
            col.addWidget(slider, alignment=Qt.AlignmentFlag.AlignHCenter)
            col.addWidget(freq_lbl)
            sliders_row.addLayout(col)

            self._eq_sliders.append((freq, slider))
            self._eq_value_labels.append(value_lbl)

        v.addLayout(sliders_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_restore = QPushButton("Restaurar padrão Voz Masculina")
        btn_restore.setObjectName("gray_btn")
        btn_restore.clicked.connect(self._restore_eq_default)
        btn_row.addWidget(btn_restore)
        v.addLayout(btn_row)

        # Flag para distinguir mudanças do usuário vs programáticas
        self._eq_programmatic_change = False

        return card

    def _build_card_noise(self, audio_cfg) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        v.addWidget(self._section_label("Redução de ruído"))

        self._noise_check = QCheckBox("Ativar")
        self._noise_check.setChecked(audio_cfg.noise_reduction_enabled)
        v.addWidget(self._noise_check)

        intensity_row = QHBoxLayout()
        intensity_row.addWidget(QLabel("Intensidade:"))
        intensity_row.addSpacing(8)

        self._noise_intensity_group = QButtonGroup(self)
        self._noise_intensity_radios = {}
        for i, label in enumerate(("baixa", "media", "alta")):
            rb = QRadioButton(label.capitalize())
            self._noise_intensity_group.addButton(rb, i)
            self._noise_intensity_radios[label] = rb
            intensity_row.addWidget(rb)

        # Marca o radio correspondente à config carregada
        current = audio_cfg.noise_reduction_intensity or "media"
        if current in self._noise_intensity_radios:
            self._noise_intensity_radios[current].setChecked(True)

        intensity_row.addStretch()
        v.addLayout(intensity_row)

        return card

    # -----------------------------------------------------------------------
    # Card 5: Nivelamento de volume (loudnorm)
    # -----------------------------------------------------------------------

    # Faixa do slider em LUFS (inteiro para QSlider)
    _LUFS_MIN = -30
    _LUFS_MAX = -6
    # Marcadores de referência: (valor_lufs, rótulo)
    _LUFS_MARKERS = [(-24, "quieto"), (-16, "padrão"), (-10, "alto")]

    def _build_card_norm(self, audio_cfg) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        v.addWidget(self._section_label("Nivelamento de volume"))

        hint = QLabel(
            "Normaliza o volume do áudio baixado e de cada vinheta "
            "separadamente antes de mixá-los (loudnorm EBU R128)."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        v.addWidget(hint)

        self._norm_check = QCheckBox("Ativar")
        self._norm_check.setChecked(audio_cfg.volume_norm_enabled)
        v.addWidget(self._norm_check)

        # ── Slider de LUFS ────────────────────────────────────────────────
        slider_frame = QFrame()
        slider_layout = QVBoxLayout(slider_frame)
        slider_layout.setContentsMargins(0, 4, 0, 0)
        slider_layout.setSpacing(2)

        self._norm_slider = QSlider(Qt.Orientation.Horizontal)
        self._norm_slider.setRange(self._LUFS_MIN, self._LUFS_MAX)
        self._norm_slider.setSingleStep(1)
        self._norm_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._norm_slider.setTickInterval(2)
        self._norm_slider.setValue(int(audio_cfg.volume_norm_lufs))
        slider_layout.addWidget(self._norm_slider)

        # Barra de marcadores de referência posicionados proporcionalmente
        marker_bar = QWidget()
        marker_bar.setFixedHeight(30)
        marker_layout = QHBoxLayout(marker_bar)
        marker_layout.setContentsMargins(0, 0, 0, 0)
        marker_layout.setSpacing(0)

        lufs_range = self._LUFS_MAX - self._LUFS_MIN  # 24

        def _add_marker(val, label):
            """Adiciona espaçador proporcional + label de marcador."""
            frac = (val - self._LUFS_MIN) / lufs_range
            lbl = QLabel(f"{val}\n{label}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lbl.setStyleSheet("font-size: 9px; color: gray;")
            return frac, lbl

        prev_frac = 0.0
        for val, label in self._LUFS_MARKERS:
            frac, lbl = _add_marker(val, label)
            # Espaçador entre o marcador anterior e este
            stretch = int(round((frac - prev_frac) * 100))
            marker_layout.addStretch(max(1, stretch))
            marker_layout.addWidget(lbl)
            prev_frac = frac
        # Espaçador final (do último marcador até o fim)
        marker_layout.addStretch(max(1, int(round((1.0 - prev_frac) * 100))))

        slider_layout.addWidget(marker_bar)

        # Linha com valor atual
        value_row = QHBoxLayout()
        self._norm_value_label = QLabel(
            f"Alvo: {int(audio_cfg.volume_norm_lufs)} LUFS"
        )
        self._norm_value_label.setStyleSheet(
            "font-size: 11px; font-family: Consolas, monospace;"
        )
        value_row.addWidget(self._norm_value_label)
        value_row.addStretch()
        slider_layout.addLayout(value_row)

        v.addWidget(slider_frame)

        # Atualiza label ao mover o slider
        self._norm_slider.valueChanged.connect(
            lambda val: self._norm_value_label.setText(f"Alvo: {val} LUFS")
        )

        return card

    # -----------------------------------------------------------------------
    # Card 6: Teste de configuração (PR 7)
    # -----------------------------------------------------------------------

    def _build_card_test(self) -> QFrame:
        """Card para gerar e tocar um preview com a config atual da UI."""
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        v.addWidget(self._section_label("Teste de configuração"))

        intro_text = QLabel(
            "Aplique a configuração atual em um áudio de exemplo para conferir "
            "o resultado antes de salvar e usar em produção."
        )
        intro_text.setWordWrap(True)
        intro_text.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        v.addWidget(intro_text)

        # ── Linha do arquivo de exemplo ────────────────────────────────────
        sample_row = QHBoxLayout()
        sample_row.setSpacing(6)

        self._test_sample_path = ""
        self._test_preview_path = ""
        self._test_running = False
        self._test_cancel_event = None
        self._test_thread = None

        self._test_sample_label = QLabel("Nenhum arquivo selecionado")
        self._test_sample_label.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")

        btn_select_sample = QPushButton("Selecionar exemplo")
        btn_select_sample.setObjectName("gray_btn")
        btn_select_sample.setFixedWidth(150)
        btn_select_sample.clicked.connect(self._select_test_sample)

        sample_row.addWidget(self._test_sample_label, stretch=1)
        sample_row.addWidget(btn_select_sample)
        v.addLayout(sample_row)

        # ── Linha de ações ─────────────────────────────────────────────────
        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)

        self._test_btn_generate = QPushButton("▷ Gerar preview")
        self._test_btn_generate.setStyleSheet("font-weight: bold;")
        self._test_btn_generate.setEnabled(False)
        self._test_btn_generate.clicked.connect(self._generate_test_preview)

        self._test_btn_play = QPushButton("▶ Tocar")
        self._test_btn_play.setObjectName("gray_btn")
        self._test_btn_play.setFixedWidth(110)
        self._test_btn_play.setEnabled(False)
        self._test_btn_play.clicked.connect(self._toggle_play_test_preview)

        self._test_btn_clear = QPushButton("Limpar")
        self._test_btn_clear.setObjectName("gray_btn")
        self._test_btn_clear.setFixedWidth(90)
        self._test_btn_clear.setEnabled(False)
        self._test_btn_clear.clicked.connect(self._clear_test_preview)

        self._test_btn_cancel = QPushButton("Cancelar")
        self._test_btn_cancel.setObjectName("red_btn")
        self._test_btn_cancel.setFixedWidth(100)
        self._test_btn_cancel.setVisible(False)
        self._test_btn_cancel.clicked.connect(self._cancel_test_preview)

        actions_row.addWidget(self._test_btn_generate)
        actions_row.addWidget(self._test_btn_play)
        actions_row.addWidget(self._test_btn_clear)
        actions_row.addWidget(self._test_btn_cancel)
        actions_row.addStretch()
        v.addLayout(actions_row)

        # ── Barra de progresso + status (interna ao card) ──────────────────
        self._test_progress = _ProgressBar()
        self._test_progress.setVisible(False)
        v.addWidget(self._test_progress)

        self._test_status_label = QLabel("")
        self._test_status_label.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        self._test_status_label.setWordWrap(True)
        v.addWidget(self._test_status_label)

        return card

    # -----------------------------------------------------------------------
    # Ações do card de teste
    # -----------------------------------------------------------------------

    def _select_test_sample(self):
        """Abre QFileDialog para escolher o arquivo de exemplo."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar arquivo de exemplo para teste",
            "",
            "Arquivos de áudio (*.mp3 *.m4a *.wav *.ogg *.flac);;Todos (*.*)",
        )
        if not path:
            return
        self._test_sample_path = path
        self._test_sample_label.setText(self._truncate(path))
        self._test_btn_generate.setEnabled(True)

    def _generate_test_preview(self):
        """Roda o pipeline de edição em uma thread, atualizando a UI."""
        import threading

        if self._test_running:
            return
        if not self._test_sample_path:
            self._set_test_status("Selecione um arquivo de exemplo primeiro.",
                                  is_error=True)
            return

        # Para qualquer player tocando antes de regenerar
        if self._currently_playing == "_test_":
            self._stop_playback()

        self._test_running = True
        self._test_cancel_event = threading.Event()
        self._set_test_running_ui(True)
        self._test_progress.set(0.0)
        self._set_test_status("Iniciando edição...")

        # Constrói config a partir do estado ATUAL da UI (não do config.json)
        config = self._read_audio_config_from_ui()

        # Caminho do preview no diretório de downloads (cleanup_downloads
        # remove tudo *.mp3 — vira limpeza automática no próximo processamento)
        preview_path = os.path.join(
            baixar_audio.DOWNLOAD_DIR, "_test_preview.mp3"
        )

        cancel_event = self._test_cancel_event
        sample_path  = self._test_sample_path

        # Prints diretos no terminal — ajudam no debug quando o preview trava.
        # `_log.info(...)` em audio_test_presenter já escreve em logs/, mas
        # estes prints garantem visibilidade IMEDIATA no console do dev.
        print(f"[PREVIEW] sample={sample_path}", flush=True)
        print(f"[PREVIEW] preview_path={preview_path}", flush=True)
        print(f"[PREVIEW] config.has_any_filter_enabled={config.has_any_filter_enabled}",
              flush=True)
        print(f"[PREVIEW] iniciando thread de edição...", flush=True)

        dispatcher = self._dispatcher

        def _worker():
            print("[PREVIEW worker] thread iniciada", flush=True)
            from composition_root import build_audio_test_presenter
            try:
                presenter = build_audio_test_presenter()
                print("[PREVIEW worker] presenter pronto, chamando execute()...",
                      flush=True)
                presenter.execute(
                    sample_path,
                    preview_path,
                    config,
                    cancel_event=cancel_event,
                    on_log=self._on_test_log,
                    on_progress=self._on_test_progress,
                )
                print(f"[PREVIEW worker] execute() concluído — emitindo completed",
                      flush=True)
                dispatcher.completed.emit(preview_path)
            except baixar_audio.OperacaoCancelada:
                print("[PREVIEW worker] cancelado pelo usuário", flush=True)
                dispatcher.cancelled.emit()
            except Exception as e:
                msg = str(e)
                print(f"[PREVIEW worker] ERRO: {msg}", flush=True)
                dispatcher.failed.emit(msg)

        self._test_thread = threading.Thread(target=_worker, daemon=True)
        self._test_thread.start()

    def _cancel_test_preview(self):
        """Sinaliza cancelamento para a thread de geração de preview."""
        if self._test_cancel_event is not None:
            self._test_cancel_event.set()
        self._set_test_status("Cancelando...")

    def _clear_test_preview(self):
        """Apaga o preview gerado e limpa o arquivo de exemplo selecionado."""
        # Para o player se estava tocando
        if self._currently_playing == "_test_":
            self._stop_playback()

        # Apaga o preview do disco
        if self._test_preview_path and os.path.exists(self._test_preview_path):
            try:
                os.remove(self._test_preview_path)
            except OSError:
                pass

        self._test_preview_path = ""
        self._test_sample_path  = ""
        self._test_sample_label.setText("Nenhum arquivo selecionado")
        self._test_progress.set(0.0)
        self._test_progress.setVisible(False)
        self._set_test_status("")
        self._test_btn_generate.setEnabled(False)
        self._test_btn_play.setEnabled(False)
        self._test_btn_clear.setEnabled(False)

    # -----------------------------------------------------------------------
    # Player do preview — abre _AudioPlayerDialog modal com controles completos
    # -----------------------------------------------------------------------

    def _toggle_play_test_preview(self):
        """
        Abre um diálogo modal com player completo (slider de posição,
        play/pause, skip ±10s). O preview persiste no disco mesmo após
        fechar — o usuário pode tocar várias vezes ou ajustar a config e
        gerar novo preview.
        """
        if not self._test_preview_path:
            return
        if not os.path.exists(self._test_preview_path):
            self._set_test_status(
                "Arquivo de preview não encontrado — gere novamente.",
                is_error=True,
            )
            self._test_btn_play.setEnabled(False)
            return

        # Para qualquer reprodução de vinheta em andamento antes de abrir
        # o player modal (evita dois áudios tocando ao mesmo tempo).
        if self._currently_playing is not None:
            self._stop_playback()

        dlg = _AudioPlayerDialog(self._test_preview_path, parent=self)
        dlg.exec()

    def _update_test_play_button(self):
        """
        Mantido por compatibilidade com `_update_play_buttons` (chamado pelo
        callback de mudança de estado do QMediaPlayer das vinhetas).
        O botão do preview agora abre um diálogo — não toggle entre Play/Stop.
        """
        self._test_btn_play.setText("▶ Tocar")

    # -----------------------------------------------------------------------
    # Callbacks da thread de preview (chamados via QTimer.singleShot)
    # -----------------------------------------------------------------------

    def _on_test_log(self, msg: str):
        """
        Callback do presenter/editor (chamado da worker thread).
        Emite o sinal — o slot `_set_test_status` roda na thread principal
        via QueuedConnection automático do Qt.
        """
        print(f"[PREVIEW log] {msg}", flush=True)
        self._dispatcher.log_received.emit(msg)

    def _on_test_progress(self, p: float):
        """Callback de progresso (worker thread → sinal → barra)."""
        if int(p * 100) % 10 == 0:
            print(f"[PREVIEW progress] {p * 100:.0f}%", flush=True)
        self._dispatcher.progress_changed.emit(float(p))

    def _on_test_done(self, preview_path: str):
        self._test_preview_path = preview_path
        self._test_progress.set(1.0)
        self._set_test_status(f"✓ Preview gerado: {os.path.basename(preview_path)}",
                              ok=True)
        self._set_test_running_ui(False)
        self._test_running = False
        self._test_cancel_event = None
        self._test_btn_play.setEnabled(True)
        self._test_btn_clear.setEnabled(True)

    def _on_test_cancelled(self):
        self._set_test_status("Geração cancelada.")
        self._test_progress.setVisible(False)
        self._set_test_running_ui(False)
        self._test_running = False
        self._test_cancel_event = None

    def _on_test_error(self, msg: str):
        self._set_test_status(f"Erro: {msg}", is_error=True)
        self._test_progress.setVisible(False)
        self._set_test_running_ui(False)
        self._test_running = False
        self._test_cancel_event = None

    # -----------------------------------------------------------------------
    # Estado visual do card de teste
    # -----------------------------------------------------------------------

    def _set_test_running_ui(self, running: bool):
        """Mostra/esconde botão Cancelar e desabilita os outros enquanto roda."""
        self._test_btn_generate.setEnabled(not running)
        self._test_btn_clear.setEnabled(not running and bool(self._test_preview_path))
        self._test_btn_play.setEnabled(not running and bool(self._test_preview_path))
        self._test_btn_cancel.setVisible(running)
        self._test_progress.setVisible(running or bool(self._test_preview_path))

    def _set_test_status(self, text: str, *, is_error: bool = False, ok: bool = False):
        if is_error:
            color = P.ERROR
        elif ok:
            color = P.GREEN
        else:
            color = P.HINT
        self._test_status_label.setText(text)
        self._test_status_label.setStyleSheet(f"color: {color}; font-size: 11px;")

    # -----------------------------------------------------------------------
    # Helpers da página de áudio
    # -----------------------------------------------------------------------

    @staticmethod
    def _fmt_freq(hz: int) -> str:
        return f"{hz} Hz" if hz < 1000 else f"{hz // 1000} kHz"

    @staticmethod
    def _truncate(path: str, maxlen: int = 42) -> str:
        if not path:
            return ""
        if len(path) <= maxlen:
            return path
        return "..." + path[-(maxlen - 3):]

    def _select_vinheta(self, kind: str):
        """
        Abre QFileDialog, copia o arquivo selecionado para `assets/vinhetas/`
        e persiste o caminho final.

        Estratégia:
          1. Apaga qualquer vinheta anterior do mesmo tipo (intro/outro) —
             garante que não acumule arquivos órfãos com extensões antigas.
          2. Copia o arquivo escolhido para `VINHETAS_DIR/{kind}.{ext}` (a
             extensão original é preservada — ffmpeg lê tudo).
          3. Atualiza o estado da UI com o NOVO caminho (dentro do app).
        """
        import shutil

        src, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar vinheta de " + ("entrada" if kind == "intro" else "saída"),
            "",
            "Arquivos de áudio (*.mp3 *.m4a *.wav *.ogg *.flac);;Todos (*.*)",
        )
        if not src:
            return

        try:
            # Garante a pasta de assets
            os.makedirs(baixar_audio.VINHETAS_DIR, exist_ok=True)

            # Apaga qualquer vinheta anterior do mesmo tipo (qualquer extensão)
            self._delete_existing_vinheta_files(kind)

            ext = os.path.splitext(src)[1].lower() or ".mp3"
            dest = os.path.join(baixar_audio.VINHETAS_DIR, f"{kind}{ext}")

            # shutil.copy2 preserva metadados; resolve overwrite atômico via
            # remove+copy se já existir (já tratamos acima).
            shutil.copy2(src, dest)
        except Exception as e:
            # Em caso de erro de I/O na cópia, mostra a mensagem no label do
            # path da vinheta (não temos um label de feedback dedicado nesta
            # sub-aba — o feedback global de save é da página principal).
            target_label = (
                self._intro_path_label if kind == "intro" else self._outro_path_label
            )
            target_label.setText(f"⚠ Erro ao copiar: {e}")
            target_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")
            return

        # Atualiza estado da UI com o caminho INTERNO (dentro do app)
        if kind == "intro":
            self._intro_path = dest
            self._intro_path_label.setText(self._truncate(dest))
            self._intro_btn_play.setEnabled(True)
            self._intro_btn_remove.setEnabled(True)
        else:
            self._outro_path = dest
            self._outro_path_label.setText(self._truncate(dest))
            self._outro_btn_play.setEnabled(True)
            self._outro_btn_remove.setEnabled(True)

    def _remove_vinheta(self, kind: str):
        """
        Limpa a vinheta selecionada e apaga o arquivo correspondente em
        `assets/vinhetas/` (best-effort — falhas de I/O não interrompem).
        """
        # Para o player se estava tocando esta vinheta
        if self._currently_playing == kind:
            self._stop_playback()

        # Remove o arquivo físico
        self._delete_existing_vinheta_files(kind)

        if kind == "intro":
            self._intro_path = ""
            self._intro_path_label.setText("Nenhum arquivo selecionado")
            self._intro_btn_play.setEnabled(False)
            self._intro_btn_remove.setEnabled(False)
        else:
            self._outro_path = ""
            self._outro_path_label.setText("Nenhum arquivo selecionado")
            self._outro_btn_play.setEnabled(False)
            self._outro_btn_remove.setEnabled(False)

    @staticmethod
    def _delete_existing_vinheta_files(kind: str):
        """
        Remove todos os arquivos `{kind}.*` existentes em VINHETAS_DIR.

        Best-effort: erros de I/O são silenciados — não devem interromper o
        fluxo principal (a substituição/limpeza pode ser tentada de novo).
        """
        import glob
        try:
            pattern = os.path.join(baixar_audio.VINHETAS_DIR, f"{kind}.*")
            for f in glob.glob(pattern):
                try:
                    os.remove(f)
                except OSError:
                    pass
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Preview da vinheta via QMediaPlayer
    # -----------------------------------------------------------------------

    def _ensure_media_player(self):
        if self._media_player is None:
            from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
            self._media_audio_output = QAudioOutput()
            self._media_player = QMediaPlayer()
            self._media_player.setAudioOutput(self._media_audio_output)
            self._media_player.playbackStateChanged.connect(
                self._on_playback_state_changed
            )

    def _toggle_play_vinheta(self, kind: str):
        from PyQt6.QtCore import QUrl
        path = self._intro_path if kind == "intro" else self._outro_path
        if not path:
            return

        # Se já estava tocando esta mesma vinheta — para
        if self._currently_playing == kind:
            self._stop_playback()
            return

        # Se estava tocando OUTRA vinheta — para a anterior antes
        if self._currently_playing is not None:
            self._stop_playback()

        self._ensure_media_player()
        self._media_player.setSource(QUrl.fromLocalFile(path))
        self._media_player.play()
        self._currently_playing = kind
        self._update_play_buttons()

    def _stop_playback(self):
        if self._media_player is not None:
            try:
                self._media_player.stop()
            except Exception:
                pass
        self._currently_playing = None
        self._update_play_buttons()

    def _on_playback_state_changed(self, state):
        # Quando o áudio termina sozinho, atualiza o botão
        try:
            from PyQt6.QtMultimedia import QMediaPlayer
            if state == QMediaPlayer.PlaybackState.StoppedState:
                self._currently_playing = None
                self._update_play_buttons()
        except Exception:
            pass

    def _update_play_buttons(self):
        intro_text = "■ Parar" if self._currently_playing == "intro" else "▶ Tocar"
        outro_text = "■ Parar" if self._currently_playing == "outro" else "▶ Tocar"
        self._intro_btn_play.setText(intro_text)
        self._outro_btn_play.setText(outro_text)
        # O card de teste só existe quando _build_card_test foi chamado
        if hasattr(self, "_test_btn_play"):
            self._update_test_play_button()

    # -----------------------------------------------------------------------
    # EQ helpers
    # -----------------------------------------------------------------------

    def _on_slider_moved(self, _value):
        """Mexer manual em qualquer slider muda o preset para 'Personalizado'."""
        if self._eq_programmatic_change:
            return
        if self._eq_preset_combo.currentIndex() != 1:
            self._eq_preset_combo.blockSignals(True)
            self._eq_preset_combo.setCurrentIndex(1)
            self._eq_preset_combo.blockSignals(False)

    def _on_preset_changed(self, idx: int):
        """Trocar combo Preset para 'Voz Masculina' restaura os sliders."""
        if idx == 0:
            self._restore_eq_default(_keep_combo=True)

    def _restore_eq_default(self, _keep_combo: bool = False):
        """Reseta sliders para o preset Voz Masculina."""
        from domain.audio_presets import EQ_PRESET_VOZ_MASCULINA
        self._eq_programmatic_change = True
        try:
            preset = dict(EQ_PRESET_VOZ_MASCULINA)
            for (freq, slider), value_lbl in zip(self._eq_sliders, self._eq_value_labels):
                gain = preset.get(freq, 0.0)
                slider.setValue(int(gain * 10))
                value_lbl.setText(f"{gain:+.1f} dB")
        finally:
            self._eq_programmatic_change = False
        if not _keep_combo:
            self._eq_preset_combo.blockSignals(True)
            self._eq_preset_combo.setCurrentIndex(0)
            self._eq_preset_combo.blockSignals(False)

    # -----------------------------------------------------------------------
    # Leitura do estado da UI → AudioEditConfig + persistência
    # -----------------------------------------------------------------------

    def _read_audio_config_from_ui(self):
        """Constrói um AudioEditConfig a partir do estado atual dos controles."""
        from domain.entities import AudioEditConfig, EqBand

        bands = tuple(
            EqBand(freq_hz=freq, gain_db=slider.value() / 10.0)
            for freq, slider in self._eq_sliders
        )

        # Intensidade selecionada (radio)
        intensity = "media"
        for label, rb in self._noise_intensity_radios.items():
            if rb.isChecked():
                intensity = label
                break

        return AudioEditConfig(
            intro_path                = self._intro_path or None,
            outro_path                = self._outro_path or None,
            intro_overlap_secs        = float(self._intro_overlap_spin.value()),
            outro_overlap_secs        = float(self._outro_overlap_spin.value()),
            fade_in_enabled           = bool(self._fade_in_check.isChecked()),
            fade_in_secs              = float(self._fade_in_spin.value()),
            fade_out_enabled          = bool(self._fade_out_check.isChecked()),
            fade_out_secs             = float(self._fade_out_spin.value()),
            eq_enabled                = bool(self._eq_check.isChecked()),
            eq_bands                  = bands,
            noise_reduction_enabled   = bool(self._noise_check.isChecked()),
            noise_reduction_intensity = intensity,
            volume_norm_enabled       = bool(self._norm_check.isChecked()),
            volume_norm_lufs          = float(self._norm_slider.value()),
        )

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        return lbl

    def hideEvent(self, event):
        """
        Para o player de preview se estiver tocando quando a aba é trocada
        (o usuário clica em outra sub-aba ou em outra página do app).
        """
        try:
            if self._media_player is not None:
                self._media_player.stop()
        except Exception:
            pass
        super().hideEvent(event)


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
