"""
Assistente de configuração inicial — IPMadalena Cultos para o Drive.
Executado automaticamente na primeira execução (antes da autorização Google).
"""

import threading

import customtkinter as ctk

import baixar_audio


class SetupWizard(ctk.CTkToplevel):
    """Wizard modal de configuração inicial em 5 passos."""

    _STEPS = [
        "Boas-vindas",
        "Canal YouTube",
        "Pasta Drive",
        "Autorização",
        "Concluído",
    ]

    def __init__(self, master, on_complete=None):
        super().__init__(master)
        self.title("IPMadalena — Configuração Inicial")
        self.geometry("600x530")
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._on_complete = on_complete
        self._step        = 0
        self._authorized  = baixar_audio.check_auth_status()
        self._fb          = None          # referência ao feedback label do passo atual

        self._build_shell()
        self._show_step(0)

    # -----------------------------------------------------------------------
    # Shell (indicador + conteúdo + navegação)
    # -----------------------------------------------------------------------

    def _build_shell(self):
        # ── Indicador de passos ──
        ind = ctk.CTkFrame(self, fg_color="transparent", height=52)
        ind.pack(fill="x", padx=28, pady=(20, 0))
        ind.pack_propagate(False)

        self._step_dots = []
        self._step_lbls = []
        for name in self._STEPS:
            col = ctk.CTkFrame(ind, fg_color="transparent")
            col.pack(side="left", expand=True, fill="x")
            dot = ctk.CTkLabel(col, text="●", font=ctk.CTkFont(size=11))
            dot.pack()
            lbl = ctk.CTkLabel(col, text=name, font=ctk.CTkFont(size=9))
            lbl.pack()
            self._step_dots.append(dot)
            self._step_lbls.append(lbl)

        ctk.CTkFrame(self, height=1, fg_color=("gray78", "gray28")).pack(
            fill="x", pady=(10, 0)
        )

        # ── Área de conteúdo ──
        self._content = ctk.CTkFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True, padx=36, pady=(22, 0))

        # ── Botões de navegação ──
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.pack(fill="x", padx=36, pady=(6, 22))

        self._back_btn = ctk.CTkButton(
            nav, text="← Voltar", width=110,
            fg_color=("gray75", "gray30"), hover_color=("gray65", "gray25"),
            command=self._go_back,
        )
        self._back_btn.pack(side="left")

        self._next_btn = ctk.CTkButton(
            nav, text="Próximo →", width=150,
            font=ctk.CTkFont(weight="bold"),
            command=self._go_next,
        )
        self._next_btn.pack(side="right")

    # -----------------------------------------------------------------------
    # Navegação
    # -----------------------------------------------------------------------

    def _show_step(self, step):
        self._step = step
        self._fb   = None

        # Atualiza indicador
        last = len(self._STEPS) - 1
        for i, (dot, lbl) in enumerate(zip(self._step_dots, self._step_lbls)):
            if i < step:
                dot.configure(text_color="#2fa84f")
                lbl.configure(text_color="#2fa84f")
            elif i == step:
                dot.configure(text_color="#4a9edd")
                lbl.configure(text_color="white")
            else:
                dot.configure(text_color="gray")
                lbl.configure(text_color="gray")

        # Limpa conteúdo anterior
        for w in self._content.winfo_children():
            w.destroy()

        # Botões
        self._back_btn.configure(state="normal" if 0 < step < last else "disabled")
        self._next_btn.configure(
            text="Começar a usar" if step == last else "Próximo →",
            state="normal",
        )

        [self._s0, self._s1, self._s2, self._s3, self._s4][step]()

    def _go_next(self):
        # Validação e persistência de cada passo
        if self._step == 1:   # canal
            channel = self._channel_entry.get().strip()
            if not channel:
                self._set_fb("Informe a URL do canal.", error=True)
                return
            baixar_audio.save_config(channel_url=channel)

        elif self._step == 2:  # pasta
            folder = self._folder_entry.get().strip()
            if not folder:
                self._set_fb("Informe o ID da pasta.", error=True)
                return
            baixar_audio.save_config(drive_folder_id=folder)

        elif self._step == 3:  # auth
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

    def _section(self, title, subtitle=""):
        ctk.CTkLabel(self._content, text=title,
                     font=ctk.CTkFont(size=18, weight="bold")).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(self._content, text=subtitle,
                         font=ctk.CTkFont(size=12), text_color="gray").pack(anchor="w", pady=(2, 14))

    def _add_fb(self):
        self._fb = ctk.CTkLabel(self._content, text="",
                                font=ctk.CTkFont(size=11), anchor="w")
        self._fb.pack(anchor="w", pady=(10, 0))

    def _set_fb(self, msg, error=False):
        if self._fb:
            self._fb.configure(text=msg,
                               text_color="#e05252" if error else "#2fa84f")

    # -----------------------------------------------------------------------
    # Passos
    # -----------------------------------------------------------------------

    def _s0(self):
        """Boas-vindas."""
        ctk.CTkLabel(self._content, text="Bem-vindo!",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(self._content, text="IPMadalena — Cultos para o Drive",
                     font=ctk.CTkFont(size=13), text_color="gray").pack(anchor="w", pady=(2, 20))
        ctk.CTkLabel(
            self._content,
            wraplength=520, justify="left", font=ctk.CTkFont(size=12),
            text=(
                "Este assistente irá guiá-lo pela configuração inicial do aplicativo.\n"
                "O processo leva cerca de 2 minutos e inclui:\n\n"
                "  • Definição do canal do YouTube a ser monitorado\n"
                "  • Configuração da pasta de destino no Google Drive\n"
                "  • Autorização de acesso ao Google Drive"
            ),
        ).pack(anchor="w")

    def _s1(self):
        """Canal do YouTube."""
        self._section("Canal do YouTube", "URL do canal a ser monitorado")
        cfg = baixar_audio.load_config()

        ctk.CTkLabel(self._content,
                     text="Informe a URL do canal cujos vídeos serão baixados:",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 8))

        self._channel_entry = ctk.CTkEntry(
            self._content, height=36, font=ctk.CTkFont(size=12))
        self._channel_entry.insert(0, cfg["channel_url"])
        self._channel_entry.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(self._content,
                     text="Ex: https://www.youtube.com/@SeuCanal/streams",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")
        self._add_fb()

    def _s2(self):
        """Pasta do Google Drive."""
        self._section("Pasta do Google Drive", "ID da pasta raiz de destino")
        cfg = baixar_audio.load_config()

        ctk.CTkLabel(
            self._content,
            wraplength=520, justify="left", font=ctk.CTkFont(size=12),
            text=(
                "Como encontrar o ID da pasta:\n"
                "  1. Abra o Google Drive no navegador\n"
                "  2. Navegue até a pasta desejada\n"
                "  3. Copie o código que aparece no final da URL"
            ),
        ).pack(anchor="w", pady=(0, 14))

        ctk.CTkLabel(self._content, text="ID da pasta:",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 6))

        self._folder_entry = ctk.CTkEntry(
            self._content, height=36, font=ctk.CTkFont(size=12))
        self._folder_entry.insert(0, cfg["drive_folder_id"])
        self._folder_entry.pack(fill="x")
        self._add_fb()

    def _s3(self):
        """Autorização Google Drive."""
        self._section("Autorização do Google Drive", "Permitir acesso à sua conta Google")
        ctk.CTkLabel(
            self._content,
            wraplength=520, justify="left", font=ctk.CTkFont(size=12),
            text=(
                "Para enviar arquivos ao Google Drive, o aplicativo precisa da sua "
                "autorização.\n\n"
                "Clique em 'Autorizar com Google' — seu navegador será aberto para que "
                "você faça login e aprove o acesso."
            ),
        ).pack(anchor="w", pady=(0, 18))

        if self._authorized:
            ctk.CTkLabel(self._content,
                         text="✓  Google Drive autorizado com sucesso!",
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color="#2fa84f").pack(anchor="w")
        else:
            self._next_btn.configure(state="disabled")
            self._auth_btn = ctk.CTkButton(
                self._content, text="Autorizar com Google", width=210,
                command=self._do_auth,
            )
            self._auth_btn.pack(anchor="w")
            self._auth_lbl = ctk.CTkLabel(
                self._content, text="Clique no botão para abrir o navegador.",
                font=ctk.CTkFont(size=12), text_color="gray",
            )
            self._auth_lbl.pack(anchor="w", pady=(12, 0))

        self._add_fb()

    def _s4(self):
        """Concluído."""
        self._back_btn.configure(state="disabled")
        ctk.CTkLabel(self._content, text="✓  Configuração concluída!",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#2fa84f").pack(anchor="w")
        ctk.CTkLabel(self._content, text="O aplicativo está pronto para uso.",
                     font=ctk.CTkFont(size=13), text_color="gray").pack(anchor="w", pady=(4, 22))
        ctk.CTkLabel(
            self._content,
            wraplength=520, justify="left", font=ctk.CTkFont(size=13),
            text=(
                "Para baixar os áudios dos cultos:\n\n"
                "  1. Informe a data do culto\n"
                "  2. Clique em 'Processar'\n"
                "  3. Selecione os vídeos desejados\n"
                "  4. Aguarde o download e o envio ao Google Drive"
            ),
        ).pack(anchor="w")

    # -----------------------------------------------------------------------
    # Autorização OAuth
    # -----------------------------------------------------------------------

    def _do_auth(self):
        self._auth_btn.configure(state="disabled", text="Aguardando navegador...")
        self._auth_lbl.configure(
            text="Navegador aberto — complete a autorização e retorne aqui.",
            text_color="white",
        )
        threading.Thread(target=self._auth_worker, daemon=True).start()

    def _auth_worker(self):
        try:
            baixar_audio.run_auth()
            self._authorized = True
            self.after(0, lambda: self._show_step(self._step))
        except Exception as e:
            self.after(0, lambda: self._on_auth_error(str(e)))

    def _on_auth_error(self, msg):
        self._auth_btn.configure(state="normal", text="Tentar novamente")
        self._auth_lbl.configure(text=f"Erro: {msg}", text_color="#e05252")

    # -----------------------------------------------------------------------
    # Conclusão
    # -----------------------------------------------------------------------

    def _finish(self):
        self.grab_release()
        self.destroy()
        if callable(self._on_complete):
            self._on_complete()

    def _on_close(self):
        # Se o wizard não foi concluído, encerra o app inteiro
        if self._step < len(self._STEPS) - 1:
            self.master.destroy()
        else:
            self._finish()
