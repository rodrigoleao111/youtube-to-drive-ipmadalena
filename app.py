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
import shutil
import threading
import urllib.request
from datetime import datetime

from PyQt6.QtCore import QDate, QObject, QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPalette, QPixmap
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


APP_VERSION = "v3.5.1"

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
# Modos de entrada da tela de processamento
# ---------------------------------------------------------------------------
_SUB_BY_DATE = (
    "Selecione a data e clique em Processar para buscar os cultos publicados"
)
_SUB_BY_LINK = (
    "Cole o link do vídeo no YouTube — a busca por data é ignorada"
)

# Complemento das mensagens do gate do Spotify, para quem está FORA da aba de
# configurações (tooltip do botão na tela Início, aviso, log). Dentro da própria
# aba a frase é fechada de outro jeito — ver _refresh_spotify_account.
_SPOTIFY_ONDE = " em Configurações → Spotify."


def _upload_date_to_br(upload_date: str) -> str:
    """
    Converte o ``upload_date`` do YouTube (YYYYMMDD) para DD/MM/AAAA.

    É a data usada daqui para frente pelo fluxo por link: define a pasta do
    mês no Drive e a chave do histórico — os mesmos papéis que a data digitada
    tem no fluxo de busca. Quando o provedor não informa a data de publicação,
    cai para a data de hoje (melhor que abortar o processamento).
    """
    try:
        return datetime.strptime(upload_date, "%Y%m%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return datetime.now().strftime("%d/%m/%Y")


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
# QPalette — garante que o Fusion style use as cores corretas em controles
# que não têm regra QSS explícita (QComboBox, QDoubleSpinBox, QTabBar…)
# ---------------------------------------------------------------------------
def _build_palette(dark: bool) -> QPalette:
    """Constrói a QPalette para o tema escolhido."""
    pal = QPalette()
    if dark:
        pal.setColor(QPalette.ColorRole.Window,          QColor(P.D_BG))
        pal.setColor(QPalette.ColorRole.WindowText,      QColor(P.D_TEXT))
        pal.setColor(QPalette.ColorRole.Base,            QColor(P.D_INPUT))
        pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(P.D_CARD))
        pal.setColor(QPalette.ColorRole.Text,            QColor(P.D_TEXT))
        pal.setColor(QPalette.ColorRole.Button,          QColor(P.D_GRAY_BTN))
        pal.setColor(QPalette.ColorRole.ButtonText,      QColor(P.D_GRAY_TEXT))
        pal.setColor(QPalette.ColorRole.BrightText,      QColor(P.D_TEXT))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(P.D_TEXT_SUB))
        pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(P.D_CARD))
        pal.setColor(QPalette.ColorRole.ToolTipText,     QColor(P.D_TEXT))
        pal.setColor(QPalette.ColorRole.Highlight,       QColor(P.GREEN))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.Link,            QColor(P.GREEN))
        # Estado desabilitado
        pal.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.WindowText,      QColor(P.D_BTN_DIS_T))
        pal.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.Text,            QColor(P.D_BTN_DIS_T))
        pal.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.ButtonText,      QColor(P.D_BTN_DIS_T))
    else:
        pal.setColor(QPalette.ColorRole.Window,          QColor(P.L_BG))
        pal.setColor(QPalette.ColorRole.WindowText,      QColor(P.L_TEXT))
        pal.setColor(QPalette.ColorRole.Base,            QColor(P.L_INPUT))
        pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(P.L_CARD))
        pal.setColor(QPalette.ColorRole.Text,            QColor(P.L_TEXT))
        pal.setColor(QPalette.ColorRole.Button,          QColor(P.L_GRAY_BTN))
        pal.setColor(QPalette.ColorRole.ButtonText,      QColor(P.L_GRAY_TEXT))
        pal.setColor(QPalette.ColorRole.BrightText,      QColor(P.L_TEXT))
        pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(P.L_TEXT_SUB))
        pal.setColor(QPalette.ColorRole.ToolTipBase,     QColor(P.L_CARD))
        pal.setColor(QPalette.ColorRole.ToolTipText,     QColor(P.L_TEXT))
        pal.setColor(QPalette.ColorRole.Highlight,       QColor(P.GREEN))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
        pal.setColor(QPalette.ColorRole.Link,            QColor(P.GREEN))
        pal.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.WindowText,      QColor(P.L_BTN_DIS_T))
        pal.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.Text,            QColor(P.L_BTN_DIS_T))
        pal.setColor(QPalette.ColorGroup.Disabled,
                     QPalette.ColorRole.ButtonText,      QColor(P.L_BTN_DIS_T))
    return pal


