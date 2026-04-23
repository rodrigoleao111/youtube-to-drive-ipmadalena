# IPMadalena — YouTube to Drive

Automatiza o download do áudio dos cultos do canal [@IPMadalena](https://www.youtube.com/@IPMadalena/streams) no YouTube e o upload para o Google Drive, organizando os arquivos por pasta de mês.

---

## Instalação

Existem duas formas de instalar o app. Escolha a que melhor se encaixa no seu perfil.

### Opção 1 — Instalador Windows (recomendado para usuários finais)

> Não requer Python, nem conhecimento técnico. Inclui yt-dlp e ffmpeg embutidos.

1. Baixe o arquivo `IPMadalena_Setup.exe`
2. Execute o instalador e siga os passos (não requer permissão de administrador)
3. Um atalho **IPMadalena** será criado na área de trabalho
4. Na primeira execução, um **assistente de configuração** irá guiá-lo pelos passos necessários

### Opção 2 — Script de instalação (sem compilar)

> Requer Windows com conexão à internet. Python será instalado automaticamente se necessário.

1. Baixe ou clone o repositório
2. Execute `instalar.bat` com duplo clique
3. O script instala Python, dependências e ffmpeg automaticamente
4. Um atalho é criado na área de trabalho ao final

### Opção 3 — Instalação manual (desenvolvedores)

```bash
pip install yt-dlp google-api-python-client google-auth-oauthlib customtkinter tkcalendar plyer
```

Instale o ffmpeg em `ffmpeg/bin/ffmpeg.exe` e execute:

```bash
python app.py
```

---

## Configuração inicial (primeiro uso)

Na primeira execução, o **assistente de configuração** é aberto automaticamente e guia você por 6 passos:

1. **Boas-vindas** — visão geral do app
2. **Credenciais Google** — selecione o arquivo `client_secret.json` baixado do Google Cloud Console
3. **Canal YouTube** — informe a URL do canal a monitorar
4. **Pasta do Drive** — informe o ID da pasta raiz onde os áudios serão organizados
5. **Autorização Google** — o navegador abre para você aprovar o acesso ao Drive
6. **Conclusão** — tudo pronto para usar

> Para criar as credenciais Google, acesse o [Google Cloud Console](https://console.cloud.google.com/), crie um projeto, ative a API do Google Drive e baixe o arquivo OAuth `client_secret.json`.

Após a configuração, o token é salvo em `credentials/token.pkl` e renovado automaticamente. Se ficar corrompido, é deletado e a autenticação é refeita na próxima execução.

---

## Como usar

### Interface gráfica

```bash
python app.py
```

1. Informe a data do culto (DD/MM/AAAA) ou use o seletor de calendário 📅
2. Clique em **Processar**
3. Selecione os vídeos desejados no popup e clique em **Prosseguir**
4. Acompanhe o progresso pelas barras de **Download**, **Conversão** e **Upload**
5. Uma notificação desktop é exibida ao concluir

### Linha de comando

```bash
python baixar_audio.py DD/MM/AAAA
```

**Exemplo:**
```bash
python baixar_audio.py 19/04/2026
```

---

## Configurações

Clique no ícone ⚙ no canto superior direito para acessar a tela de configurações:

- **Autorização Google Drive** — autorizar ou revogar acesso
- **Canal YouTube** — alterar a URL do canal monitorado
- **Pasta do Drive** — alterar o ID da pasta raiz de destino

---

## O que o app faz automaticamente

1. Verifica conexão com a internet e espaço em disco (≥ 500 MB)
2. Limpa arquivos residuais de execuções anteriores
3. Avisa se a data já foi processada antes (pode prosseguir mesmo assim)
4. Atualiza o yt-dlp em background ao iniciar
5. Busca os vídeos publicados na data informada no canal
6. Exibe popup para selecionar quais vídeos processar
7. Baixa o áudio e converte para MP3 (barra de Download + Conversão)
8. Localiza a pasta do mês no Drive (ou cria se não existir)
9. Faz o upload com progresso em tempo real (barra de Upload)
10. Remove os arquivos locais após o upload
11. Salva histórico local e exibe notificação desktop

> **Transmissões ao vivo:** o YouTube pode registrar a data de publicação como o dia seguinte ao culto. O script lida com isso automaticamente.

---

## Estrutura do projeto

```
youtube_to_drive/
├── app.py                   ← interface gráfica (customtkinter)
├── baixar_audio.py          ← módulo principal (lógica + CLI)
├── setup_wizard.py          ← assistente de configuração inicial
├── historico.json           ← datas já processadas (gerado automaticamente)
├── config.json              ← canal e pasta Drive (gerado automaticamente)
├── credentials/
│   ├── client_secret.json   ← credenciais OAuth (você baixa do Google Cloud)
│   └── token.pkl            ← token de acesso (gerado automaticamente)
├── downloads/               ← pasta temporária (limpa após cada execução)
├── logs/
│   └── DD-MM-YYYY.log       ← log diário (gerado automaticamente)
├── ffmpeg/bin/ffmpeg.exe    ← conversor de áudio
├── instalar.bat             ← instalador sem compilar
├── build_app.spec           ← spec do PyInstaller
├── build_installer.bat      ← gera IPMadalena_Setup.exe
└── installer.iss            ← script Inno Setup
```

---

## Gerar o instalador (para desenvolvedores)

Para gerar o `IPMadalena_Setup.exe`:

1. Instale o [Inno Setup 6](https://jrsoftware.org/isdl.php) (pode ser via `winget install JRSoftware.InnoSetup`)
2. Execute `build_installer.bat` com duplo clique

O script cuida de tudo automaticamente em 4 passos:
1. Baixa o `yt-dlp.exe` standalone do GitHub (necessário para bundle correto)
2. Instala/verifica PyInstaller
3. Empacota o app com PyInstaller → `dist\IPMadalena\`
4. Gera o instalador com Inno Setup → `dist\IPMadalena_Setup.exe`

> **Importante:** o `build_installer.bat` deve sempre ser usado em vez de rodar o PyInstaller manualmente — ele garante que o `yt-dlp.exe` standalone correto seja incluído no bundle.

> Sem o Inno Setup, o bundle em `dist\IPMadalena\` pode ser distribuído comprimido como `.zip`.

---

## Solução de problemas

| Problema | Solução |
|---|---|
| Botão "Autorizar Google Drive" aparece no topo | Clique nele ou acesse ⚙ Configurações para autorizar |
| `client_secret.json` não encontrado | O assistente de configuração abre automaticamente na primeira execução |
| Erro de autenticação Google | Acesse ⚙ Configurações → Logout e autorize novamente |
| Nenhum vídeo encontrado para a data | Verifique se o culto foi transmitido nesse dia |
| Upload duplicado | O script detecta arquivos já existentes no Drive e pula automaticamente |
| App abre duas vezes | Somente uma instância é permitida — feche a anterior |
| Sem espaço em disco | O app avisa antes de começar; libere pelo menos 500 MB |
| `yt-dlp: command not found` | Execute `pip install yt-dlp` ou reinstale via `instalar.bat` |
