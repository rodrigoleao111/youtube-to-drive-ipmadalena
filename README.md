# IPMadalena — YouTube to Drive

Automatiza o download do áudio dos cultos do canal [@IPMadalena](https://www.youtube.com/@IPMadalena/streams) no YouTube e o upload para o Google Drive, organizando os arquivos por pasta de mês.

A partir da v3.0.0, oferece também um **pipeline de edição de áudio** opcional (vinhetas de entrada/saída, fade in/out, equalização de 5 bandas e redução de ruído) — produz arquivos prontos para uso como podcast.

A v3.2.0 introduz a **tela Início**: biblioteca local de áudios baixados com cards, badge de status de envio ao Drive, re-upload individual, ordenação e confirmação ao fechar durante operações em curso.

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
pip install PyQt6 yt-dlp google-api-python-client google-auth-oauthlib plyer
```

Instale o ffmpeg em `ffmpeg/bin/ffmpeg.exe` e execute:

```bash
python app.py
```

---

## Configuração inicial (primeiro uso)

Na primeira execução, o **assistente de configuração** é aberto automaticamente e guia você por 4 passos:

1. **Boas-vindas** — visão geral do app
2. **Canal YouTube** — informe a URL do canal a monitorar
3. **Pasta do Drive** — informe o ID da pasta raiz onde os áudios serão organizados
4. **Autorização Google** — o navegador abre para você aprovar o acesso ao Drive

> As credenciais OAuth já estão embutidas no app — não é necessário nenhum arquivo adicional do Google Cloud Console.

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
4. O **player** abre com o vídeo no YouTube — assista e clique **⏱ Marcar** para capturar o tempo de início e fim da pregação
5. Clique em **Confirmar trecho** (ou **Usar vídeo completo** para enviar sem corte)
6. Acompanhe o progresso pelas barras de **Download**, **Conversão** (edição de áudio) e **Upload**
7. Uma notificação desktop é exibida ao concluir

### Edição de áudio (opcional, novidade da v3.0.0)

Em **Configurações → Edição de áudio**, você pode habilitar um pipeline completo de pós-processamento que gera arquivos prontos para uso como podcast:

- **Vinhetas de entrada/saída** — faça upload de arquivos de áudio (mp3/wav/m4a/ogg/flac); ficam em `assets/vinhetas/` dentro do app, com sobreposição em segundos configurável
- **Fade in / fade out** — duração configurável (0–10 s)
- **Equalização paramétrica de 5 bandas** (80 / 250 / 1k / 4k / 10k Hz, -12 a +12 dB) com preset padrão **"Voz Masculina"** otimizado para clareza em pregações
- **Redução de ruído** com 3 níveis (baixa / média / alta)
- **Teste de configuração** — selecione um arquivo de exemplo, clique em **Gerar preview** e ouça o resultado no player popup integrado (com slider de posição, play/pause e skip ±10s) antes de salvar e processar um culto inteiro

A edição é aplicada automaticamente entre o download do trecho e o upload — sem etapas manuais. A barra de **Conversão** na tela principal exibe progresso real da edição enquanto roda.

Toda a config fica em `config.json` e é portátil entre instalações (paths das vinhetas são gravados como basename, não absolutos — mover a pasta do app não quebra a referência).

### Linha de comando

```bash
python baixar_audio.py DD/MM/AAAA
```

**Exemplo:**
```bash
python baixar_audio.py 19/04/2026
```

---

## Tela Início

A primeira página do app exibe os arquivos MP3 em `downloads/` como cards com:

- **Badge de status** — "✓ Enviado ao Drive" (verde) quando o arquivo já consta no histórico, ou "● Local" (cinza) caso ainda não tenha sido enviado
- **Botão ↑** — re-envia o arquivo ao Drive sem precisar reprocessar o vídeo (aparece apenas em arquivos "Local")
- **Botão lixeira** — exclui o arquivo local com confirmação em português
- **Ordenação** — "Mais recentes" (padrão) ou "A–Z" via combo na topbar
- **Subtítulo** — mostra total de arquivos e espaço ocupado em disco

Para que os arquivos apareçam aqui, ative **Manter arquivos no dispositivo** em Configurações → Geral.

---

## Configurações

Clique no ícone ⚙ no canto superior direito para acessar a tela de configurações:

- **Autorização Google Drive** — autorizar ou revogar acesso
- **Canal YouTube** — alterar a URL do canal monitorado
- **Pasta do Drive** — alterar o ID da pasta raiz de destino
- **Manter arquivos no dispositivo** — mantém os MP3s em `downloads/` após o upload (necessário para a tela Início)
- **Abrir log de hoje** — abre o arquivo de log do dia corrente no bloco de notas

---

## O que o app faz automaticamente

1. Verifica conexão com a internet e espaço em disco (≥ 500 MB)
2. Limpa arquivos residuais de execuções anteriores
3. Avisa se a data já foi processada antes (pode prosseguir mesmo assim)
4. Atualiza o yt-dlp em background ao iniciar
5. Verifica se há nova versão do app no GitHub Releases e exibe banner verde quando disponível — permite baixar e instalar sem sair do app (apenas no instalador; em modo script exibe instrução para `git pull`)
6. Busca os vídeos publicados na data informada no canal
7. Exibe popup para selecionar quais vídeos processar
8. Abre o player para marcar o trecho desejado (início/fim da pregação)
9. Baixa apenas o trecho selecionado e converte para MP3
10. Localiza a pasta do mês no Drive (ou cria se não existir)
11. Faz o upload com progresso em tempo real
12. Remove os arquivos locais após o upload (a menos que "Manter arquivos no dispositivo" esteja ativo)
13. Salva histórico local e exibe notificação desktop

> **Transmissões ao vivo:** o YouTube pode registrar a data de publicação como o dia seguinte ao culto. O script lida com isso automaticamente.

> **Precisão do corte:** o yt-dlp corta no keyframe mais próximo do tempo marcado, com precisão de ±2 segundos.

---

## Estrutura do projeto

```
youtube_to_drive/
│
├── domain/                         ← núcleo de negócio (zero deps externas)
│   ├── entities.py                 Video, Segment, AudioFile, ProcessingResult
│   ├── ports.py                    Protocols: IVideoSource, ICloudStorage, ...
│   └── exceptions.py               OperacaoCancelada, VideoNaoEncontrado, ...
│
├── infrastructure/                 ← adaptadores que implementam os ports
│   ├── youtube/                    yt-dlp: listagem e download
│   ├── drive/                      Google Drive: OAuth + upload streaming
│   ├── persistence/                JSON: history e config
│   └── notification/               plyer: notificação desktop
│
├── application/                    ← use cases (orquestradores do domínio)
│   └── use_cases.py                ListVideos, DownloadSegments, UploadAudio
│
├── presentation/                   ← adaptadores de UI
│   └── processing_presenter.py     compõe use cases para a GUI
│
├── composition_root.py             ← fábrica única do presenter (DI)
│
├── app.py                          ← interface gráfica (PyQt6)
├── baixar_audio.py                 ← constantes, utilidades de SO, CLI
├── setup_wizard.py                 ← wizard de primeira execução
├── player_window_qt.py             ← launcher do player Qt (subprocess)
├── player_subprocess_qt.py         ← subprocesso do player YouTube (QWebEngine)
│
├── tests/                          ← suíte completa (pytest + mocks)
│
├── historico.json                  ← datas já processadas (runtime)
├── config.json                     ← canal e pasta Drive (runtime)
├── credentials/token.pkl           ← token OAuth (runtime)
├── downloads/                      ← pasta temporária (runtime)
├── logs/DD-MM-YYYY.log             ← log diário (runtime)
├── ffmpeg/bin/ffmpeg.exe           ← conversor de áudio local
│
├── instalar.bat                    ← instalador sem compilar
├── build_app.spec                  ← spec do PyInstaller
├── build_installer.bat             ← gera IPMadalena_Setup.exe
└── installer.iss                   ← script Inno Setup
```

---

## Arquitetura

O projeto segue **Clean Architecture** com 4 camadas conectadas por um *composition root*:

```
                  ┌────────────────────────────┐
                  │  presentation/             │  ProcessingPresenter
                  │  (compõe use cases)        │
                  └─────────────┬──────────────┘
                                │
                  ┌─────────────▼──────────────┐
                  │  application/              │  ListVideosUseCase
                  │  (orquestração de domínio) │  DownloadSegmentsUseCase
                  └─────────────┬──────────────┘  UploadAudioUseCase
                                │
                  ┌─────────────▼──────────────┐
                  │  domain/                   │  Entities: Video, Segment, ...
                  │  (núcleo, sem deps)        │  Ports:    IVideoSource, ...
                  └─────────────▲──────────────┘  Exceptions: OperacaoCancelada
                                │ implementa
                  ┌─────────────┴──────────────┐
                  │  infrastructure/           │  YtDlpVideoSource
                  │  (adaptadores)             │  GoogleDriveStorage
                  └────────────────────────────┘  JsonHistoryRepository
                                                  PlyerNotifier
                                ▲
                                │ wired por
                  ┌─────────────┴──────────────┐
                  │  composition_root.py       │  build_processing_presenter()
                  │  (único módulo que conhece │  build_notifier()
                  │   todas as camadas)        │
                  └────────────────────────────┘
```

**Princípios:**
- O **domínio** define contratos via `typing.Protocol` (`@runtime_checkable`) e não importa nada de fora.
- A **infraestrutura** implementa esses Protocols por *duck typing* (sem herança).
- O **composition root** é o único lugar onde a regra "camadas internas não conhecem externas" é deliberadamente quebrada — porque ele *precisa* conhecer todas para conectá-las.

Detalhes técnicos completos (port-by-port, decisões de design, problemas conhecidos resolvidos) estão em [`CLAUDE.md`](CLAUDE.md).

---

## Testes

Suíte com **701 testes** usando apenas `pytest` e `unittest.mock` — sem dependências adicionais:

```bash
python -m pytest tests/
```

Atalho:

```bash
run_tests.bat
```

Distribuição por camada:

| Arquivo | Testes | Cobertura |
|---|---:|---|
| `test_domain.py` | 87 | Entidades, exceções, Protocols (puro) |
| `test_ffmpeg_editor.py` | 43 | FfmpegAudioEditor (subprocess mockado) |
| `test_ytdlp_source.py` | 41 | Adaptadores yt-dlp (subprocess mockado) |
| `test_gdrive_storage.py` | 38 | Drive OAuth + upload (HTTP/Drive API mockados) |
| `test_use_cases.py` | 50 | Use cases da camada application (ports mockados) |
| `test_persistence.py` | 33 | Repositórios JSON (I/O real em `tmp_path`) |
| `test_app.py` | 210 | Integração da GUI (Home, Processar, Config, Player) |
| `test_github_updater.py` | 19 | Auto-update via GitHub Releases (HTTP mockado) |
| `test_baixar_audio.py` | 38 | Utilidades + CLI + auth wrappers |
| `test_presenter.py` | 30 | ProcessingPresenter (use cases mockados) |
| `test_player_window_qt.py` | 29 | PlayerWindowQt |
| `test_composition_root.py` | 22 | Wiring/DI |
| `test_audio_test_presenter.py` | 17 | AudioTestPresenter |
| `test_player_window.py` | 34 | PlayerWindow + utilitários de tempo |
| `test_plyer_notifier.py` | 10 | PlyerNotifier (plyer mockado) |

**Não testado automaticamente** (requer execução manual com rede e credenciais ativas):
fluxo real com YouTube, popup de seleção (interação humana), upload real para Drive, notificação desktop visível, player webview abrindo a página do YouTube.

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
| Erro de autenticação Google | Acesse ⚙ Configurações → Logout e autorize novamente |
| Nenhum vídeo encontrado para a data | Verifique se o culto foi transmitido nesse dia |
| Player não abre | Verifique se o Edge WebView2 Runtime está instalado (já vem com o Windows 11) |
| Upload duplicado | O script detecta arquivos já existentes no Drive e pula automaticamente |
| App abre duas vezes | Somente uma instância é permitida — feche a anterior |
| Sem espaço em disco | O app avisa antes de começar; libere pelo menos 500 MB |
| `yt-dlp: command not found` | Execute `pip install yt-dlp` ou reinstale via `instalar.bat` |