# ---------------------------------------------------------------------------
# Stylesheet — Modo Escuro
# ---------------------------------------------------------------------------
_QSS_DARK = f"""
/* Cor e fonte globais — SEM background-color no QWidget: evita forçar
   autoFillBackground=True em QLabel/QCheckBox dentro de cards coloridos. */
QMainWindow, QWidget {{
    color: {P.D_TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow {{ background-color: {P.D_BG}; }}
QLabel  {{ color: {P.D_TEXT}; }}
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
/* Cor e fonte globais — SEM background-color no QWidget. */
QMainWindow, QWidget {{
    color: {P.L_TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow {{ background-color: {P.L_BG}; }}
QLabel  {{ color: {P.L_TEXT}; }}
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
# Logos SVG para ícones das abas de Configurações
# ---------------------------------------------------------------------------

_LOGO_SVG: dict[str, bytes] = {
    "drive": (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 87.3 78">'
        b'<path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3'
        b'l13.75-23.8h-27.5c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>'
        b'<path d="m43.65 25-13.75-23.8c-1.35.8-2.5 1.9-3.3 3.3'
        b'l-25.4 44a9.06 9.06 0 0 0-1.2 4.5h27.5z" fill="#00ac47"/>'
        b'<path d="m73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75'
        b'7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5h-27.502l5.852 11.5z"'
        b' fill="#ea4335"/>'
        b'<path d="m43.65 25 13.75-23.8c-1.35-.8-2.9-1.2-4.5-1.2'
        b'h-18.5c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>'
        b'<path d="m59.8 53h-32.3l-13.75 23.8c1.35.8 2.9 1.2 4.5 1.2'
        b'h50.8c1.6 0 3.15-.45 4.5-1.2z" fill="#2684fc"/>'
        b'<path d="m73.4 26.5-12.7-22c-.8-1.4-1.95-2.5-3.3-3.3'
        b'l-13.75 23.8 16.15 28h27.45c0-1.55-.4-3.1-1.2-4.5z"'
        b' fill="#ffba00"/></svg>'
    ),
    "youtube": (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        b'<path d="M23.495 6.205a3.007 3.007 0 0 0-2.088-2.088'
        b'c-1.87-.501-9.396-.501-9.396-.501s-7.507-.01-9.396.501'
        b'A3.007 3.007 0 0 0 .527 6.205a31.247 31.247 0 0 0-.522 5.805'
        b'a31.247 31.247 0 0 0 .522 5.783 3.007 3.007 0 0 0 2.088 2.088'
        b'c1.868.502 9.396.502 9.396.502s7.506 0 9.396-.502'
        b'a3.007 3.007 0 0 0 2.088-2.088 31.247 31.247 0 0 0 .5-5.783'
        b'a31.247 31.247 0 0 0-.5-5.805z'
        b'M9.609 15.601V8.408l6.264 3.602z" fill="#FF0000"/></svg>'
    ),
    "spotify": (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        b'<path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12'
        b'S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24'
        b'-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179'
        b'-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6'
        b' 11.64 1.32.42.18.479.659.301 1.02z'
        b'm1.44-3.3c-.301.42-.841.6-1.262.3'
        b'-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12'
        b'-1.14-.6-.12-.48.12-1.021.6-1.141'
        b'C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2z'
        b'm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301'
        b'c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381'
        b' 4.26-1.26 11.28-1.02 15.721 1.621'
        b'.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"'
        b' fill="#1DB954"/></svg>'
    ),
}


def _logo_icon(name: str, size: int = 18) -> "QIcon":
    """Renderiza SVG de logo de serviço como QIcon via QSvgRenderer.

    Fallback silencioso para QIcon() vazio se PyQt6.QtSvg não estiver
    disponível (improvável, mas protege o runtime em ambientes mínimos).
    """
    from PyQt6.QtGui import QIcon, QPixmap, QPainter
    try:
        from PyQt6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(bytearray(_LOGO_SVG[name]))
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception:
        return QIcon()


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
        # Spotify publishing — preenchido em _worker_phase2, consumido em _on_done
        self._spotify_pending: dict | None = None

        from composition_root import build_notifier, build_spotify_session
        self._notifier = build_notifier()
        # Uma única sessão do Spotify por execução (dona do perfil persistente
        # do navegador embutido). O perfil em si só é criado no primeiro uso.
        self._spotify_session = build_spotify_session()

        self._build_ui()

        # Timer de polling da fila (worker → GUI)
        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._process_queue)
        self._queue_timer.start(100)

        # Timer do diálogo de pré-publicação no Spotify (ver
        # _agendar_spotify_predialog): filho do App e guardado aqui para poder
        # ser cancelado — um QTimer.singleShot solto não pode.
        self._spotify_predialog_pending: dict | None = None
        self._spotify_predialog_timer = QTimer(self)
        self._spotify_predialog_timer.setSingleShot(True)
        self._spotify_predialog_timer.timeout.connect(self._abrir_spotify_predialog)

        # Atualiza yt-dlp em background
        threading.Thread(target=self._init_update_ytdlp, daemon=True).start()

        # Verifica atualização do app em background
        threading.Thread(target=self._check_update_worker, daemon=True).start()

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
        app = QApplication.instance()
        app.setPalette(_build_palette(self._dark_mode))
        app.setStyleSheet(qss)

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

        # Busca arquivos MP3 em DOWNLOAD_DIR (raiz e subpastas de 1 nível)
        os.makedirs(baixar_audio.DOWNLOAD_DIR, exist_ok=True)
        all_files = (
            _glob.glob(os.path.join(baixar_audio.DOWNLOAD_DIR, "*.mp3")) +
            _glob.glob(os.path.join(baixar_audio.DOWNLOAD_DIR, "*", "*.mp3"))
        )
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

        # Thumbnail (16:9 — imagem real ou fallback emoji)
        thumb = QLabel()
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setFixedHeight(118)
        thumb.setFixedWidth(220)

        # Procura capa.jpg na mesma pasta do MP3 (novo formato — subpastas);
        # se não encontrar, tenta o nome-base.jpg (retrocompatibilidade).
        _mp3_dir = os.path.dirname(fpath)
        _thumb_path = os.path.join(_mp3_dir, "capa.jpg")
        if not os.path.isfile(_thumb_path):
            _thumb_path = os.path.splitext(fpath)[0] + ".jpg"
        if os.path.isfile(_thumb_path):
            from PyQt6.QtGui import QPixmap
            _pix = QPixmap(_thumb_path).scaled(
                220, 118,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # Crop centralizado
            _x = (_pix.width() - 220) // 2
            _y = (_pix.height() - 118) // 2
            thumb.setPixmap(_pix.copy(_x, _y, 220, 118))
            thumb.setStyleSheet(
                "border-top-left-radius: 8px; border-top-right-radius: 8px;"
                " background: transparent;"
            )
        else:
            thumb.setText("🎵")
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
            btn_upload.setIcon(_logo_icon("drive", 16))
            btn_upload.setObjectName("gray_btn")
            btn_upload.setFixedWidth(32)
            btn_upload.setToolTip("Enviar ao Drive")
            btn_upload.clicked.connect(lambda: self._reupload_file(_fp, btn_upload))
            acts.addWidget(btn_upload)

        # Botão Spotify — aparece quando o Show ID está configurado e só fica
        # clicável quando também há conta logada (as duas condições do gate).
        _sp_cfg = baixar_audio.load_config().get("spotify", {})
        if _sp_cfg.get("show_id", "").strip():
            btn_spotify = QPushButton()
            btn_spotify.setIcon(_logo_icon("spotify", 16))
            btn_spotify.setObjectName("gray_btn")
            btn_spotify.setFixedWidth(32)
            _pronto, _motivo = self._spotify_publish_ready()
            btn_spotify.setEnabled(_pronto)
            btn_spotify.setToolTip(
                "Publicar no Spotify" if _pronto else _motivo + _SPOTIFY_ONDE
            )
            btn_spotify.clicked.connect(lambda: self._spotify_from_local(_fp))
            acts.addWidget(btn_spotify)

        # Botão "Abrir pasta no Explorer"
        btn_folder = QPushButton()
        btn_folder.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        btn_folder.setObjectName("gray_btn")
        btn_folder.setFixedWidth(32)
        btn_folder.setToolTip("Abrir pasta no Explorer")
        btn_folder.clicked.connect(lambda: self._reveal_in_explorer(_fp))
        acts.addWidget(btn_folder)

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
                mp3_dir = os.path.dirname(fpath)
                if os.path.normpath(mp3_dir) != os.path.normpath(baixar_audio.DOWNLOAD_DIR):
                    # MP3 está em subpasta — exclui a pasta inteira (MP4, capa, descrição)
                    shutil.rmtree(mp3_dir, ignore_errors=True)
                else:
                    os.remove(fpath)
                self._refresh_home()
            except Exception as e:
                QMessageBox.critical(
                    self, "Erro", f"Não foi possível excluir o arquivo:\n{e}"
                )

    def _reveal_in_explorer(self, fpath: str):
        """Abre o Explorer do Windows com o arquivo selecionado."""
        try:
            # /select, faz o Explorer abrir a pasta e destacar o arquivo
            import subprocess as _sp
            _sp.Popen(["explorer", "/select,", os.path.normpath(fpath)])
        except Exception:
            # Fallback: abre só a pasta sem selecionar o arquivo
            try:
                os.startfile(os.path.dirname(fpath))
            except Exception:
                pass

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

                # MP3 dentro de downloads/<pasta>/ → sobe como pacote (zip com
                # capa e descrição), igual ao fluxo normal. MP3 solto na raiz
                # de downloads/ não tem artefatos irmãos: sobe sozinho.
                pasta = os.path.dirname(os.path.abspath(fpath))
                subfolder = (
                    None
                    if pasta == os.path.abspath(baixar_audio.DOWNLOAD_DIR)
                    else pasta
                )
                audio_file = AudioFile(
                    path=fpath, title=title, video_id="", subfolder=subfolder,
                )
                presenter.upload_uc.execute(
                    audio_files=presenter.build_upload_package(audio_file),
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
                    btn.setIcon(_logo_icon("drive", 16)),
                ))

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _spotify_extras(audio_path: str) -> tuple[str, str]:
        """
        Localiza a descrição e a capa geradas pelo downloader para um áudio.

        Retorna ``(descricao, caminho_da_capa)`` — strings vazias quando não há.

        O downloader grava `descricao.txt` e `capa.jpg` **na subpasta do
        episódio**, com nome fixo (`YtDlpAudioDownloader._save_extras`). Antes do
        fluxo de subpastas os extras ficavam com o nome do áudio — daí o
        fallback para `<base>.txt` / `<base>.jpg`, que mantém os episódios
        antigos funcionando.
        """
        pasta = os.path.dirname(audio_path)
        base  = os.path.splitext(audio_path)[0]

        descricao = ""
        for cand in (os.path.join(pasta, "descricao.txt"), base + ".txt"):
            if not os.path.isfile(cand):
                continue
            try:
                with open(cand, encoding="utf-8") as fh:
                    descricao = fh.read().strip()
            except UnicodeDecodeError:
                # Arquivo antigo gravado na codepage do Windows: melhor uma
                # descrição com algum caractere torto do que campo vazio.
                try:
                    with open(cand, encoding="cp1252", errors="replace") as fh:
                        descricao = fh.read().strip()
                except Exception:
                    pass
            except Exception:
                pass
            if descricao:
                break

        capa = ""
        for cand in (os.path.join(pasta, "capa.jpg"), base + ".jpg"):
            if os.path.isfile(cand):
                capa = cand
                break

        return descricao, capa

    def _spotify_from_local(self, fpath: str):
        """
        Abre o diálogo de pré-publicação no Spotify para um arquivo local
        escolhido diretamente na tela Início (sem passar pelo pipeline de download).

        O ``audio_path`` é passado direto — não é necessário o glob de DOWNLOAD_DIR.
        """
        cfg    = baixar_audio.load_config()
        sp_cfg = cfg.get("spotify", {})
        show_id = sp_cfg.get("show_id", "").strip()

        pronto, motivo = self._spotify_publish_ready()
        if not pronto:
            QMessageBox.information(
                self, "Spotify não configurado", motivo + _SPOTIFY_ONDE
            )
            return

        title_text = os.path.splitext(os.path.basename(fpath))[0]
        prefix     = sp_cfg.get("title_prefix", "").strip()
        ep_title   = f"{prefix} {title_text}".strip() if prefix else title_text

        try:
            mtime    = datetime.fromtimestamp(os.path.getmtime(fpath))
            date_str = mtime.strftime("%d/%m/%Y")
        except Exception:
            date_str = ""

        # Descrição e capa que o downloader salvou junto do áudio — sem isso o
        # diálogo abria sempre com a descrição em branco e sem miniatura.
        description, cover_image_path = self._spotify_extras(fpath)
        if not description:
            _file_log(f"Spotify: descrição não encontrada para '{fpath}'.")

        dlg = _SpotifyPrePublishDialog(
            show_id          = show_id,
            video_id         = "",
            title            = ep_title,
            description      = description,
            date_str         = date_str,
            tags             = sp_cfg.get("default_tags", ""),
            audio_path       = fpath,
            cover_image_path = cover_image_path,
            parent           = self,
            session          = self._spotify_session,
        )
        dlg.exec()

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

        self._processar_sub = QLabel(_SUB_BY_DATE)
        self._processar_sub.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        layout.addWidget(self._processar_sub)
        layout.addSpacing(14)

        # ── Banner de atualização disponível ────────────────────────────────
        self._update_banner = QFrame()
        self._update_banner.setObjectName("update_banner")
        ub = QHBoxLayout(self._update_banner)
        ub.setContentsMargins(14, 8, 14, 8)
        self._update_lbl = QLabel()
        self._update_lbl.setStyleSheet(f"font-weight: bold; color: {P.GREEN};")
        btn_do_update = QPushButton("Atualizar agora")
        btn_do_update.setStyleSheet(
            f"background: {P.GREEN}; color: white; font-weight: bold;"
            f" border-radius: 4px; padding: 4px 12px;"
        )
        btn_do_update.clicked.connect(self._on_update_clicked)
        btn_dismiss = QPushButton("✕")
        btn_dismiss.setObjectName("gray_btn")
        btn_dismiss.setFixedWidth(28)
        btn_dismiss.setToolTip("Dispensar")
        btn_dismiss.clicked.connect(self._update_banner.hide)
        ub.addWidget(self._update_lbl)
        ub.addStretch()
        ub.addWidget(btn_do_update)
        ub.addSpacing(6)
        ub.addWidget(btn_dismiss)
        self._update_banner.hide()
        layout.addWidget(self._update_banner)

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

        # ── Card de origem (data OU link) ──────────────────────────────────
        date_frame = QFrame()
        date_frame.setObjectName("date_frame")
        card = QVBoxLayout(date_frame)
        card.setContentsMargins(16, 10, 16, 10)
        card.setSpacing(8)

        # Linha 1 — escolha do modo de entrada
        mode_row = QHBoxLayout()
        mode_row.setSpacing(18)
        self.mode_date_radio = QRadioButton("📅  Buscar por data")
        self.mode_link_radio = QRadioButton("🔗  Link do vídeo")
        self.mode_date_radio.setChecked(True)
        self.mode_date_radio.setToolTip(
            "Lista os vídeos publicados no canal na data informada."
        )
        self.mode_link_radio.setToolTip(
            "Processa direto o vídeo do link — sem a etapa de busca."
        )
        self._mode_group = QButtonGroup(page)
        self._mode_group.addButton(self.mode_date_radio, 0)
        self._mode_group.addButton(self.mode_link_radio, 1)
        self.mode_link_radio.toggled.connect(self._on_input_mode_changed)
        mode_row.addWidget(self.mode_date_radio)
        mode_row.addWidget(self.mode_link_radio)
        mode_row.addStretch()
        card.addLayout(mode_row)

        # Linha 2 — entrada (empilhada) + botões de ação
        dr = QHBoxLayout()
        dr.setSpacing(8)

        self._input_stack = QStackedWidget()

        # Página 0 — data
        date_page = QWidget()
        dpl = QHBoxLayout(date_page)
        dpl.setContentsMargins(0, 0, 0, 0)
        dpl.setSpacing(8)
        dpl.addWidget(QLabel("Data do culto:"))

        self.date_entry = QLineEdit()
        self.date_entry.setPlaceholderText("DD/MM/AAAA")
        self.date_entry.setFixedWidth(130)
        dpl.addWidget(self.date_entry)

        cal_btn = QPushButton("📅")
        cal_btn.setObjectName("icon_btn")
        cal_btn.setFixedWidth(38)
        cal_btn.clicked.connect(self._open_calendar)
        dpl.addWidget(cal_btn)
        dpl.addStretch()

        # Página 1 — link direto
        link_page = QWidget()
        lpl = QHBoxLayout(link_page)
        lpl.setContentsMargins(0, 0, 0, 0)
        lpl.setSpacing(8)
        lpl.addWidget(QLabel("Link do vídeo:"))

        self.link_entry = QLineEdit()
        self.link_entry.setPlaceholderText(
            "https://www.youtube.com/watch?v=..."
        )
        self.link_entry.setClearButtonEnabled(True)
        lpl.addWidget(self.link_entry, stretch=1)

        self._input_stack.addWidget(date_page)
        self._input_stack.addWidget(link_page)
        dr.addWidget(self._input_stack, stretch=1)

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

        card.addLayout(dr)

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
    # Página 2 — Configurações (Drive / YouTube / Spotify / Edição de áudio)
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
        self._cfg_tabs.setIconSize(QSize(18, 18))
        self._cfg_tabs.addTab(self._build_drive_tab(),   "  Drive")
        self._cfg_tabs.setTabIcon(0, _logo_icon("drive"))
        self._cfg_tabs.addTab(self._build_local_tab(),   "💾  Arquivos locais")
        self._cfg_tabs.addTab(self._build_youtube_tab(), "  YouTube")
        self._cfg_tabs.setTabIcon(2, _logo_icon("youtube"))
        self._cfg_tabs.addTab(self._build_spotify_tab(), "  Spotify")
        self._cfg_tabs.setTabIcon(3, _logo_icon("spotify"))
        self._audio_tab = _AudioSettingsTab(self)
        self._cfg_tabs.addTab(self._audio_tab,           "🎚  Edição de áudio")
        layout.addWidget(self._cfg_tabs, stretch=1)

        # ── Save unificado (persiste todas as abas em uma chamada) ──────────
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

    # ------------------------------------------------------------------
    def _build_drive_tab(self) -> QWidget:
        """Sub-aba 'Drive' — autorização, pasta, manter arquivos, log."""
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

        cfg = baixar_audio.load_config()
        _upload_enabled = bool(cfg.get("upload_to_drive", True))

        # ── Card: Fazer upload para o Drive ─────────────────────────────────
        # (primeiro na aba — controla a disponibilidade dos demais cards)
        up_card = QFrame()
        up_card.setObjectName("cfg_card")
        upc = QVBoxLayout(up_card)
        upc.setContentsMargins(20, 16, 20, 16)
        upc.setSpacing(8)

        tr_up = QHBoxLayout()
        tr_up.addWidget(self._icon_label("☁️", 22))
        lbl_up = QLabel("Upload para o Google Drive")
        lbl_up.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr_up.addWidget(lbl_up)
        tr_up.addStretch()
        upc.addLayout(tr_up)

        up_hint = QLabel(
            "Quando desabilitado, o processamento salva o áudio apenas localmente "
            "(visível na tela Início) e não faz upload para o Drive."
        )
        up_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        up_hint.setWordWrap(True)
        upc.addWidget(up_hint)

        self._cfg_upload_to_drive_check = QCheckBox("Fazer upload para o Google Drive")
        self._cfg_upload_to_drive_check.setChecked(_upload_enabled)
        upc.addWidget(self._cfg_upload_to_drive_check)
        layout.addWidget(up_card)

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

        hint = QLabel("Permite que o app envie arquivos para o seu Google Drive.")
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

        # ── Card: Pasta do Google Drive ─────────────────────────────────────
        dr_card = QFrame()
        dr_card.setObjectName("cfg_card")
        dc = QVBoxLayout(dr_card)
        dc.setContentsMargins(20, 16, 20, 16)
        dc.setSpacing(8)

        tr2 = QHBoxLayout()
        tr2.addWidget(self._icon_label("📁", 22))
        lbl2 = QLabel("Pasta do Google Drive")
        lbl2.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr2.addWidget(lbl2)
        tr2.addStretch()
        dc.addLayout(tr2)

        self._cfg_folder_entry = QLineEdit(cfg["drive_folder_id"])
        dc.addWidget(self._cfg_folder_entry)

        dr_hint = QLabel(
            "ID da pasta raiz no Drive (encontrado no final da URL da pasta)"
        )
        dr_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        dc.addWidget(dr_hint)
        layout.addWidget(dr_card)
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

        # ── Liga o toggle para habilitar / desabilitar cards dependentes ────
        # Apenas autenticação e pasta do Drive ficam bloqueados quando o upload
        # está desabilitado — manter arquivos e salvar vídeo são independentes.
        _drive_dependent_cards = [auth_card, dr_card]

        def _on_upload_toggle(checked: bool):
            from PyQt6.QtWidgets import QGraphicsOpacityEffect
            for card in _drive_dependent_cards:
                card.setEnabled(checked)
                if checked:
                    # Sem efeito quando habilitado — evita artefatos de
                    # compositing off-screen que escurecem widgets filhos.
                    card.setGraphicsEffect(None)
                else:
                    effect = QGraphicsOpacityEffect(card)
                    effect.setOpacity(0.35)
                    card.setGraphicsEffect(effect)

        self._cfg_upload_to_drive_check.checkStateChanged.connect(
            lambda state: _on_upload_toggle(
                state == Qt.CheckState.Checked
            )
        )
        _on_upload_toggle(_upload_enabled)  # estado inicial

        return tab

    # ------------------------------------------------------------------
    def _build_local_tab(self) -> QWidget:
        """Sub-aba 'Arquivos locais' — manter arquivos e salvar vídeo."""
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

        cfg = baixar_audio.load_config()

        # ── Card: Manter arquivos no dispositivo ────────────────────────────
        kf_card = QFrame()
        kf_card.setObjectName("cfg_card")
        kfc = QVBoxLayout(kf_card)
        kfc.setContentsMargins(20, 16, 20, 16)
        kfc.setSpacing(8)

        tr3 = QHBoxLayout()
        tr3.addWidget(self._icon_label("💾", 22))
        lbl3 = QLabel("Manter arquivos no dispositivo")
        lbl3.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr3.addWidget(lbl3)
        tr3.addStretch()
        kfc.addLayout(tr3)

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

        # ── Card: Salvar vídeo (MP4) ─────────────────────────────────────────
        sv_card = QFrame()
        sv_card.setObjectName("cfg_card")
        svc = QVBoxLayout(sv_card)
        svc.setContentsMargins(20, 16, 20, 16)
        svc.setSpacing(8)

        tr_sv = QHBoxLayout()
        tr_sv.addWidget(self._icon_label("🎬", 22))
        lbl_sv = QLabel("Salvar vídeo no dispositivo")
        lbl_sv.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr_sv.addWidget(lbl_sv)
        tr_sv.addStretch()
        svc.addLayout(tr_sv)

        sv_hint = QLabel(
            "Se habilitado, o arquivo MP4 (vídeo do trecho selecionado) é mantido "
            "na pasta do áudio após o processamento. Por padrão apenas o MP3 é salvo."
        )
        sv_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        sv_hint.setWordWrap(True)
        svc.addWidget(sv_hint)

        self._cfg_save_video_check = QCheckBox("Salvar vídeo (MP4)")
        self._cfg_save_video_check.setChecked(bool(cfg.get("save_video", False)))
        svc.addWidget(self._cfg_save_video_check)

        # ── Seleção de qualidade (habilitada somente quando save_video=True) ─
        quality_frame = QFrame()
        qfl = QHBoxLayout(quality_frame)
        qfl.setContentsMargins(20, 0, 0, 0)
        qfl.setSpacing(12)

        quality_lbl = QLabel("Qualidade do vídeo:")
        quality_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        quality_lbl.setToolTip(
            "Define a qualidade do arquivo MP4 salvo localmente.\n"
            "Alta: melhor resolução disponível (arquivo maior).\n"
            "Baixa: menor resolução (arquivo menor, carrega mais rápido).\n"
            "Não afeta o áudio final — apenas o vídeo salvo."
        )
        qfl.addWidget(quality_lbl)

        _saved_quality = cfg.get("video_quality", "alta")

        self._cfg_video_quality_alta = QRadioButton("Alta")
        self._cfg_video_quality_alta.setChecked(_saved_quality != "baixa")
        self._cfg_video_quality_alta.setToolTip("Melhor qualidade disponível no YouTube.")
        qfl.addWidget(self._cfg_video_quality_alta)

        self._cfg_video_quality_baixa = QRadioButton("Baixa")
        self._cfg_video_quality_baixa.setChecked(_saved_quality == "baixa")
        self._cfg_video_quality_baixa.setToolTip(
            "Menor qualidade disponível — arquivo significativamente menor."
        )
        qfl.addWidget(self._cfg_video_quality_baixa)

        _quality_group = QButtonGroup(quality_frame)
        _quality_group.addButton(self._cfg_video_quality_alta)
        _quality_group.addButton(self._cfg_video_quality_baixa)

        qfl.addStretch()
        svc.addWidget(quality_frame)

        # Sincroniza estado inicial e mudanças do checkbox com os radios
        def _on_save_video_toggle(checked: bool):
            quality_frame.setEnabled(checked)

        self._cfg_save_video_check.toggled.connect(_on_save_video_toggle)
        _on_save_video_toggle(bool(cfg.get("save_video", False)))

        layout.addWidget(sv_card)
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)
        return tab

    # ------------------------------------------------------------------
    def _build_youtube_tab(self) -> QWidget:
        """Sub-aba 'YouTube' — canal e capítulo automático."""
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

        cfg = baixar_audio.load_config()

        # ── Card: Canal do YouTube ──────────────────────────────────────────
        yt_card = QFrame()
        yt_card.setObjectName("cfg_card")
        yc = QVBoxLayout(yt_card)
        yc.setContentsMargins(20, 16, 20, 16)
        yc.setSpacing(8)

        tr = QHBoxLayout()
        tr.addWidget(self._icon_label("📺", 22))
        lbl = QLabel("Canal do YouTube")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr.addWidget(lbl)
        tr.addStretch()
        yc.addLayout(tr)

        self._cfg_channel_entry = QLineEdit(cfg["channel_url"])
        yc.addWidget(self._cfg_channel_entry)

        yt_hint = QLabel("Ex: https://www.youtube.com/@SeuCanal/streams")
        yt_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        yc.addWidget(yt_hint)
        layout.addWidget(yt_card)

        # ── Card: Capítulo automático ───────────────────────────────────────
        ch_card = QFrame()
        ch_card.setObjectName("cfg_card")
        cc = QVBoxLayout(ch_card)
        cc.setContentsMargins(20, 16, 20, 16)
        cc.setSpacing(8)

        tr2 = QHBoxLayout()
        tr2.addWidget(self._icon_label("📑", 22))
        lbl2 = QLabel("Capítulo automático")
        lbl2.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr2.addWidget(lbl2)
        tr2.addStretch()
        cc.addLayout(tr2)

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
        layout.addStretch()

        scroll.setWidget(container)
        outer.addWidget(scroll)
        return tab

    # ------------------------------------------------------------------
    def _build_spotify_tab(self) -> QWidget:
        """Sub-aba 'Spotify' — Show ID, prefixo de título, tags padrão."""
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

        sp_cfg = baixar_audio.load_config().get("spotify", {})

        # ── Card: Conta do Spotify ─────────────────────────────────────────
        # Primeiro card porque é a primeira condição: sem login não há
        # publicação, mesmo com o Show ID preenchido.
        acc_card = QFrame()
        acc_card.setObjectName("cfg_card")
        acc = QVBoxLayout(acc_card)
        acc.setContentsMargins(20, 16, 20, 16)
        acc.setSpacing(8)

        tr0 = QHBoxLayout()
        tr0.addWidget(self._icon_label("👤", 22))
        lbl0 = QLabel("Conta do Spotify")
        lbl0.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr0.addWidget(lbl0)
        tr0.addStretch()
        acc.addLayout(tr0)

        acc_hint = QLabel(
            "Entre na conta que administra o podcast. O login fica salvo neste "
            "computador, então você não precisa repetir a cada publicação."
        )
        acc_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        acc_hint.setWordWrap(True)
        acc.addWidget(acc_hint)

        sr0 = QHBoxLayout()
        self._cfg_spotify_status_label = QLabel("")
        self._cfg_spotify_login_btn = QPushButton("")
        self._cfg_spotify_login_btn.setFixedWidth(110)
        self._cfg_spotify_login_btn.clicked.connect(self._spotify_toggle_login)
        sr0.addWidget(self._cfg_spotify_status_label, stretch=1)
        sr0.addWidget(self._cfg_spotify_login_btn)
        acc.addLayout(sr0)

        # Diz qual das duas condições ainda falta para a publicação funcionar.
        self._cfg_spotify_gate_label = QLabel("")
        self._cfg_spotify_gate_label.setWordWrap(True)
        self._cfg_spotify_gate_label.setStyleSheet(f"font-size: 11px;")
        acc.addWidget(self._cfg_spotify_gate_label)
        layout.addWidget(acc_card)

        # ── Card: Show ID ──────────────────────────────────────────────────
        sid_card = QFrame()
        sid_card.setObjectName("cfg_card")
        sc = QVBoxLayout(sid_card)
        sc.setContentsMargins(20, 16, 20, 16)
        sc.setSpacing(8)

        tr = QHBoxLayout()
        tr.addWidget(self._icon_label("🎙", 22))
        lbl = QLabel("Show ID")
        lbl.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr.addWidget(lbl)
        tr.addStretch()
        sc.addLayout(tr)

        self._cfg_spotify_show_id = QLineEdit(sp_cfg.get("show_id", ""))
        self._cfg_spotify_show_id.setPlaceholderText(
            "Ex: 3a1b2c3d4e5f (URL do podcast no Spotify for Podcasters)"
        )
        sc.addWidget(self._cfg_spotify_show_id)

        sid_hint = QLabel(
            "ID do seu show no Spotify. Encontrado na URL do podcast: "
            "creators.spotify.com/pod/show/<show_id>/overview"
        )
        sid_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        sid_hint.setWordWrap(True)
        sc.addWidget(sid_hint)
        layout.addWidget(sid_card)

        # ── Card: Prefixo do título ────────────────────────────────────────
        pfx_card = QFrame()
        pfx_card.setObjectName("cfg_card")
        pc = QVBoxLayout(pfx_card)
        pc.setContentsMargins(20, 16, 20, 16)
        pc.setSpacing(8)

        tr2 = QHBoxLayout()
        tr2.addWidget(self._icon_label("✏️", 22))
        lbl2 = QLabel("Prefixo do título")
        lbl2.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr2.addWidget(lbl2)
        tr2.addStretch()
        pc.addLayout(tr2)

        pfx_hint = QLabel(
            "Texto adicionado antes do título do vídeo ao publicar no Spotify. "
            "Deixe em branco para usar o título original."
        )
        pfx_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        pfx_hint.setWordWrap(True)
        pc.addWidget(pfx_hint)

        self._cfg_spotify_title_prefix = QLineEdit(sp_cfg.get("title_prefix", ""))
        self._cfg_spotify_title_prefix.setPlaceholderText("Ex: IPMadalena — ")
        pc.addWidget(self._cfg_spotify_title_prefix)
        layout.addWidget(pfx_card)

        # ── Card: Tags padrão ─────────────────────────────────────────────
        tag_card = QFrame()
        tag_card.setObjectName("cfg_card")
        tc = QVBoxLayout(tag_card)
        tc.setContentsMargins(20, 16, 20, 16)
        tc.setSpacing(8)

        tr3 = QHBoxLayout()
        tr3.addWidget(self._icon_label("🏷", 22))
        lbl3 = QLabel("Tags padrão")
        lbl3.setStyleSheet("font-size: 14px; font-weight: bold;")
        tr3.addWidget(lbl3)
        tr3.addStretch()
        tc.addLayout(tr3)

        tag_hint = QLabel(
            "Tags pré-preenchidas ao publicar um episódio. Separe com vírgula."
        )
        tag_hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        tag_hint.setWordWrap(True)
        tc.addWidget(tag_hint)

        self._cfg_spotify_default_tags = QLineEdit(sp_cfg.get("default_tags", ""))
        self._cfg_spotify_default_tags.setPlaceholderText("Ex: pregação, evangelho, IPMadalena")
        tc.addWidget(self._cfg_spotify_default_tags)
        layout.addWidget(tag_card)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)
        self._refresh_spotify_account()
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

    # -----------------------------------------------------------------------
    # Conta do Spotify (login persistente no navegador embutido)
    # -----------------------------------------------------------------------

    def _spotify_publish_ready(self) -> tuple[bool, str]:
        """
        Diz se a publicação no Spotify está liberada e, se não, o que falta.

        Duas condições, ambas obrigatórias: uma conta logada e o Show ID
        configurado. Sem o Show ID não há para onde enviar; sem login o
        formulário do Spotify abriria na tela de credenciais.

        O motivo vem sem ponto final e sem dizer onde resolver — quem exibe
        completa a frase, porque dentro da própria aba de Spotify mandar o
        usuário "ir em Configurações → Spotify" seria absurdo.
        """
        sp_cfg = baixar_audio.load_config().get("spotify", {})
        if not sp_cfg.get("show_id", "").strip():
            return False, "Configure o Show ID do Spotify"
        if not self._spotify_session.is_logged_in():
            return False, "Entre na sua conta do Spotify"
        return True, ""

    def _refresh_spotify_account(self):
        """Atualiza o card de conta (status, botão) e o aviso do que falta."""
        logado = self._spotify_session.is_logged_in()
        if logado:
            self._cfg_spotify_status_label.setText("✓  Conectado")
            self._cfg_spotify_status_label.setStyleSheet(
                f"color: {P.GREEN}; font-weight: bold;"
            )
            self._cfg_spotify_login_btn.setText("Sair")
            self._cfg_spotify_login_btn.setStyleSheet(
                f"background: {P.RED}; border-radius: 4px;"
            )
        else:
            self._cfg_spotify_status_label.setText("✗  Não conectado")
            self._cfg_spotify_status_label.setStyleSheet(
                f"color: {P.ERROR}; font-weight: bold;"
            )
            self._cfg_spotify_login_btn.setText("Entrar")
            self._cfg_spotify_login_btn.setStyleSheet(
                f"background: {P.GREEN}; border-radius: 4px;"
            )

        pronto, motivo = self._spotify_publish_ready()
        if pronto:
            self._cfg_spotify_gate_label.setText(
                "✓  Publicação no Spotify liberada."
            )
            self._cfg_spotify_gate_label.setStyleSheet(
                f"color: {P.GREEN}; font-size: 11px;"
            )
        else:
            # Aqui o usuário já está na tela certa — só falta a ação.
            self._cfg_spotify_gate_label.setText(
                f"⚠  {motivo} para liberar a publicação."
            )
            self._cfg_spotify_gate_label.setStyleSheet(
                f"color: {P.WARN}; font-size: 11px;"
            )

    def _spotify_toggle_login(self):
        """Entra na conta (abre o navegador embutido) ou encerra a sessão."""
        if self._spotify_session.is_logged_in():
            resp = QMessageBox.question(
                self,
                "Sair do Spotify",
                "Encerrar a sessão do Spotify neste computador?\n\n"
                "Você precisará entrar de novo para publicar episódios.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
            self._spotify_session.logout()
            self._refresh_spotify_account()
            self._cfg_feedback_label.setText("Sessão do Spotify encerrada.")
            self._cfg_feedback_label.setStyleSheet(
                f"color: {P.WARN}; font-size: 11px;"
            )
            _file_log("Spotify: sessão encerrada pelo usuário.")
            return

        self._spotify_login_window = _SpotifyLoginWindow(
            session   = self._spotify_session,
            on_finish = self._on_spotify_login_finished,
            parent    = self,
        )
        self._spotify_login_window.show()

    def _on_spotify_login_finished(self, logado: bool):
        """Callback da janela de login — atualiza o card e dá o retorno na UI."""
        self._refresh_spotify_account()
        if logado:
            self._cfg_feedback_label.setText("Spotify conectado com sucesso!")
            self._cfg_feedback_label.setStyleSheet(
                f"color: {P.GREEN}; font-size: 11px;"
            )
            _file_log("Spotify: login concluído.")
        else:
            self._cfg_feedback_label.setText(
                "Login do Spotify não concluído. Tente novamente."
            )
            self._cfg_feedback_label.setStyleSheet(
                f"color: {P.WARN}; font-size: 11px;"
            )
            _file_log("Spotify: janela de login fechada sem concluir.")

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
            current["upload_to_drive"] = self._cfg_upload_to_drive_check.isChecked()
            current["save_video"]      = self._cfg_save_video_check.isChecked()
            current["video_quality"]   = (
                "baixa" if self._cfg_video_quality_baixa.isChecked() else "alta"
            )
            # `logged_in` é preservado: ele não vem de nenhum campo da tela, e
            # sobrescrever o dict inteiro deslogaria o usuário a cada save.
            _sp_atual = current.get("spotify") or {}
            current["spotify"] = {
                "show_id":      self._cfg_spotify_show_id.text().strip(),
                "title_prefix": self._cfg_spotify_title_prefix.text().strip(),
                "default_tags": self._cfg_spotify_default_tags.text().strip(),
                "logged_in":    bool(_sp_atual.get("logged_in", False)),
            }
            repo.save(current)
        except Exception as e:
            self._cfg_feedback_label.setText(f"Erro ao salvar: {e}")
            self._cfg_feedback_label.setStyleSheet(f"color: {P.ERROR}; font-size: 11px;")
            return

        # O Show ID acabou de mudar → o aviso do que falta para publicar
        # precisa refletir o novo estado.
        self._refresh_spotify_account()

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

                elif kind == "update_available":
                    self._show_update_banner(value["version"], value["download_url"])

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
    def _on_input_mode_changed(self, _checked: bool = False):
        """Alterna a entrada visível (data ⇄ link) e o subtítulo da página."""
        link_mode = self.mode_link_radio.isChecked()
        self._input_stack.setCurrentIndex(1 if link_mode else 0)
        self._processar_sub.setText(_SUB_BY_LINK if link_mode else _SUB_BY_DATE)

    def _start(self):
        if self.mode_link_radio.isChecked():
            return self._start_by_link()
        return self._start_by_date()

    def _start_by_link(self):
        """Valida o link e dispara o fluxo que pula a busca por data."""
        from infrastructure.youtube.ytdlp_source import extract_video_id

        url = self.link_entry.text().strip()
        if not url:
            self._show_error("Informe o link do vídeo no YouTube.")
            return
        if extract_video_id(url) is None:
            self._show_error(
                "Link inválido.\n\n"
                "Cole o link de um vídeo do YouTube, por exemplo:\n"
                "https://www.youtube.com/watch?v=XXXXXXXXXXX\n"
                "https://youtu.be/XXXXXXXXXXX\n"
                "https://www.youtube.com/live/XXXXXXXXXXX"
            )
            return
        if not self._prepare_run():
            return

        threading.Thread(
            target=self._worker_preflight,
            args=(None,),
            kwargs={"video_url": url},
            daemon=True,
        ).start()

    def _start_by_date(self):
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
        if not self._prepare_run():
            return

        threading.Thread(
            target=self._worker_preflight, args=(date_str,), daemon=True
        ).start()

    def _prepare_run(self) -> bool:
        """
        Checa autorização e prepara a UI para uma execução.

        Retorna False (sem alterar a UI) quando o Drive não está autorizado —
        os dois modos de entrada compartilham essa verificação.
        """
        if not baixar_audio.check_auth_status():
            self._show_error(
                "Google Drive não autorizado.\n\n"
                "Clique em 'Autorizar' no banner acima ou acesse Configurações."
            )
            return False

        self.log_box.clear()
        self._set_status("Verificando...", "running")
        self._cancel_event.clear()
        self._converting = False
        self._running = True
        self._show_bars()
        self._set_buttons_running(True)
        return True

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

    def _worker_preflight(self, date_str: str, video_url: str = None):
        """
        Checagens prévias comuns aos dois modos (internet, disco).

        No modo por data, segue para a checagem de histórico e a busca no
        canal. No modo por link (``video_url`` preenchido), não há data ainda
        — ela é derivada do próprio vídeo em ``_worker_link``.
        """
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

        if video_url:
            self._queue.put(("status", "Buscando vídeo..."))
            threading.Thread(
                target=self._worker_link, args=(video_url,), daemon=True
            ).start()
            return

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

    def _worker_link(self, url: str):
        """
        Fase 1 alternativa: resolve o vídeo do link e entra no fluxo comum.

        Pula a listagem do canal e o popup de seleção — o vídeo já é conhecido.
        A data usada daqui para frente (pasta do mês no Drive e histórico) vem
        da data de publicação do próprio vídeo.
        """
        try:
            video = self._build_presenter().fetch_video(
                url,
                cancel_event=self._cancel_event,
                on_log=lambda m: self._queue.put(("log", m)),
                on_status=lambda m: self._queue.put(("status", m)),
            )
            date_str = _upload_date_to_br(video.get("upload_date", ""))
            self._queue.put((
                "log",
                f"Vídeo selecionado: {video['title']} — data {date_str}.",
            ))

            # No modo link o histórico não bloqueia: o usuário apontou o vídeo
            # explicitamente. Apenas registra o aviso no log.
            try:
                if date_str in baixar_audio.load_history():
                    self._queue.put((
                        "log",
                        f"Obs.: {date_str} já consta no histórico — "
                        "processando mesmo assim.",
                    ))
            except Exception:
                pass

            self._queue.put(("check_chapters", (date_str, [video])))
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
            import time as _time
            _phase2_start = _time.time()
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

            # Prepara metadados para publicação no Spotify (se show_id configurado).
            # Thumbnail e descrição já foram salvos pelo downloader na subpasta;
            # aqui apenas localiza os caminhos para passar ao diálogo do Spotify.
            if segments:
                sp_cfg = baixar_audio.load_config().get("spotify", {})
                show_id = sp_cfg.get("show_id", "").strip()
                pronto, motivo = self._spotify_publish_ready()
                if not pronto and show_id:
                    # Show ID preenchido = o usuário quer publicar, então o
                    # desvio precisa aparecer no log (antes era silencioso).
                    # Sem Show ID nenhum, o Spotify não faz parte do fluxo
                    # dele — avisar a cada execução seria só ruído.
                    self._queue.put((
                        "log",
                        "Publicação no Spotify não oferecida: "
                        + motivo + _SPOTIFY_ONDE,
                    ))
                elif pronto:
                    first    = segments[0]
                    prefix   = sp_cfg.get("title_prefix", "")
                    ep_title = (prefix + first.get("title", "")) if prefix else first.get("title", "")
                    video_id = first.get("video_id", "")

                    # Descrição: lê do descricao.txt gerado pelo downloader na subpasta.
                    # build_output_names é a MESMA função usada pelo downloader —
                    # sanitize_folder_name sozinho erraria a pasta quando o nome
                    # precisou ser encurtado pelo limite de caminho do Windows.
                    description = ""
                    try:
                        from infrastructure.youtube.ytdlp_source import build_output_names
                        _pasta, _ = build_output_names(
                            baixar_audio.DOWNLOAD_DIR, first.get("title", "")
                        )
                        _subfolder = os.path.join(
                            baixar_audio.DOWNLOAD_DIR, _pasta,
                        )
                        _txt = os.path.join(_subfolder, "descricao.txt")
                        if os.path.isfile(_txt):
                            with open(_txt, encoding="utf-8") as _fh:
                                description = _fh.read()
                    except Exception:
                        pass

                    # cover_image_path: capa.jpg na subpasta do primeiro segmento
                    cover_image_path = ""
                    try:
                        _capa = os.path.join(_subfolder, "capa.jpg")
                        if os.path.isfile(_capa):
                            cover_image_path = _capa
                    except Exception:
                        pass

                    self._spotify_pending = {
                        "show_id":          show_id,
                        "video_id":         video_id,
                        "title":            ep_title,
                        "description":      description,
                        "date_str":         date_str,
                        "tags":             sp_cfg.get("default_tags", ""),
                        "cover_image_path": cover_image_path,
                    }
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
        self._refresh_spotify_account()

    def _check_auth_visibility(self):
        if baixar_audio.check_auth_status():
            self._auth_banner.hide()
        else:
            self._auth_banner.show()

    # -----------------------------------------------------------------------
    # Auto-update
    # -----------------------------------------------------------------------

    def _check_update_worker(self):
        try:
            from infrastructure.updater.github_updater import check_latest_version
            result = check_latest_version(baixar_audio.GITHUB_REPO, APP_VERSION)
            if result:
                self._queue.put(("update_available", result))
        except Exception:
            pass  # falha silenciosa — sem rede, GitHub indisponível, etc.

    def _show_update_banner(self, version: str, download_url: str):
        self._pending_update_url = download_url
        self._update_lbl.setText(f"🎉  Nova versão {version} disponível")
        self._update_banner.show()

    def _on_update_clicked(self):
        if not getattr(sys, "frozen", False):
            QMessageBox.information(
                self,
                "Atualização disponível",
                "Você está rodando em modo script.\n"
                "Atualize via git pull ou baixe o instalador no GitHub Releases.",
            )
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Atualizar IPMadalena")
        msg.setText(
            "O app será fechado e o instalador iniciará automaticamente.\n"
            "Deseja continuar?"
        )
        msg.setIcon(QMessageBox.Icon.Question)
        btn_sim = msg.addButton("Atualizar", QMessageBox.ButtonRole.YesRole)
        msg.addButton("Agora não", QMessageBox.ButtonRole.NoRole)
        msg.exec()
        if msg.clickedButton() is not btn_sim:
            return

        dlg = _UpdateDownloadDialog(self._pending_update_url, parent=self)
        dlg.exec()

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

        # Abre diálogo de pré-publicação no Spotify (se configurado)
        if self._spotify_pending:
            pending = self._spotify_pending
            self._spotify_pending = None
            self._agendar_spotify_predialog(pending)

    def _on_error(self, msg: str):
        self._running = False
        self._converting = False
        self._set_buttons_running(False)
        self._hide_bars()
        self._set_status("Erro — veja o log abaixo", "error")
        self._append_log(f"ERRO: {msg}")
        _file_log(f"ERRO: {msg}")
        self._show_error(msg)

    # Espera antes de abrir o diálogo: dá tempo de a notificação de conclusão
    # aparecer e de a GUI assentar antes de um modal roubar o foco.
    _SPOTIFY_PREDIALOG_MS = 800

    def _agendar_spotify_predialog(self, pending: dict) -> None:
        """
        Agenda a abertura do diálogo de pré-publicação para daqui a
        ``_SPOTIFY_PREDIALOG_MS``.

        Usa o timer próprio criado no ``__init__`` (filho do App) em vez de
        ``QTimer.singleShot``: um singleShot solto **não pode ser cancelado**.
        Se o usuário fechasse o app dentro da janela de 800 ms, o timer órfão
        disparava depois e abria um diálogo modal sobre uma janela já morta —
        e, nos testes, disparava dentro do ``update()`` do Tcl/Tk
        (``customtkinter``, que pompa a fila de mensagens do Windows e com ela
        os timers do Qt), travando a suíte para sempre no ``exec()`` do modal.
        Ver ``closeEvent``, que para o timer.
        """
        self._spotify_predialog_pending = pending
        self._spotify_predialog_timer.stop()      # substitui agendamento anterior
        self._spotify_predialog_timer.start(self._SPOTIFY_PREDIALOG_MS)

    def _abrir_spotify_predialog(self) -> None:
        """Slot do ``_spotify_predialog_timer`` — consome o pedido agendado."""
        pending = self._spotify_predialog_pending
        self._spotify_predialog_pending = None
        if pending:
            self._show_spotify_predialog(pending)

    def _show_spotify_predialog(self, pending: dict):
        """
        Abre o diálogo de pré-publicação no Spotify for Podcasters.

        ``pending`` é o dict construído em ``_worker_phase2`` com chaves:
        ``show_id``, ``video_id``, ``title``, ``date_str``, ``tags``,
        ``cover_image_path`` (opcional).
        """
        import glob as _glob
        # Localiza o MP3 mais recente em DOWNLOAD_DIR — inclui subpastas
        # criadas pelo novo fluxo MP4-first (downloads/{título}/arquivo.mp3)
        candidates = sorted(
            _glob.glob(os.path.join(baixar_audio.DOWNLOAD_DIR, "*.mp3")) +
            _glob.glob(os.path.join(baixar_audio.DOWNLOAD_DIR, "*", "*.mp3")),
            key=os.path.getmtime,
            reverse=True,
        )
        audio_path = candidates[0] if candidates else ""

        # Fallback para os extras: o `pending` os traz de `_worker_phase2`, mas
        # se a subpasta não foi encontrada lá, procuramos ao lado do áudio.
        description      = pending.get("description", "")
        cover_image_path = pending.get("cover_image_path", "")
        if audio_path and (not description or not cover_image_path):
            _desc, _capa = self._spotify_extras(audio_path)
            description      = description      or _desc
            cover_image_path = cover_image_path or _capa

        dlg = _SpotifyPrePublishDialog(
            show_id          = pending["show_id"],
            video_id         = pending["video_id"],
            title            = pending["title"],
            description      = description,
            date_str         = pending["date_str"],
            tags             = pending["tags"],
            audio_path       = audio_path,
            cover_image_path = cover_image_path,
            parent           = self,
            session          = self._spotify_session,
        )
        dlg.exec()

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
        # Sem isso, um diálogo de pré-publicação agendado nos últimos 800 ms
        # abriria depois da janela fechar (ver _agendar_spotify_predialog).
        self._spotify_predialog_timer.stop()
        self._spotify_predialog_pending = None
        event.accept()


# ---------------------------------------------------------------------------
# Dialog de download de atualização
# ---------------------------------------------------------------------------
class _UpdateDownloadDialog(QDialog):
    """
    Dialog modal que baixa o instalador de uma nova versão e o executa.

    Iniciado automaticamente ao abrir (QTimer.singleShot). Mostra barra de
    progresso e label de status. Ao concluir: executa o instalador via
    subprocess.Popen e encerra o app com sys.exit(0).
    """

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self._cancelled = False

        self.setWindowTitle("Baixando atualização")
        self.setFixedWidth(420)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        self._status_lbl = QLabel("Preparando download...")
        layout.addWidget(self._status_lbl)

        self._bar = QProgressBar()
        self._bar.setMinimum(0)
        self._bar.setMaximum(100)
        self._bar.setValue(0)
        layout.addWidget(self._bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("gray_btn")
        btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        QTimer.singleShot(0, self._start_download)

    def _start_download(self):
        self._status_lbl.setText("Baixando instalador...")
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        import tempfile
        dest = os.path.join(tempfile.gettempdir(), "IPMadalena_Update.exe")
        try:
            from infrastructure.updater.github_updater import download_release
            download_release(
                self._url,
                dest,
                on_progress=lambda p: QTimer.singleShot(
                    0, lambda val=p: self._bar.setValue(int(val * 100))
                ),
            )
            if not self._cancelled:
                QTimer.singleShot(0, lambda: self._on_done(dest))
        except Exception as e:
            if not self._cancelled:
                QTimer.singleShot(0, lambda: self._on_error(str(e)))

    def _on_done(self, installer_path: str):
        self._status_lbl.setText("Download concluído. Iniciando instalador...")
        self._bar.setValue(100)
        subprocess.Popen([installer_path])
        sys.exit(0)

    def _on_error(self, msg: str):
        self._status_lbl.setText(f"Erro no download: {msg}")
        QMessageBox.critical(self, "Erro", f"Não foi possível baixar a atualização:\n{msg}")
        self.reject()

    def _on_cancel(self):
        self._cancelled = True
        self.reject()


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
        layout.addWidget(self._build_card_bg_music(audio_cfg))
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

    # -----------------------------------------------------------------------
    # Card 2: Música de fundo
    # -----------------------------------------------------------------------

    def _build_card_bg_music(self, audio_cfg) -> QFrame:
        """Card para configurar e habilitar música de fundo no episódio."""
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 12, 16, 14)
        v.setSpacing(10)

        v.addWidget(self._section_label("Música de fundo"))

        hint = QLabel(
            "Mistura uma faixa de música ao áudio do episódio. "
            "A música toca em loop no volume configurado, com fade in/out, "
            "sempre mais baixa que o áudio principal."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        v.addWidget(hint)

        # ── Seleção do arquivo ────────────────────────────────────────────
        self._bg_music_path = audio_cfg.bg_music_path or ""

        file_row = QHBoxLayout()
        file_row.setSpacing(6)

        self._bg_music_path_label = QLabel(
            self._truncate(self._bg_music_path) or "Nenhum arquivo selecionado"
        )
        self._bg_music_path_label.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        self._bg_music_path_label.setMinimumWidth(220)

        btn_select_bg = QPushButton("Selecionar")
        btn_select_bg.setObjectName("gray_btn")
        btn_select_bg.setFixedWidth(110)
        btn_select_bg.clicked.connect(self._select_bg_music)
        btn_select_bg.setToolTip(
            "Escolha um arquivo de música para tocar de fundo durante o episódio.\n"
            "O arquivo é copiado para dentro do app (MP3, WAV, M4A, OGG, FLAC)."
        )

        btn_remove_bg = QPushButton("Remover")
        btn_remove_bg.setObjectName("gray_btn")
        btn_remove_bg.setFixedWidth(90)
        btn_remove_bg.clicked.connect(self._remove_bg_music)
        btn_remove_bg.setEnabled(bool(self._bg_music_path))
        btn_remove_bg.setToolTip("Remove a música de fundo configurada.")
        self._bg_music_btn_remove = btn_remove_bg

        file_row.addWidget(self._bg_music_path_label, stretch=1)
        file_row.addWidget(btn_select_bg)
        file_row.addWidget(btn_remove_bg)
        v.addLayout(file_row)

        # ── Toggles ───────────────────────────────────────────────────────
        self._bg_music_check = QCheckBox("Ativar música de fundo")
        self._bg_music_check.setChecked(audio_cfg.bg_music_enabled)
        self._bg_music_check.setToolTip(
            "Quando marcado, a música escolhida é misturada ao áudio do episódio\n"
            "antes do upload. A voz fica sempre mais alta que a música."
        )
        v.addWidget(self._bg_music_check)

        self._bg_music_loop_check = QCheckBox("Repetir em loop até o fim do episódio")
        self._bg_music_loop_check.setChecked(audio_cfg.bg_music_loop)
        self._bg_music_loop_check.setToolTip(
            "Marcado: a música repete automaticamente se for mais curta que o episódio.\n"
            "Desmarcado: a música toca uma vez e para; o sermão continua sem música."
        )
        v.addWidget(self._bg_music_loop_check)

        # ── Parâmetros ────────────────────────────────────────────────────
        params_frame = QFrame()
        params_layout = QVBoxLayout(params_frame)
        params_layout.setContentsMargins(0, 4, 0, 0)
        params_layout.setSpacing(6)

        def _spin_row(label_text, value, min_val, max_val, step, suffix, decimals=1):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(180)
            spin = QDoubleSpinBox()
            spin.setRange(min_val, max_val)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
            spin.setSuffix(suffix)
            spin.setValue(float(value))
            spin.setFixedWidth(100)
            row.addWidget(lbl)
            row.addWidget(spin)
            row.addStretch()
            return row, spin

        # Volume: armazenado como 0.0–1.0, exibido como 0–100 %
        vol_row = QHBoxLayout()
        vol_lbl = QLabel("Volume da música:")
        vol_lbl.setFixedWidth(180)

        _vol_tt = (
            "Volume da música em relação à voz (1–50 %).\n"
            "10–15 %: discreta, mal perceptível — ideal para pregações longas.\n"
            "20–30 %: presente, boa para momentos de adoração.\n"
            "Acima de 35 %: pode disputar atenção com a voz."
        )
        vol_lbl.setToolTip(_vol_tt)

        self._bg_music_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._bg_music_vol_slider.setRange(1, 50)   # 1–50 %
        self._bg_music_vol_slider.setSingleStep(1)
        self._bg_music_vol_slider.setValue(
            max(1, min(50, round(audio_cfg.bg_music_volume * 100)))
        )
        self._bg_music_vol_slider.setFixedWidth(150)
        self._bg_music_vol_slider.setToolTip(_vol_tt)

        self._bg_music_vol_label = QLabel(
            f"{self._bg_music_vol_slider.value()} %"
        )
        self._bg_music_vol_label.setFixedWidth(40)
        self._bg_music_vol_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px;"
        )
        self._bg_music_vol_slider.valueChanged.connect(
            lambda v: self._bg_music_vol_label.setText(f"{v} %")
        )

        vol_row.addWidget(vol_lbl)
        vol_row.addWidget(self._bg_music_vol_slider)
        vol_row.addWidget(self._bg_music_vol_label)
        vol_row.addStretch()
        params_layout.addLayout(vol_row)

        delay_row, self._bg_music_delay_spin = _spin_row(
            "Intro musical (s antes da voz):",
            audio_cfg.bg_music_delay, 0.0, 60.0, 0.5, " s",
        )
        self._bg_music_delay_spin.setToolTip(
            "Quantos segundos de música tocam sozinhos antes da voz começar.\n"
            "Cria uma abertura musical antes do sermão.\n"
            "0 = música e voz começam juntos desde o início."
        )
        params_layout.addLayout(delay_row)

        fi_row, self._bg_music_fade_in_spin = _spin_row(
            "Fade in:",
            audio_cfg.bg_music_fade_in, 0.0, 30.0, 0.5, " s",
        )
        self._bg_music_fade_in_spin.setToolTip(
            "A música sobe gradualmente do silêncio ao volume configurado\n"
            "durante esse tempo (em segundos). 0 = começa no volume cheio."
        )
        params_layout.addLayout(fi_row)

        fo_row, self._bg_music_fade_out_spin = _spin_row(
            "Fade out:",
            audio_cfg.bg_music_fade_out, 0.0, 30.0, 0.5, " s",
        )
        self._bg_music_fade_out_spin.setToolTip(
            "A música diminui gradualmente até o silêncio nos últimos N segundos\n"
            "do episódio. 0 = a música para abruptamente no final."
        )
        params_layout.addLayout(fo_row)

        v.addWidget(params_frame)
        return card

    def _select_bg_music(self):
        """Abre seletor de arquivo e copia a música para VINHETAS_DIR."""
        import shutil

        src, _ = QFileDialog.getOpenFileName(
            self, "Selecionar música de fundo", "",
            "Arquivos de áudio (*.mp3 *.m4a *.wav *.ogg *.flac);;Todos (*.*)",
        )
        if not src:
            return

        try:
            os.makedirs(baixar_audio.VINHETAS_DIR, exist_ok=True)

            # Remove arquivo anterior de música de fundo
            import glob as _glob
            for old in _glob.glob(
                os.path.join(baixar_audio.VINHETAS_DIR, "bg_music.*")
            ):
                try:
                    os.remove(old)
                except Exception:
                    pass

            ext  = os.path.splitext(src)[1].lower() or ".mp3"
            dest = os.path.join(baixar_audio.VINHETAS_DIR, f"bg_music{ext}")
            shutil.copy2(src, dest)
        except Exception as e:
            self._bg_music_path_label.setText(f"⚠ Erro ao copiar: {e}")
            self._bg_music_path_label.setStyleSheet(
                f"color: {P.ERROR}; font-size: 11px;"
            )
            return

        self._bg_music_path = dest
        self._bg_music_path_label.setText(self._truncate(dest))
        self._bg_music_path_label.setStyleSheet(
            f"color: {P.HINT}; font-size: 11px;"
        )
        self._bg_music_btn_remove.setEnabled(True)

    def _remove_bg_music(self):
        """Remove a música de fundo selecionada."""
        import glob as _glob
        for f in _glob.glob(
            os.path.join(baixar_audio.VINHETAS_DIR, "bg_music.*")
        ):
            try:
                os.remove(f)
            except Exception:
                pass

        self._bg_music_path = ""
        self._bg_music_path_label.setText("Nenhum arquivo selecionado")
        self._bg_music_path_label.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        self._bg_music_btn_remove.setEnabled(False)
        self._bg_music_check.setChecked(False)

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
        _tt_vinheta = (
            "Abre explorador de arquivos para escolher o arquivo de áudio da vinheta.\n"
            "Formatos suportados: MP3, M4A, WAV, OGG, FLAC.\n"
            "O arquivo é copiado para dentro do app — você pode mover o original depois."
        )
        btn_select.setToolTip(_tt_vinheta)
        path_label.setToolTip(_tt_vinheta)

        btn_play = QPushButton("▶ Tocar")
        btn_play.setObjectName("gray_btn")
        btn_play.setFixedWidth(90)
        btn_play.clicked.connect(lambda: self._toggle_play_vinheta(kind))
        btn_play.setEnabled(bool(initial_path))
        btn_play.setToolTip("Pré-escuta a vinheta selecionada.")

        btn_remove = QPushButton("Remover")
        btn_remove.setObjectName("gray_btn")
        btn_remove.setFixedWidth(90)
        btn_remove.clicked.connect(lambda: self._remove_vinheta(kind))
        btn_remove.setEnabled(bool(initial_path))
        btn_remove.setToolTip("Remove a vinheta desta posição (o arquivo original não é apagado).")

        row.addWidget(path_label, stretch=1)
        row.addWidget(btn_select)
        row.addWidget(btn_play)
        row.addWidget(btn_remove)
        block.addLayout(row)

        _overlap_tt = (
            "Número de segundos em que a vinheta e o sermão tocam simultaneamente\n"
            "antes da vinheta terminar (acrossfade). 0 = corte direto sem sobreposição.\n"
            "Exemplo: 1,5 s cria uma transição suave sem silêncio entre os trechos."
        )
        overlap_lbl = QLabel("Sobreposição com áudio:")
        overlap_lbl.setToolTip(_overlap_tt)
        overlap_row = QHBoxLayout()
        overlap_row.addWidget(overlap_lbl)
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 10.0)
        spin.setSingleStep(0.5)
        spin.setDecimals(1)
        spin.setSuffix(" s")
        spin.setValue(float(initial_overlap or 0.0))
        spin.setFixedWidth(90)
        spin.setToolTip(_overlap_tt)
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

        hint_fade = QLabel(
            "Aplica transições suaves de volume no início e/ou fim do áudio principal "
            "(sem contar as vinhetas)."
        )
        hint_fade.setWordWrap(True)
        hint_fade.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
        v.addWidget(hint_fade)

        # Fade in
        _fi_tt = (
            "O áudio sobe gradualmente do silêncio ao volume normal.\n"
            "Elimina cliques, chiados ou barulhos abruptos no início da gravação."
        )
        row_in = QHBoxLayout()
        self._fade_in_check = QCheckBox("Fade in")
        self._fade_in_check.setChecked(audio_cfg.fade_in_enabled)
        self._fade_in_check.setToolTip(_fi_tt)
        row_in.addWidget(self._fade_in_check)
        row_in.addSpacing(12)
        dur_in_lbl = QLabel("Duração:")
        dur_in_lbl.setToolTip("Tempo da transição em segundos.")
        row_in.addWidget(dur_in_lbl)
        self._fade_in_spin = QDoubleSpinBox()
        self._fade_in_spin.setRange(0.0, 10.0)
        self._fade_in_spin.setSingleStep(0.5)
        self._fade_in_spin.setDecimals(1)
        self._fade_in_spin.setSuffix(" s")
        self._fade_in_spin.setValue(float(audio_cfg.fade_in_secs))
        self._fade_in_spin.setFixedWidth(90)
        self._fade_in_spin.setToolTip(_fi_tt)
        row_in.addWidget(self._fade_in_spin)
        row_in.addStretch()
        v.addLayout(row_in)

        # Fade out
        _fo_tt = (
            "O áudio diminui gradualmente até o silêncio no final.\n"
            "Evita cortes bruscos ao término do sermão."
        )
        row_out = QHBoxLayout()
        self._fade_out_check = QCheckBox("Fade out")
        self._fade_out_check.setChecked(audio_cfg.fade_out_enabled)
        self._fade_out_check.setToolTip(_fo_tt)
        row_out.addWidget(self._fade_out_check)
        row_out.addSpacing(8)
        dur_out_lbl = QLabel("Duração:")
        dur_out_lbl.setToolTip("Tempo da transição em segundos.")
        row_out.addWidget(dur_out_lbl)
        self._fade_out_spin = QDoubleSpinBox()
        self._fade_out_spin.setRange(0.0, 10.0)
        self._fade_out_spin.setSingleStep(0.5)
        self._fade_out_spin.setDecimals(1)
        self._fade_out_spin.setSuffix(" s")
        self._fade_out_spin.setValue(float(audio_cfg.fade_out_secs))
        self._fade_out_spin.setFixedWidth(90)
        self._fade_out_spin.setToolTip(_fo_tt)
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
        self._eq_check.setToolTip(
            "Equalização ajusta o tom do áudio em diferentes faixas de frequência.\n"
            "O preset 'Voz Masculina' foi calibrado para pregações:\n"
            "reduz graves que embolam a voz e realça médios-agudos para maior clareza."
        )
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

        _eq_freq_tips = {
            80:   "80 Hz — Graves profundos\nReduz ronco de microfone, ruído de ventilação "
                  "e 'bumps' de baixa frequência.\nPregação: leve corte melhora clareza.",
            250:  "250 Hz — Graves médios\nExcesso deixa a voz 'embolada' ou 'abafada'.\n"
                  "Corte suave aqui abre espaço para a voz respirar.",
            1000: "1 kHz — Médios\nFrequência central da fala. Pequenos ajustes têm grande impacto.\n"
                  "Corte excessivo deixa a voz 'vazia'; boost demais torna agressiva.",
            4000: "4 kHz — Médios-agudos (presença)\nAumenta a inteligibilidade e 'projeção' da voz.\n"
                  "Boost leve aqui faz o pregador 'chegar' melhor ao ouvinte.",
            8000: "8 kHz — Agudos (brilho/ar)\nAdiciona 'ar' e abertura ao som.\n"
                  "Exagero causa sibilo (sibilância) em consoantes 's' e 'ch'.",
        }

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

            _tip = _eq_freq_tips.get(freq, "")
            if _tip:
                slider.setToolTip(_tip)
                freq_lbl.setToolTip(_tip)
                value_lbl.setToolTip(_tip)

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
        btn_restore.setToolTip(
            "Redefine os 5 sliders para o preset otimizado para voz masculina em pregação:\n"
            "corte em 80 Hz e 250 Hz, boost leve em 4 kHz."
        )
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
        self._noise_check.setToolTip(
            "Remove ruídos de fundo constantes: ar-condicionado, ventilador,\n"
            "chiado de microfone ou zumbido elétrico.\n"
            "Não é eficaz contra ruídos intermitentes (tosses, vozes, etc.)."
        )
        v.addWidget(self._noise_check)

        _intensity_tips = {
            "baixa": (
                "Baixa — redução discreta.\n"
                "Ideal para gravações com pouco ruído de fundo.\n"
                "Preserva mais naturalidade na voz."
            ),
            "media": (
                "Média — equilíbrio entre limpeza e naturalidade.\n"
                "Boa para a maioria das situações em igrejas."
            ),
            "alta": (
                "Alta — redução intensa.\n"
                "Use somente quando o ruído for muito forte.\n"
                "Pode causar efeito 'robótico' ou 'metalizado' na voz."
            ),
        }

        intensity_row = QHBoxLayout()
        intensity_lbl = QLabel("Intensidade:")
        intensity_lbl.setToolTip("Força da redução de ruído aplicada.")
        intensity_row.addWidget(intensity_lbl)
        intensity_row.addSpacing(8)

        self._noise_intensity_group = QButtonGroup(self)
        self._noise_intensity_radios = {}
        for i, label in enumerate(("baixa", "media", "alta")):
            rb = QRadioButton(label.capitalize())
            rb.setToolTip(_intensity_tips[label])
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
        self._norm_check.setToolTip(
            "Padroniza o volume do episódio para que todos os cultos fiquem\n"
            "no mesmo nível sonoro (loudnorm EBU R128).\n"
            "Útil quando alguns cultos foram gravados mais alto ou mais baixo."
        )
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
        self._norm_slider.setToolTip(
            "Define o alvo de loudness integrado (LUFS — Loudness Units Full Scale).\n"
            "−16 LUFS: padrão para podcasts e streaming (Spotify, YouTube).\n"
            "−24 LUFS: mais quieto — adequado se ouvido com fone em ambiente silencioso.\n"
            "−10 LUFS: mais alto — bom para quem ouve em carro ou ambiente barulhento.\n"
            "Valores próximos de 0 podem causar distorção (clipping)."
        )
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
            bg_music_path             = self._bg_music_path or None,
            bg_music_enabled          = bool(self._bg_music_check.isChecked()),
            bg_music_volume           = self._bg_music_vol_slider.value() / 100.0,
            bg_music_delay            = float(self._bg_music_delay_spin.value()),
            bg_music_fade_in          = float(self._bg_music_fade_in_spin.value()),
            bg_music_fade_out         = float(self._bg_music_fade_out_spin.value()),
            bg_music_loop             = bool(self._bg_music_loop_check.isChecked()),
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
# Spotify for Podcasters — WebView publishing
# ---------------------------------------------------------------------------

# JavaScript injetado na página do Spotify for Podcasters após o carregamento.
# Preenche título e descrição usando as variáveis definidas por
# `_SpotifyPublishWindow._build_setup_js`.
#
# Por que um observador em vez de algumas tentativas: o wizard é uma SPA. Sair de
# "Upload" para "Details" NÃO recarrega a página, então `loadFinished` não
# dispara de novo — e os campos de título/descrição só existem no segundo passo.
# A versão anterior tentava 10 vezes em 6 s, ainda na tela de Upload, desistia, e
# nunca via os campos aparecerem (relato de campo: arquivo entrou, texto não).
#
# Regras de convivência com o usuário:
#   - cada campo é preenchido UMA vez e só se estiver vazio (nunca sobrescreve
#     o que ele digitou);
#   - o observador se desliga sozinho ao concluir ou após o prazo;
#   - tudo é registrado no console, que o app grava no log (linhas `js:`).
_SPOTIFY_FILL_JS = r"""
(function () {
    if (window.__ipmFiller) { window.__ipmFiller.tenta('reinjecao'); return; }

    var PRAZO_MS  = 5 * 60 * 1000;   // desiste depois disso
    var DEBOUNCE  = 300;
    var inicio    = Date.now();
    var feito     = { titulo: false, descricao: false };
    var observer  = null, timer = null, pendente = null;

    function log(msg) { try { console.log('[IPMadalena] ' + msg); } catch (e) {} }

    function visivel(el) {
        if (!el || el.disabled || el.readOnly) { return false; }
        if (el.offsetParent === null) { return false; }
        var r = el.getBoundingClientRect();
        return r.width > 4 && r.height > 4;
    }

    function vazio(el) {
        var v;
        if (el.value !== undefined && el.value !== null) { v = el.value; }
        else { v = el.innerText || el.textContent || ''; }
        // Editores costumam deixar <br>, espaço fino ou caractere de largura
        // zero no campo "vazio" — nada disso conta como conteúdo do usuário.
        return String(v).replace(/[\s​-‍﻿]/g, '') === '';
    }

    // Busca que também entra em shadow DOM e iframes de mesma origem. O caminho
    // caro só roda quando a busca simples não achou nada.
    function coleta(raiz, seletor, saida) {
        try {
            var achados = raiz.querySelectorAll(seletor);
            for (var i = 0; i < achados.length; i++) { saida.push(achados[i]); }
            var todos = raiz.querySelectorAll('*');
            for (var j = 0; j < todos.length; j++) {
                if (todos[j].shadowRoot) { coleta(todos[j].shadowRoot, seletor, saida); }
                if (todos[j].tagName === 'IFRAME') {
                    try {
                        var doc = todos[j].contentDocument;
                        if (doc) { coleta(doc, seletor, saida); }
                    } catch (e) { /* iframe de outra origem: inacessível */ }
                }
            }
        } catch (e) {}
        return saida;
    }

    function acha(seletor) {
        var simples = [];
        try {
            simples = Array.prototype.slice.call(document.querySelectorAll(seletor));
        } catch (e) {}
        return simples.length ? simples : coleta(document, seletor, []);
    }

    // Força o React a reconhecer a mudança (ele ignora atribuição direta a .value)
    function setNativo(el, valor) {
        var proto = (el.tagName === 'TEXTAREA')
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
        var desc = Object.getOwnPropertyDescriptor(proto, 'value');
        if (desc && desc.set) { desc.set.call(el, valor); } else { el.value = valor; }
        el.dispatchEvent(new Event('input',  { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // Editor rico (contenteditable): execCommand gera os eventos que editores
    // como Draft.js/ProseMirror esperam; atribuir textContent sozinho não basta.
    function setRico(el, texto) {
        el.focus();
        var ok = false;
        try { ok = document.execCommand('insertText', false, texto); } catch (e) { ok = false; }
        if (!ok || vazio(el)) {
            el.textContent = texto;
            try { el.dispatchEvent(new InputEvent('input', { bubbles: true })); }
            catch (e) { el.dispatchEvent(new Event('input', { bubbles: true })); }
        }
    }

    var RUIDO = /search|busca|pesquis|filtro|filter/i;
    var TITULO = /name|nome|title|t[ií]tulo/i;

    function achaTitulo() {
        var todos = acha('input'), candidatos = [];
        for (var i = 0; i < todos.length; i++) {
            var el = todos[i], tipo = (el.type || 'text').toLowerCase();
            if (tipo !== 'text') { continue; }
            if (!visivel(el) || !vazio(el)) { continue; }
            var dica = (el.placeholder || '') + ' ' + (el.getAttribute('aria-label') || '') +
                       ' ' + (el.name || '') + ' ' + (el.id || '') +
                       ' ' + (el.getAttribute('role') || '');
            if (RUIDO.test(dica)) { continue; }
            if (TITULO.test(dica)) { return el; }
            candidatos.push(el);
        }
        // Sem pista no atributo, só arrisca quando não há ambiguidade
        return candidatos.length === 1 ? candidatos[0] : null;
    }

    function achaDescricao() {
        var tas = acha('textarea');
        for (var i = 0; i < tas.length; i++) {
            if (visivel(tas[i]) && vazio(tas[i])) { return { el: tas[i], rico: false }; }
        }
        // `[contenteditable]` sem exigir ="true": o atributo aceita valor vazio
        // e pode ser herdado — `isContentEditable` é quem responde de verdade.
        var ces = acha('[contenteditable]');
        for (var j = 0; j < ces.length; j++) {
            if (ces[j].isContentEditable && visivel(ces[j]) && vazio(ces[j])) {
                return { el: ces[j], rico: true };
            }
        }
        return null;
    }

    // Quando não achamos o campo, o log precisa dizer POR QUÊ — senão a
    // investigação vira adivinhação a cada tentativa do usuário.
    var diagnosticado = false;
    function diagnostica() {
        if (diagnosticado) { return; }
        diagnosticado = true;
        var tas = acha('textarea'), ces = acha('[contenteditable]');
        var partes = ['descricao nao encontrada. textarea=' + tas.length +
                      ' contenteditable=' + ces.length];
        function descreve(el, i) {
            return '#' + i + '{visivel=' + visivel(el) + ' vazio=' + vazio(el) +
                   ' editavel=' + (el.isContentEditable === true) +
                   ' classe=' + String(el.className || '').slice(0, 40) + '}';
        }
        for (var i = 0; i < Math.min(tas.length, 3); i++) { partes.push('ta' + descreve(tas[i], i)); }
        for (var j = 0; j < Math.min(ces.length, 3); j++) { partes.push('ce' + descreve(ces[j], j)); }
        log(partes.join(' '));
    }

    function para(motivo) {
        if (observer) { observer.disconnect(); observer = null; }
        if (timer) { clearInterval(timer); timer = null; }
        log('preenchimento encerrado: ' + motivo);
    }

    function tenta(origem) {
        if (feito.titulo && feito.descricao) { return true; }
        if (Date.now() - inicio > PRAZO_MS) {
            para('prazo esgotado (titulo=' + feito.titulo + ' descricao=' + feito.descricao + ')');
            return true;
        }
        if (!feito.titulo && window._spotifyTitle) {
            var t = achaTitulo();
            if (t) {
                setNativo(t, window._spotifyTitle);
                feito.titulo = true;
                log('titulo preenchido [' + origem + ']');
            }
        }
        if (!feito.descricao && window._spotifyDescription) {
            var d = achaDescricao();
            if (d) {
                if (d.rico) { setRico(d.el, window._spotifyDescription); }
                else { setNativo(d.el, window._spotifyDescription); }
                feito.descricao = true;
                log('descricao preenchida [' + origem + (d.rico ? ', editor rico' : '') + ']');
            } else if (feito.titulo &&
                       Date.now() - inicio > (window.__ipmDiagnosticoMs || 6000)) {
                // Título já entrou (logo a tela do episódio está aberta) e a
                // descrição não: relata o que existe na página.
                diagnostica();
            }
        }
        if (feito.titulo && feito.descricao) { para('tudo preenchido'); return true; }
        return false;
    }

    function agenda() {
        if (pendente) { return; }
        pendente = setTimeout(function () { pendente = null; tenta('dom'); }, DEBOUNCE);
    }

    window.__ipmFiller = { tenta: tenta, para: para };

    if (!tenta('inicial')) {
        // Observador: pega os campos surgindo na troca de passo do wizard.
        observer = new MutationObserver(agenda);
        observer.observe(document.documentElement, { childList: true, subtree: true });
        // Rede de segurança para conteúdo que não passa por mutação observável.
        timer = setInterval(function () { tenta('timer'); }, 1000);
        log('aguardando os campos do episodio aparecerem');
    }
})();
"""


#: Altura da barra de ferramentas das janelas do Spotify.
_SPOTIFY_BAR_H = 40

# Formatos que o seletor de arquivos pode pedir. O `accept` de um <input> pode
# vir como tipo MIME (`audio/*`) OU como lista de extensões (`.mp3,.m4a,...`) —
# e o QtWebEngine repassa exatamente o que está no HTML, sem normalizar.
# Medido: o Qt entrega `['.mp3', '.m4a', '.wav', '.mpg', '.mp4', '.mov']` para o
# formulário do Spotify, que anuncia justamente esses formatos.
_SP_EXT_AUDIO = (
    ".mp3", ".m4a", ".wav", ".mpg", ".mp4", ".mov",
    ".aac", ".flac", ".ogg", ".oga", ".m4v", ".wma",
)
_SP_EXT_IMAGEM = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")

_SP_PEDE_AUDIO = "audio"
_SP_PEDE_IMAGEM = "imagem"
_SP_PEDE_INDEFINIDO = "indefinido"


def _spotify_tipo_pedido(accepted) -> str:
    """
    Diz o que o formulário está pedindo a partir da lista de tipos aceitos.

    Retorna ``_SP_PEDE_IMAGEM``, ``_SP_PEDE_AUDIO`` ou ``_SP_PEDE_INDEFINIDO``
    (lista vazia ou irreconhecível — o `accept` é opcional no HTML).

    A imagem é testada primeiro: o passo da capa costuma aceitar só imagem,
    enquanto o do episódio aceita áudio E vídeo.
    """
    itens = [str(m).strip().lower() for m in (accepted or []) if str(m).strip()]
    if not itens:
        return _SP_PEDE_INDEFINIDO

    def casa(item, familia, extensoes):
        return item.startswith(familia + "/") or item.endswith(extensoes)

    if any(casa(m, "image", _SP_EXT_IMAGEM) for m in itens):
        return _SP_PEDE_IMAGEM
    if any(
        casa(m, "audio", _SP_EXT_AUDIO) or m.startswith("video/")
        for m in itens
    ):
        return _SP_PEDE_AUDIO
    return _SP_PEDE_INDEFINIDO


def _spotify_top_bar(esquerda: list, direita: list) -> QWidget:
    """
    Monta a barra de ferramentas das janelas do Spotify, com altura FIXA.

    Por que um widget de altura fixa em vez de só um QHBoxLayout: num
    QVBoxLayout, a altura máxima de uma linha aninhada depende dos itens dela —
    e, medido, o resultado muda conforme a ORDEM deles. Com o botão (altura
    fixa) à esquerda e o rótulo (altura flexível) à direita, a barra ficava sem
    limite e engolia 503 px de uma janela de 1000 px, empurrando a página para
    baixo; com a ordem invertida, ficava nos 37 px esperados. Fixar a altura
    aqui elimina essa dependência de ordem — e o chamador ainda dá stretch 1 ao
    WebView, para que a sobra vá toda para a página.
    """
    barra = QWidget()
    barra.setFixedHeight(_SPOTIFY_BAR_H)
    barra.setStyleSheet(
        f"background: {P.D_SIDEBAR}; border-bottom: 1px solid {P.D_BORDER};"
    )
    lay = QHBoxLayout(barra)
    lay.setContentsMargins(8, 0, 12, 0)
    lay.setSpacing(8)
    for w in esquerda:
        lay.addWidget(w)
    lay.addStretch()
    for w in direita:
        lay.addWidget(w)
    return barra


class _SpotifyPage:
    """
    Subclasse de QWebEnginePage que intercepta chooseFiles para pré-selecionar
    o arquivo de áudio ou de capa sem que o usuário precise navegar pelo explorer.

    A instância recebe os paths via atributos ``_audio_path`` e ``_cover_image_path``
    ANTES de qualquer chamada do browser ao seletor de arquivos.
    """

    # Criada como mixin para evitar importação circular de QWebEnginePage no
    # nível do módulo (QWebEngineWidgets exige QApplication criado antes).
    # O construtor real é feito em _SpotifyPublishWindow._make_page().

    @staticmethod
    def _make_page(parent_view, audio_path: str = "", cover_path: str = "", profile=None):
        """
        Cria a página do WebView.

        ``profile`` é o perfil persistente da sessão do Spotify. Sem ele a página
        cai no perfil padrão do Qt, que é off-the-record — e o login se perde ao
        fechar a janela.
        """
        from PyQt6.QtWebEngineCore import QWebEnginePage

        class _Page(QWebEnginePage):
            def __init__(self, view):
                if profile is not None:
                    super().__init__(profile, view)
                else:
                    super().__init__(view)
                self._audio_path = audio_path
                self._cover_image_path = cover_path

            def javaScriptConsoleMessage(self, level, message, line, source):
                """
                Leva as mensagens do injetor para o log do app.

                Não dá para confiar no encaminhamento padrão do Qt: medido, ele
                não imprimiu nem `console.log` nem `console.error` — e foi por
                isso que um relato de campo chegou sem nenhuma linha
                `[IPMadalena]`, apesar de o script ter rodado (o título tinha
                sido preenchido). O resto das mensagens da página segue o
                caminho normal.
                """
                if message and "[IPMadalena]" in message:
                    _file_log(f"Spotify: {message.replace('[IPMadalena] ', '')}")
                    return
                super().javaScriptConsoleMessage(level, message, line, source)

            def chooseFiles(self, mode, old_files, accepted_mimetypes):
                """
                Entrega o arquivo certo no lugar do seletor do Windows.

                Chamado quando o usuário clica em "Select a file" na página —
                não há como preencher o campo antes disso (o navegador só
                permite escolher arquivo a partir de um gesto do usuário).
                """
                tipo = _spotify_tipo_pedido(accepted_mimetypes)
                capa  = self._cover_image_path
                audio = self._audio_path

                if tipo == _SP_PEDE_IMAGEM and capa and os.path.isfile(capa):
                    _file_log(f"Spotify: capa entregue ao formulário — {capa}")
                    return [capa]
                # 'indefinido' cai no áudio: é o passo obrigatório do wizard, e
                # a capa é opcional (o usuário escolhe manualmente se preciso).
                if tipo in (_SP_PEDE_AUDIO, _SP_PEDE_INDEFINIDO) and audio \
                        and os.path.isfile(audio):
                    _file_log(f"Spotify: áudio entregue ao formulário — {audio}")
                    return [audio]

                _file_log(
                    f"Spotify: seletor de arquivos aberto sem preenchimento "
                    f"automático (pedido={tipo}, aceitos={list(accepted_mimetypes or [])})."
                )
                return super().chooseFiles(mode, old_files, accepted_mimetypes)

        return _Page(parent_view)


class _SpotifyLoginWindow(QMainWindow):
    """
    Janela de login no Spotify, usando o perfil persistente da sessão.

    Abre a tela de credenciais (``login_url``) e acompanha para onde a navegação
    vai. A área autenticada do Creators **não** serve de entrada: deslogado, o
    roteador dela trava a página carregando (ver o docstring de
    ``infrastructure/spotify/session.py``).

    Por que a detecção é por TRANSIÇÃO
    ----------------------------------
    "Estar numa URL interna do Creators" não prova sessão: com o banner de
    consentimento de cookies na tela, a página fica parada nessa URL
    indefinidamente (medido ao vivo, 20 s em ``/pod/dashboard``). Então o
    positivo só é aceito depois de a tela de credenciais ter aparecido e a
    página sair dela — a transição ``logged_out → logged_in``, que nenhuma
    página travada consegue produzir.

    Para quem já estava logado (nunca vê a tela de credenciais) existe o botão
    "Concluí o login". Se ele for clicado sem login de verdade, o flag fica
    errado até a próxima publicação, quando a janela do wizard recebe a tela de
    login e corrige — o erro não persiste.

    Fecha sozinha ao confirmar o login e chama ``on_finish(logado: bool)``.
    """

    #: Silêncio de navegação que caracteriza a página "assentada". Reiniciado a
    #: cada carregamento, então uma cadeia de redirecionamentos só é avaliada
    #: quando para.
    _ASSENTAR_MS = 2500

    #: Espera antes de fechar após detectar o login — deixa o Spotify concluir
    #: os redirecionamentos do OAuth e gravar os cookies antes da janela sumir.
    _FECHAR_APOS_MS = 1200

    def __init__(self, session, on_finish=None, parent=None):
        super().__init__(parent)
        self._session   = session
        self._on_finish = on_finish
        self._logado    = False
        self._notificou = False
        # Marca se a tela de credenciais já apareceu — é o que autoriza aceitar
        # o veredito positivo depois.
        self._viu_login = False

        # Timer reiniciável: cada loadFinished adia a avaliação, então uma
        # cadeia de redirecionamentos só é julgada quando para.
        self._assentar_timer = QTimer(self)
        self._assentar_timer.setSingleShot(True)
        self._assentar_timer.timeout.connect(self._on_settled)

        self.setWindowTitle("Entrar no Spotify")
        self.resize(1000, 760)

        from PyQt6.QtWebEngineWidgets import QWebEngineView
        self._view = QWebEngineView()
        self._view.setPage(
            _SpotifyPage._make_page(self._view, profile=session.profile())
        )
        self._view.loadFinished.connect(self._on_load_finished)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        # Sem espaçamento: senão sobra uma faixa escura entre a barra e a página
        layout.setSpacing(0)

        self._hint_lbl = QLabel(
            "Entre com a conta que administra o podcast. "
            "A janela fecha sozinha quando o login for concluído."
        )
        self._hint_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        self._confirm_btn = QPushButton("Concluí o login")
        self._confirm_btn.setToolTip(
            "Use se a janela não fechar sozinha depois de você entrar"
        )
        self._confirm_btn.clicked.connect(self._confirmar_manual)
        layout.addWidget(_spotify_top_bar([self._hint_lbl], [self._confirm_btn]))
        # stretch 1: toda a sobra vertical vai para a página, não para a barra
        layout.addWidget(self._view, 1)

        from PyQt6.QtCore import QUrl
        self._view.load(QUrl(session.login_url()))

    def _on_load_finished(self, ok: bool):
        """
        Adia a avaliação: só decide quando a navegação parar.

        Não dá para classificar aqui. O desvio do Creators para o login é feito
        pelo próprio site, não por um 302 — então o primeiro ``loadFinished``
        chega com a URL interna ainda no lugar, e o ``urlChanged`` é pior ainda
        (traz a URL só pedida). Medido ao vivo: deslogado, os dois sinais
        entregam ``logged_in`` antes de o Spotify mandar para o login.
        """
        if not ok:
            return
        self._assentar_timer.start(self._ASSENTAR_MS)

    def _on_settled(self):
        """
        Julga a página assentada.

        Tela de credenciais → registra que ela apareceu (e corrige o flag, que
        pode estar ligado de uma sessão expirada). Página interna DEPOIS disso →
        login concluído.

        Usa o veredito da URL, nunca ``is_logged_in()``: o flag pode estar ligado
        de antes e a janela fecharia ainda na tela de credenciais.
        """
        from domain.ports import SPOTIFY_LOGGED_IN, SPOTIFY_LOGGED_OUT

        veredito = self._session.classify(self._view.url().toString())

        if veredito == SPOTIFY_LOGGED_OUT:
            self._viu_login = True
            self._session.mark_logged_in(False)
            return

        if veredito == SPOTIFY_LOGGED_IN and self._viu_login:
            self._concluir()

    def _confirmar_manual(self):
        """
        Botão "Concluí o login" — saída para quem já estava logado.

        Sem a transição observada não há como provar a sessão daqui, então
        confiamos no usuário; só barramos o caso claramente errado (ainda na
        tela de credenciais).
        """
        from domain.ports import SPOTIFY_LOGGED_OUT

        if self._session.classify(self._view.url().toString()) == SPOTIFY_LOGGED_OUT:
            self._hint_lbl.setText(
                "Ainda na tela de login — entre na sua conta para continuar."
            )
            return
        self._concluir()

    def _concluir(self):
        """Registra o login, avisa na tela e fecha a janela."""
        if self._logado:
            return
        self._logado = True
        self._session.mark_logged_in(True)
        self._hint_lbl.setText("Conectado! Fechando...")
        self._confirm_btn.setEnabled(False)
        QTimer.singleShot(self._FECHAR_APOS_MS, self.close)

    def closeEvent(self, event):
        self._assentar_timer.stop()
        self._notificar()
        super().closeEvent(event)

    def _notificar(self):
        """Avisa o App uma única vez (o closeEvent pode disparar mais de uma)."""
        if self._notificou:
            return
        self._notificou = True
        if callable(self._on_finish):
            self._on_finish(self._logado)


class _SpotifyPublishWindow(QMainWindow):
    """
    Janela secundária com um QWebEngineView apontando para o formulário de novo
    episódio no Spotify for Podcasters.

    Após o carregamento, injeta _SPOTIFY_FILL_JS com as variáveis globais
    ``_spotifyTitle`` e ``_spotifyDescription`` preenchidas.
    """

    def __init__(
        self,
        show_id: str,
        episode_title: str,
        episode_description: str,
        audio_path: str = "",
        cover_image_path: str = "",
        parent=None,
        session=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Publicar no Spotify for Podcasters")
        self.resize(1100, 780)

        self._show_id = show_id
        self._episode_title = episode_title
        self._episode_description = episode_description
        self._audio_path = audio_path
        self._cover_image_path = cover_image_path
        self._session = session

        from PyQt6.QtWebEngineWidgets import QWebEngineView
        self._view = QWebEngineView()
        page = _SpotifyPage._make_page(
            self._view,
            audio_path = audio_path,
            cover_path = cover_image_path,
            # Mesmo perfil da janela de login — é o que evita cair na tela de
            # credenciais aqui.
            profile    = session.profile() if session is not None else None,
        )
        self._view.setPage(page)
        # A classificação da sessão acontece em _on_load_finished, com a URL
        # final. `urlChanged` traria a URL pedida (o wizard, sempre "logado")
        # antes de o Spotify decidir se redireciona para o login.
        self._view.loadFinished.connect(self._on_load_finished)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        # Sem espaçamento: senão sobra uma faixa escura entre a barra e a página
        layout.setSpacing(0)

        # Barra de ferramentas superior
        back_btn = QPushButton("← Voltar")
        back_btn.clicked.connect(self._view.back)
        hint_lbl = QLabel("Revise e publique o episódio no Spotify for Podcasters")
        hint_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 12px;")
        layout.addWidget(_spotify_top_bar([back_btn], [hint_lbl]))
        # stretch 1: toda a sobra vertical vai para a página, não para a barra
        layout.addWidget(self._view, 1)

        if session is not None:
            url = session.wizard_url(show_id)
        else:
            url = f"https://creators.spotify.com/pod/show/{show_id}/episode/wizard"
        from PyQt6.QtCore import QUrl
        self._view.load(QUrl(url))

    def _on_load_finished(self, ok: bool):
        if not ok:
            return
        # Não preenche quando o Spotify devolveu a tela de credenciais: o
        # primeiro input visível ali é o campo de e-mail, e o título do
        # episódio acabaria digitado no login.
        #
        # Usa `classify` (que não persiste) e só corrige o flag na direção
        # LOGGED_OUT: essa é conclusiva — se o Spotify pediu credenciais, a
        # sessão acabou. O contrário não vale aqui, porque este callback também
        # roda antes de um eventual desvio para o login.
        if self._session is not None:
            from domain.ports import SPOTIFY_LOGGED_OUT

            if self._session.classify(self._view.url().toString()) == SPOTIFY_LOGGED_OUT:
                self._session.mark_logged_in(False)
                return
        # Define variáveis JS antes de injetar o script de preenchimento
        self._view.page().runJavaScript(
            self._build_setup_js(self._episode_title, self._episode_description)
        )
        self._view.page().runJavaScript(_SPOTIFY_FILL_JS)

    @staticmethod
    def _build_setup_js(title: str, description: str) -> str:
        """
        Monta o JS que declara título e descrição para o script de preenchimento.

        Usa `json.dumps` para gerar os literais. O escape manual anterior tratava
        só `\\` e `'` — e a descrição do YouTube é multi-linha (as reais têm ~25
        linhas). Uma quebra de linha crua dentro de `'...'` torna o script
        inválido, ele falha inteiro e silenciosamente, e aí NEM o título é
        preenchido (o preenchedor só age se a variável existir). Verificado numa
        página real: com descrição multi-linha, as duas variáveis chegavam como
        `undefined`.

        `json.dumps` escapa aspas, barras e quebras de linha, e com o
        `ensure_ascii` padrão converte todo caractere não-ASCII em `\\uXXXX` —
        o que também neutraliza U+2028/U+2029, válidos em JSON mas quebrados
        como literal de string em JS antigo.
        """
        import json as _json

        return (
            f"window._spotifyTitle = {_json.dumps(title or '')};\n"
            f"window._spotifyDescription = {_json.dumps(description or '')};\n"
        )


class _SpotifyPrePublishDialog(QDialog):
    """
    Diálogo modal que exibe os metadados do episódio antes de abrir o WebView.

    O usuário pode editar título, descrição e tags. Ao confirmar, o WebView
    abre na URL do novo episódio com os campos pré-preenchidos.

    A descrição é buscada de forma assíncrona via yt-dlp logo após a abertura
    do diálogo (o campo inicia vazio e é preenchido quando a busca conclui).
    """

    def __init__(
        self,
        show_id: str,
        video_id: str,
        title: str,
        description: str,
        date_str: str,
        tags: str,
        audio_path: str,
        cover_image_path: str = "",
        parent=None,
        session=None,
    ):
        super().__init__(parent)
        self._show_id          = show_id
        self._video_id         = video_id
        self._audio_path       = audio_path
        self._cover_image_path = cover_image_path
        self._session          = session

        self.setWindowTitle("Publicar no Spotify for Podcasters")
        self.setMinimumWidth(500)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        # Título
        lbl_title = QLabel("Título do episódio:")
        lbl_title.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_title)
        self._title_edit = QLineEdit(title)
        layout.addWidget(self._title_edit)

        # Descrição — pré-preenchida com o que foi buscado no worker.
        # Se estiver vazia (falha de rede), mantém placeholder para o usuário digitar.
        lbl_desc = QLabel("Descrição:")
        lbl_desc.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_desc)
        self._desc_edit = QPlainTextEdit()
        if description:
            self._desc_edit.setPlainText(description)
        else:
            self._desc_edit.setPlaceholderText(
                "Não foi possível buscar a descrição do YouTube. Digite aqui."
            )
        self._desc_edit.setMinimumHeight(120)
        layout.addWidget(self._desc_edit)

        # Tags
        lbl_tags = QLabel("Tags (separadas por vírgula):")
        lbl_tags.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_tags)
        self._tags_edit = QLineEdit(tags)
        self._tags_edit.setPlaceholderText("Ex: pregação, evangelho")
        layout.addWidget(self._tags_edit)

        # Capa do episódio + arquivo de áudio (row informativa)
        info_row = QHBoxLayout()
        info_row.setSpacing(12)

        if cover_image_path and os.path.isfile(cover_image_path):
            from PyQt6.QtGui import QPixmap
            cov_pix = QPixmap(cover_image_path).scaled(
                80, 80,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            cov_lbl = QLabel()
            cov_lbl.setPixmap(cov_pix.copy(0, 0, 80, 80))
            cov_lbl.setFixedSize(80, 80)
            info_row.addWidget(cov_lbl)

        if audio_path and os.path.isfile(audio_path):
            af_lbl = QLabel(f"🎵  {os.path.basename(audio_path)}")
            af_lbl.setStyleSheet(f"color: {P.HINT}; font-size: 11px;")
            info_row.addWidget(af_lbl)
        else:
            no_audio = QLabel("⚠  Arquivo de áudio não encontrado em downloads/")
            no_audio.setStyleSheet(f"color: {P.WARN_LABEL}; font-size: 11px;")
            info_row.addWidget(no_audio)

        info_row.addStretch()
        layout.addLayout(info_row)

        # Botões
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Agora não")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        self._publish_btn = QPushButton("Abrir Spotify →")
        self._publish_btn.setDefault(True)
        self._publish_btn.clicked.connect(self._on_publish)
        btn_row.addWidget(self._publish_btn)
        layout.addLayout(btn_row)

    def _on_publish(self):
        title = self._title_edit.text().strip()
        if not title:
            QMessageBox.warning(self, "Título obrigatório", "Informe um título para o episódio.")
            return
        desc  = self._desc_edit.toPlainText().strip()
        # Fecha o diálogo e abre a janela do Spotify.
        # Armazena a janela no App pai para evitar garbage collection prematura.
        self.accept()
        parent_app = self.parent()
        win = _SpotifyPublishWindow(
            show_id             = self._show_id,
            episode_title       = title,
            episode_description = desc,
            audio_path          = self._audio_path,
            cover_image_path    = self._cover_image_path,
            parent              = parent_app,
            # A sessão vem do App quando o diálogo não a recebeu explicitamente
            # — é ela que carrega o perfil já logado.
            session             = self._session
                                  or getattr(parent_app, "_spotify_session", None),
        )
        # Mantém referência viva no App para evitar que o GC destrua a janela
        # imediatamente após este método retornar.
        if parent_app is not None:
            parent_app._spotify_window = win
        win.show()


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Deve ser chamado ANTES de criar QApplication para que QWebEngineView
    # funcione corretamente no processo principal (Spotify WebView).
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

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
        _q.setPalette(_build_palette(dark=True))
        _q.setStyleSheet(_QSS_DARK)
        win = App()
        win.show()
        sys.exit(_q.exec())
