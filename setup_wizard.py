"""
Assistente de configuração inicial — IPMadalena Cultos para o Drive (PyQt6).
Executado automaticamente na primeira execução (antes da autorização Google).
"""

import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

import baixar_audio


class SetupWizard(QDialog):
    """Wizard de configuração inicial em 5 passos (QDialog não-bloqueante)."""

    _STEPS = [
        "Boas-vindas",
        "Canal YouTube",
        "Pasta Drive",
        "Autorização",
        "Concluído",
    ]

    # Sinais para comunicação thread-safe com o worker de autenticação
    _auth_done_sig  = pyqtSignal(bool, str)   # (success, error_msg)

    def __init__(self, parent=None, on_complete=None):
        super().__init__(parent)
        self.setWindowTitle("IPMadalena — Configuração Inicial")
        self.setFixedSize(600, 530)
        # Janela própria; não bloqueia o mainloop
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowTitleHint |
            Qt.WindowType.WindowCloseButtonHint,
        )

        self._on_complete = on_complete
        self._step        = 0
        self._authorized  = baixar_audio.check_auth_status()
        self._finished    = False

        # Referências de widgets do passo atual (populadas em _show_step)
        self._channel_entry : QLineEdit | None = None
        self._folder_entry  : QLineEdit | None = None
        self._auth_btn      : QPushButton | None = None
        self._auth_lbl      : QLabel | None = None
        self._fb_label      : QLabel | None = None

        self._auth_done_sig.connect(self._on_auth_result)

        self._build_shell()
        self._show_step(0)

    # -----------------------------------------------------------------------
    # Shell fixo (indicador + área de conteúdo + navegação)
    # -----------------------------------------------------------------------
    def _build_shell(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Indicador de passos ──
        ind = QWidget()
        ind.setFixedHeight(64)
        ind.setStyleSheet("background: #2b2b2b;")
        il = QHBoxLayout(ind)
        il.setContentsMargins(28, 8, 28, 8)

        self._step_dots: list[QLabel] = []
        self._step_lbls: list[QLabel] = []
        for name in self._STEPS:
            col = QWidget()
            cl  = QVBoxLayout(col)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(2)
            dot = QLabel("●")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel(name)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.addWidget(dot)
            cl.addWidget(lbl)
            il.addWidget(col, stretch=1)
            self._step_dots.append(dot)
            self._step_lbls.append(lbl)

        root.addWidget(ind)

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #444;")
        root.addWidget(sep)

        # ── Área de conteúdo substituível ──
        self._content_area = QWidget()
        self._content_layout = QVBoxLayout(self._content_area)
        self._content_layout.setContentsMargins(36, 22, 36, 10)
        self._content_layout.setSpacing(8)
        root.addWidget(self._content_area, stretch=1)

        # ── Navegação ──
        nav = QWidget()
        nav.setStyleSheet("background: #2b2b2b;")
        nl = QHBoxLayout(nav)
        nl.setContentsMargins(28, 10, 28, 18)

        self._back_btn = QPushButton("← Voltar")
        self._back_btn.setFixedWidth(110)
        self._back_btn.setObjectName("gray_btn")
        self._back_btn.clicked.connect(self._go_back)

        self._next_btn = QPushButton("Próximo →")
        self._next_btn.setFixedWidth(160)
        self._next_btn.setStyleSheet("font-weight: bold; padding: 6px 18px;")
        self._next_btn.clicked.connect(self._go_next)

        nl.addWidget(self._back_btn)
        nl.addStretch()
        nl.addWidget(self._next_btn)
        root.addWidget(nav)

    # -----------------------------------------------------------------------
    # Navegar entre passos
    # -----------------------------------------------------------------------
    def _show_step(self, step: int):
        self._step       = step
        self._fb_label   = None
        self._channel_entry = None
        self._folder_entry  = None
        self._auth_btn   = None
        self._auth_lbl   = None

        last = len(self._STEPS) - 1

        # Atualiza indicador de passos
        for i, (dot, lbl) in enumerate(zip(self._step_dots, self._step_lbls)):
            if i < step:
                dot.setStyleSheet("color: #2fa84f; font-size: 11px;")
                lbl.setStyleSheet("color: #2fa84f; font-size: 9px;")
            elif i == step:
                dot.setStyleSheet("color: #4a9edd; font-size: 11px;")
                lbl.setStyleSheet("color: white; font-size: 9px;")
            else:
                dot.setStyleSheet("color: gray; font-size: 11px;")
                lbl.setStyleSheet("color: gray; font-size: 9px;")

        # Botões
        self._back_btn.setEnabled(0 < step < last)
        self._next_btn.setText("Começar a usar" if step == last else "Próximo →")
        self._next_btn.setEnabled(True)

        # Substitui conteúdo limpando e reconstruindo
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        [self._s0, self._s1, self._s2, self._s3, self._s4][step]()
        self._content_layout.addStretch()

    def _go_next(self):
        if self._step == 1:
            if self._channel_entry:
                channel = self._channel_entry.text().strip()
                if not channel:
                    self._set_fb("Informe a URL do canal.", error=True)
                    return
                baixar_audio.save_config(channel_url=channel)

        elif self._step == 2:
            if self._folder_entry:
                folder = self._folder_entry.text().strip()
                if not folder:
                    self._set_fb("Informe o ID da pasta.", error=True)
                    return
                baixar_audio.save_config(drive_folder_id=folder)

        elif self._step == 3:
            if not self._authorized:
                self._set_fb("Autorize o acesso ao Google Drive antes de continuar.", error=True)
                return

        if self._step == len(self._STEPS) - 1:
            self._finish()
        else:
            self._show_step(self._step + 1)

    def _go_back(self):
        if 0 < self._step < len(self._STEPS) - 1:
            self._show_step(self._step - 1)

    # -----------------------------------------------------------------------
    # Helpers de layout
    # -----------------------------------------------------------------------
    def _section(self, title: str, subtitle: str = ""):
        t = QLabel(title)
        t.setStyleSheet("font-size: 18px; font-weight: bold;")
        self._content_layout.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setStyleSheet("color: gray; font-size: 12px;")
            self._content_layout.addWidget(s)

    def _add_fb(self):
        self._fb_label = QLabel("")
        self._fb_label.setStyleSheet("font-size: 11px;")
        self._content_layout.addWidget(self._fb_label)

    def _set_fb(self, msg: str, error: bool = False):
        if self._fb_label:
            color = "#e05252" if error else "#2fa84f"
            self._fb_label.setStyleSheet(f"font-size: 11px; color: {color};")
            self._fb_label.setText(msg)

    # -----------------------------------------------------------------------
    # Conteúdo de cada passo
    # -----------------------------------------------------------------------
    def _s0(self):
        lbl = QLabel("Bem-vindo!")
        lbl.setStyleSheet("font-size: 22px; font-weight: bold;")
        self._content_layout.addWidget(lbl)

        sub = QLabel("IPMadalena — Cultos para o Drive")
        sub.setStyleSheet("color: gray; font-size: 13px;")
        self._content_layout.addWidget(sub)
        self._content_layout.addSpacing(16)

        body = QLabel(
            "Este assistente irá guiá-lo pela configuração inicial do aplicativo.\n"
            "O processo leva cerca de 2 minutos e inclui:\n\n"
            "  • Definição do canal do YouTube a ser monitorado\n"
            "  • Configuração da pasta de destino no Google Drive\n"
            "  • Autorização de acesso ao Google Drive"
        )
        body.setStyleSheet("font-size: 12px;")
        body.setWordWrap(True)
        self._content_layout.addWidget(body)

    def _s1(self):
        self._section("Canal do YouTube", "URL do canal a ser monitorado")
        cfg = baixar_audio.load_config()

        hint = QLabel("Informe a URL do canal cujos vídeos serão baixados:")
        hint.setStyleSheet("font-size: 12px;")
        self._content_layout.addWidget(hint)

        self._channel_entry = QLineEdit(cfg["channel_url"])
        self._channel_entry.setFixedHeight(36)
        self._content_layout.addWidget(self._channel_entry)

        ex = QLabel("Ex: https://www.youtube.com/@SeuCanal/streams")
        ex.setStyleSheet("color: gray; font-size: 11px;")
        self._content_layout.addWidget(ex)

        self._add_fb()

    def _s2(self):
        self._section("Pasta do Google Drive", "ID da pasta raiz de destino")
        cfg = baixar_audio.load_config()

        body = QLabel(
            "Como encontrar o ID da pasta:\n"
            "  1. Abra o Google Drive no navegador\n"
            "  2. Navegue até a pasta desejada\n"
            "  3. Copie o código que aparece no final da URL"
        )
        body.setStyleSheet("font-size: 12px;")
        body.setWordWrap(True)
        self._content_layout.addWidget(body)
        self._content_layout.addSpacing(10)

        lbl = QLabel("ID da pasta:")
        lbl.setStyleSheet("font-size: 12px;")
        self._content_layout.addWidget(lbl)

        self._folder_entry = QLineEdit(cfg["drive_folder_id"])
        self._folder_entry.setFixedHeight(36)
        self._content_layout.addWidget(self._folder_entry)

        self._add_fb()

    def _s3(self):
        self._section("Autorização do Google Drive", "Permitir acesso à sua conta Google")

        body = QLabel(
            "Para enviar arquivos ao Google Drive, o aplicativo precisa da sua "
            "autorização.\n\n"
            "Clique em 'Autorizar com Google' — seu navegador será aberto para que "
            "você faça login e aprove o acesso."
        )
        body.setStyleSheet("font-size: 12px;")
        body.setWordWrap(True)
        self._content_layout.addWidget(body)
        self._content_layout.addSpacing(14)

        if self._authorized:
            ok = QLabel("✓  Google Drive autorizado com sucesso!")
            ok.setStyleSheet("font-size: 13px; font-weight: bold; color: #2fa84f;")
            self._content_layout.addWidget(ok)
        else:
            self._next_btn.setEnabled(False)
            self._auth_btn = QPushButton("Autorizar com Google")
            self._auth_btn.setFixedWidth(210)
            self._auth_btn.clicked.connect(self._do_auth)
            self._content_layout.addWidget(self._auth_btn)

            self._auth_lbl = QLabel("Clique no botão para abrir o navegador.")
            self._auth_lbl.setStyleSheet("color: gray; font-size: 12px;")
            self._content_layout.addWidget(self._auth_lbl)

        self._add_fb()

    def _s4(self):
        self._back_btn.setEnabled(False)

        ok = QLabel("✓  Configuração concluída!")
        ok.setStyleSheet("font-size: 20px; font-weight: bold; color: #2fa84f;")
        self._content_layout.addWidget(ok)

        sub = QLabel("O aplicativo está pronto para uso.")
        sub.setStyleSheet("color: gray; font-size: 13px;")
        self._content_layout.addWidget(sub)
        self._content_layout.addSpacing(18)

        body = QLabel(
            "Para baixar os áudios dos cultos:\n\n"
            "  1. Informe a data do culto\n"
            "  2. Clique em 'Processar'\n"
            "  3. Selecione os vídeos desejados\n"
            "  4. Aguarde o download e o envio ao Google Drive"
        )
        body.setStyleSheet("font-size: 13px;")
        body.setWordWrap(True)
        self._content_layout.addWidget(body)

    # -----------------------------------------------------------------------
    # Autorização OAuth (thread-safe via sinal)
    # -----------------------------------------------------------------------
    def _do_auth(self):
        if self._auth_btn:
            self._auth_btn.setEnabled(False)
            self._auth_btn.setText("Aguardando navegador...")
        if self._auth_lbl:
            self._auth_lbl.setText(
                "Navegador aberto — complete a autorização e retorne aqui."
            )
            self._auth_lbl.setStyleSheet("color: white; font-size: 12px;")
        threading.Thread(target=self._auth_worker, daemon=True).start()

    def _auth_worker(self):
        try:
            baixar_audio.run_auth()
            self._auth_done_sig.emit(True, "")
        except Exception as e:
            self._auth_done_sig.emit(False, str(e))

    def _on_auth_result(self, success: bool, error_msg: str):
        if success:
            self._authorized = True
            self._show_step(self._step)
        else:
            if self._auth_btn:
                self._auth_btn.setEnabled(True)
                self._auth_btn.setText("Tentar novamente")
            if self._auth_lbl:
                self._auth_lbl.setText(f"Erro: {error_msg}")
                self._auth_lbl.setStyleSheet("color: #e05252; font-size: 12px;")

    # -----------------------------------------------------------------------
    # Conclusão e fechamento
    # -----------------------------------------------------------------------
    def _finish(self):
        self._finished = True
        self.accept()
        if callable(self._on_complete):
            self._on_complete()

    def closeEvent(self, event):
        # Se fechado antes de concluir o wizard → encerra a janela pai (App)
        if not self._finished and self._step < len(self._STEPS) - 1:
            if self.parent() is not None:
                self.parent().close()
        event.accept()
