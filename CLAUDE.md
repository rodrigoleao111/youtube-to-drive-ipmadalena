# IPMadalena — YouTube to Drive

## Regras de trabalho

- **Commits:** somente quando o usuário solicitar explicitamente. Nunca commitar automaticamente após implementar uma mudança.
- **Antes de cada commit:** verificar se `CLAUDE.md` e `README.md` precisam ser atualizados para refletir as mudanças que serão commitadas. Atualizar ambos antes de fazer o commit se necessário.

## O que é este projeto

Script Python com interface gráfica que baixa o áudio dos cultos do canal [@IPMadalena](https://www.youtube.com/@IPMadalena/streams) no YouTube e faz upload para o Google Drive, organizando por pasta de mês.

## Como rodar

### GUI
```bash
python app.py
```

### CLI
```bash
python baixar_audio.py DD/MM/AAAA
```

Exemplo:
```bash
python baixar_audio.py 19/04/2026
```

## Estrutura de arquivos

```
youtube_to_drive/
├── app.py                          ← interface gráfica (customtkinter)
├── baixar_audio.py                 ← módulo principal (lógica + CLI)
├── setup_wizard.py                 ← wizard de primeira execução (5 passos)
├── player_window.py                ← painel de controles de trecho (CTkToplevel)
├── player_subprocess.py            ← subprocesso do player YouTube (pywebview/Edge)
│
├── domain/                         ← núcleo de negócio (sem deps externas)
│   ├── __init__.py
│   ├── entities.py                 ← Video, Segment, AudioFile, ProcessingResult
│   ├── exceptions.py               ← IPMadalenaError, OperacaoCancelada, DomainError...
│   └── ports.py                    ← Protocols: IVideoSource, IAudioDownloader...
│
├── infrastructure/                 ← adaptadores que conectam ao domínio
│   └── youtube/
│       ├── __init__.py
│       ├── _utils.py               ← ytdlp_exe(), ffmpeg_dir(), start_process(), check_cancel()
│       └── ytdlp_source.py         ← YtDlpVideoSource, YtDlpAudioDownloader
│
├── historico.json                  ← datas já processadas (gerado em runtime)
├── config.json                     ← canal YouTube + pasta Drive (gerado em runtime)
├── credentials/
│   └── token.pkl                   ← token OAuth salvo (gerado na 1ª execução)
├── downloads/                      ← pasta temporária, limpa após upload
├── logs/DD-MM-YYYY.log             ← log diário (gerado em runtime)
├── ffmpeg/bin/ffmpeg.exe           ← conversor local de áudio
├── instalar.bat                    ← instalador script (sem PyInstaller)
├── build_app.spec                  ← spec do PyInstaller para gerar .exe
├── build_installer.bat             ← gera instalador completo (PyInstaller + Inno Setup)
└── installer.iss                   ← script Inno Setup para IPMadalena_Setup.exe
```

## Dependências Python

```
yt-dlp
google-api-python-client
google-auth-oauthlib
customtkinter
tkcalendar
plyer
pywebview
```

## Arquitetura — domain/ e infrastructure/ (Clean Architecture, Fase 1+2)

O projeto está em migração incremental para Clean Architecture. As fases concluídas introduzem:

**`domain/` — núcleo de negócio (zero dependências externas)**
- `entities.py` — dataclasses imutáveis (`frozen=True`): `Video`, `Segment`, `AudioFile`, `ProcessingResult`
- `exceptions.py` — hierarquia: `IPMadalenaError` → `DomainError` → `VideoNaoEncontrado`, `SegmentoInvalido`, `ConfiguracaoInvalida`; `OperacaoCancelada` herda direto de `IPMadalenaError`
- `ports.py` — `typing.Protocol` com `@runtime_checkable`: `IVideoSource`, `IAudioDownloader`, `ICloudStorage`, `IHistoryRepository`, `IConfigRepository`, `INotifier`

**`infrastructure/youtube/` — adaptadores yt-dlp**
- `_utils.py` — utilitários stateless: `ytdlp_exe()`, `ffmpeg_dir()`, `start_process()`, `check_cancel()`
- `ytdlp_source.py` — `YtDlpVideoSource` (implementa `IVideoSource`), `YtDlpAudioDownloader` (implementa `IAudioDownloader`)

**Compatibilidade retroativa em `baixar_audio.py`:**
- `list_videos()` delega para `YtDlpVideoSource` e converte `List[Video]` → `List[dict]`
- `download_selected_sections()` delega para `YtDlpAudioDownloader` e converte `List[AudioFile]` → `List[str]` (caminhos)
- `OperacaoCancelada` é re-exportada de `domain.exceptions` (mesma classe, sem duplicação)
- Nenhuma assinatura pública foi alterada — callers existentes continuam funcionando

**`infrastructure/drive/` — adaptador Google Drive (Fase 3)**
- `gdrive_storage.py` — `GoogleDriveStorage` (implementa `ICloudStorage`)
  - `get_service()` — autenticação OAuth2, refresh, reauth, salva token
  - `check_auth()` — verifica se token existe e está válido
  - `logout()` — remove token (força nova autorização)
  - `_find_or_create_month_folder()` — localização fuzzy + criação automática
  - `_upload_single()` — resumable upload com `_ProgressFile` e cancelamento
  - `upload()` — implementa `ICloudStorage.upload()`, retorna `ProcessingResult`
- `_ProgressFile` — streaming com progresso byte-a-byte, stats de taxa, cancel em < 100 ms

**Compatibilidade retroativa em `baixar_audio.py` (Fase 3):**
- `get_drive_service()`, `check_auth_status()`, `run_auth()`, `find_or_create_month_folder()`, `upload_to_drive()`, `upload_files()` → delegam para `GoogleDriveStorage`
- `_ProgressFile` e lógica de OAuth removidas de `baixar_audio.py`

**Fases futuras planejadas:**
- Fase 4: `infrastructure/persistence/` — `JsonHistoryRepository`, `JsonConfigRepository`
- Fase 5: camada `application/` (use cases)
- Fase 6: `presentation/` (presenter pattern para `App`)
- Fase 7: remoção das funções legadas de `baixar_audio.py`

---

## Detalhes técnicos — baixar_audio.py

- **Python:** `C:\Users\rasantos\AppData\Local\Programs\Python\Python312\python.exe`
- **`BASE_DIR`:** detecta execução frozen (PyInstaller): `os.path.dirname(sys.executable)` se `sys.frozen`, senão `os.path.dirname(__file__)`
- **`_ytdlp_cmd()`:** retorna caminho do yt-dlp bundled (`sys._MEIPASS/yt-dlp.exe`) quando frozen, senão `"yt-dlp"`
- **`_LOCAL_FFMPEG`:** verifica `sys._MEIPASS/ffmpeg/bin/ffmpeg.exe` como fallback quando frozen
- **yt-dlp:** usa `--dateafter` + `--break-on-reject` para parar a varredura ao passar da data alvo (o canal tem ~1300 vídeos — sem isso varre tudo); `--socket-timeout 30` em todos os comandos
- **Listagem:** `--simulate --print "%(id)s|||%(title)s|||%(upload_date)s"` — varre sem baixar; após coletar, filtra por `upload_date == data_alvo` ou `upload_date == data_alvo + 1 dia` (lives publicadas com data posterior ao culto)
- **Download:** URLs individuais por ID (`https://www.youtube.com/watch?v=<id>`); player_client `ios,android,web` — `tv_embedded` foi descontinuado pelo YouTube e não deve ser usado
- **`download_selected()`:** aceita callback `on_download_progress(float)` chamado a cada linha `[download] X%` do yt-dlp; progresso normalizado entre vídeos: `(current_video + file_pct) / total_videos`; emite `(current_video + 1) / total_videos` ao detectar `[ExtractAudio]`
- **Encoding do subprocess:** `_start_process()` injeta `PYTHONUTF8=1` e `PYTHONIOENCODING=utf-8` no ambiente — funciona para yt-dlp script; para o standalone, usa-se `--encoding utf-8` diretamente nos comandos yt-dlp (`list_videos` e `download_selected`), pois o standalone ignora variáveis de ambiente do processo pai
- **Janela de console oculta:** `_start_process()` usa `creationflags=subprocess.CREATE_NO_WINDOW` no Windows para que o yt-dlp não abra janela preta visível; o mesmo flag é aplicado em todos os `subprocess.run()` de `update_ytdlp()`
- **ffmpeg** instalado localmente em `ffmpeg/bin/`, referenciado via `--ffmpeg-location`
- **Google Drive API v3** com OAuth2; token salvo em `credentials/token.pkl`
- **Token corrompido:** `get_drive_service()` captura exceção no `pickle.load()`, remove o arquivo e força reautenticação; idem para falha no refresh
- **`check_auth_status()`:** verifica se token existe e é válido (tenta refresh); retorna `True/False`; usado pela GUI para bloquear processamento sem autorização
- **`run_auth(on_log=None)`:** chama `get_drive_service()` para forçar fluxo OAuth; callback de log opcional para a GUI
- **`logout_drive()`:** remove `TOKEN_FILE`; exige nova autorização na próxima operação
- **OAuth server:** `flow.run_local_server(host="127.0.0.1", port=8085)` — porta fixa para não conflitar com outros serviços
- **`check_internet()`:** usa `socket.setdefaulttimeout(5)` com `finally: socket.setdefaulttimeout(None)` — sem o `finally`, o timeout global ficava ativo e causava falha no servidor OAuth após 5 segundos
- **`load_config()` / `save_config()`:** `config.json` com campos `channel_url` e `drive_folder_id`; permite personalizar canal e pasta sem editar código
- **Pasta raiz no Drive:** lida via `drive_folder_id` em `config.json` (padrão: `1KfsI5zCDL4HZ2pdAWPFfAD3TugplzBez`)
- **Subpasta do mês:** localizada por nome fuzzy (aceita `Abril-2026`, `Abril 2026`, `Abr/2026`); se não encontrar, cria automaticamente
- **Upload:** `AuthorizedSession` (google-auth / requests) + streaming via `_ProgressFile`; verificação de duplicatas antes de enviar
- **`_ProgressFile`:** wrapper de arquivo com três responsabilidades separadas:
  - Cancelamento verificado a cada `read()` (~65 KB) → resposta < 100 ms
  - Label de stats na GUI atualizado a cada 1 MB (taxa instantânea do último chunk)
  - Log de texto apenas nos marcos 25 %, 50 % e 75 % (taxa média acumulada) + linha final com taxa média total
  - Expõe `average_rate_mbps()` para o log de conclusão em `upload_to_drive()`
- **Histórico:** `historico.json` — `{date_str: {processado_em, videos: [...]}}` — gerenciado por `load_history()` / `save_history()`
- **Utilitários de robustez:** `check_internet()`, `check_disk_space(min_mb=500)`, `cleanup_downloads()`, `update_ytdlp()`
- **`download_selected_sections()`:** versão por-vídeo de `download_selected()`; recebe `list[{id, title, start, end}]`; adiciona `--download-sections "*HH:MM:SS-HH:MM:SS"` quando start/end presentes; um subprocess por vídeo
- **Modo debug (não-frozen):** em `upload_files()`, o `os.remove(file_path)` após upload é condicionado a `sys.frozen`; em modo script (`python app.py`), o MP3 é mantido em `downloads/` e uma linha `[DEBUG] Arquivo mantido em: ...` é logada

## Detalhes técnicos — app.py

- **Framework:** `customtkinter` (dark mode) + `tkcalendar` para popup de calendário
- **Janela:** 660×700px
- **Thread safety:** `queue.Queue` para comunicação worker→GUI; polling com `self.after(100, _process_queue)`
- **Cancelamento:** `threading.Event` passado a todas as fases; watchdog daemon termina o subprocess; `_check_cancel()` no loop de leitura do stdout
- **Instância única:** porta TCP 47892 reservada via `_acquire_single_instance()`; segunda instância exibe alerta e encerra
- **Log em arquivo:** `logs/DD-MM-YYYY.log` via `logging.basicConfig`; todo log/status/erro é gravado
- **Auto-update yt-dlp:** thread daemon roda `update_ytdlp()` ao iniciar o app
- **Primeira execução:** se `credentials/token.pkl` não existe (usuário ainda não autorizou o Drive), janela principal fica oculta (`withdraw()`) e `SetupWizard` é aberto; ao concluir, `_on_wizard_complete()` chama `_check_auth_visibility()` e exibe a janela (`deiconify()`)
- **Banner de autorização:** frame condicional no topo — aparece via `pack()` quando Drive não autorizado, some via `pack_forget()` quando autorizado; `_check_auth_visibility()` decide exibição
- **Bloqueio de processamento:** `_start()` chama `check_auth_status()` antes de prosseguir; exibe aviso e retorna se não autorizado
- **`_set_status(text, state)`:** atualiza `status_label` e `_status_dot`; estados: `idle` (cinza), `running` (azul), `done` (verde), `error` (vermelho)
- **Barras de progresso (3 uniformes):**
  - `download_bar` — progresso byte a byte via callback `on_download_progress`
  - `conversion_bar` — animação suave `after(160ms)`, sobe até 90% enquanto "Convertendo", zera ao avançar de fase
  - `upload_bar` — progresso byte a byte via streaming `_ProgressFile`
  - Todas agrupadas em `_progress_frame`; `_hide_bars()` faz `pack_forget()` no frame inteiro; `_show_bars()` faz `pack()` antes de `_log_label`
- **`_animate_conversion()`:** iniciada ao detectar "Convertendo" no status; incrementa barra em passos de 1,8% a cada 160ms até 90%; parada ao mudar de fase
- **Ícone da janela:** `self.iconbitmap()` chamado no `__init__` usando `sys._MEIPASS` quando frozen, `__file__` quando script — garante ícone correto na barra de tarefas; `icon.ico` incluído nos `datas` do PyInstaller
- **Tela de configurações (`SettingsWindow`):** `CTkToplevel` com 3 seções:
  - Drive: status de autorização + botão Autorizar/Logout
  - YouTube: campo de entrada para URL do canal
  - Drive folder: campo de entrada para ID da pasta raiz
  - `_refresh_auth_status()`, `_do_authorize()` (thread), `_do_logout()`, `_save()`
- **`_open_settings()`:** cria `SettingsWindow`, vincula `<Destroy>` a `_check_auth_visibility()` para atualizar banner ao fechar
- **Popup de seleção de vídeos:** `_cancelar()` + `popup.protocol("WM_DELETE_WINDOW", _cancelar)` — fechar a janela pelo X agora cancela corretamente em vez de travar
- **Fluxo de execução:**
  1. `_worker_preflight` — verifica internet, disco, limpa resíduos, consulta histórico
  2. Popup de aviso se data já foi processada (pode continuar mesmo assim)
  3. `_worker` — `list_videos()` (fase 1, sem download)
  4. Popup de seleção de vídeos (checkboxes, todos marcados por padrão)
  5. `_show_player_window()` → abre `PlayerWindow`; usuário marca trechos
  6. `_worker_phase2` — `download_selected_sections()` + `upload_files()`
  7. `_on_done()` — salva histórico + notificação desktop via `plyer`
- **Mensagens de fila:** `log`, `status`, `progress`, `download_progress`, `done`, `cancelled`, `error`, `preflight_error`, `history_warning`, `auth_done`, `auth_error`, `open_player`
- **Modo subprocesso do player (frozen exe):** `app.py` detecta `--player-mode` antes de qualquer import do Tkinter; importa `player_subprocess` e chama `main()`, encerrando em seguida — permite que `IPMadalena.exe --player-mode video_id x y w h` rode o player sem inicializar a GUI principal

## Detalhes técnicos — setup_wizard.py

`SetupWizard(ctk.CTkToplevel)` — wizard de primeira execução, aberto automaticamente quando `credentials/token.pkl` não existe (usuário ainda não autorizou o Drive).

**5 passos:**
0. Boas-vindas
1. Canal YouTube — URL do canal (salvo em `config.json`)
2. Pasta Drive — ID da pasta raiz (salvo em `config.json`)
3. Autorização Google — botão que chama `run_auth()` em thread separada; re-renderiza passo ao concluir
4. Conclusão

**Credenciais OAuth embutidas:** não é mais necessário distribuir `client_secret.json`. O `baixar_audio.py` define `_OAUTH_CLIENT_CONFIG` com `client_id` e `client_secret` hardcoded; `get_drive_service()` usa `InstalledAppFlow.from_client_config(_OAUTH_CLIENT_CONFIG, SCOPES)`. O token por usuário (`token.pkl`) continua sendo gerado na primeira autorização.

**Indicador de passos:** linha de dots coloridos — verde (concluído), azul (atual), cinza (pendente).

**`_on_close()`:** se wizard não foi concluído, destrói a janela mestre (encerra o app).

**`_finish()`:** `grab_release()` → `destroy()` → chama callback `on_complete`.

## Detalhes técnicos — player_window.py + player_subprocess.py

**Problema de threading:** `webview.start()` exige ser chamado da thread principal do processo. O Tkinter já ocupa essa thread com `mainloop()`. A solução é rodar o webview em um **processo separado** (`player_subprocess.py`), que tem sua própria thread principal livre.

**Comunicação por pipes:**
- `stdout` do subprocesso → pai: mensagens JSON (`{"type": "ready"}`, `{"type": "mark", "target": "start"|"end", "seconds": float}`, `{"type": "error"}`, `{"type": "closed"}`)
- `stdin` do pai → subprocesso: comandos JSON (`{"cmd": "load", "video_id": "..."}`, `{"cmd": "eval", "js": "..."}`, `{"cmd": "quit"}`)

**`player_window.py`:**
- `PlayerWindow(ctk.CTkToplevel)` — barra horizontal de 860×118px posicionada diretamente abaixo da janela do player, formando unidade visual integrada
- `_calc_positions()`: player em (base_x, base_y), controles em (base_x, base_y + PLAY_H) — colados verticalmente, centralizados na tela
- `_start_player()`: se processo já existe, envia `{"cmd": "load"}` via stdin para navegar sem reabrir; caso contrário inicia novo subprocess via `_build_player_cmd()`
- `_build_player_cmd()`: retorna `[sys.executable, "--player-mode", ...]` se frozen, ou `[sys.executable, "player_subprocess.py", ...]` em modo script
- `_read_player_stdout()`: thread daemon lê JSON do stdout e coloca em `self._ev_queue`
- `_poll_queue()`: chamado a cada 100ms via `after()` — despacha eventos para UI (thread-safe)
- `_request_mark(target)`: envia `{"cmd": "get_time", "target": "start"|"end"}` — subprocess executa `evaluate_js("video.currentTime")` e responde com `{"type": "mark", ...}`
- `_kill_player()`: envia `{"cmd": "quit"}` e chama `terminate()` em fallback
- Botões ◀ ficam desabilitados até receber `{"type": "ready"}`; ao receber, habilita também "Confirmar trecho" e "Usar completo"
- Ao avançar para próximo vídeo: reutiliza subprocess via `{"cmd": "load"}` — sem fechar e reabrir a janela

**`player_subprocess.py`:**
- Carrega `https://www.youtube.com/watch?v=VIDEO_ID` (página completa, sem embed) — evita erro 153 (restrição de incorporação em livestreams)
- Corre `webview.start(gui="edgechromium")` na thread principal deste processo
- `_Bridge`: `on_time_result(seconds, target)` chamado pelos botões overlay no player via `window.pywebview.api`; envia JSON ao pai via `sys.stdout`
- `_on_loaded()`: chamado pelo evento `window.events.loaded`; injeta `_OVERLAY_JS` via `evaluate_js()` para adicionar botões "▶ Marcar Início" / "■ Marcar Fim" sobrepostos ao vídeo (retry automático até o elemento `<video>` estar disponível)
- `_stdin_reader()`: thread daemon lê comandos do pai — `load` → `load_url()`, `get_time` → `evaluate_js("video.currentTime")` + `_send(mark)`, `eval` → `evaluate_js()`, `quit` → `destroy()`
- `evaluate_js()` ignora CSP da página — roda no contexto do renderer como acesso de desenvolvedor

**Modo `--player-mode` (frozen exe):**
- `app.py` verifica `"--player-mode" in sys.argv` antes de qualquer import Tkinter
- Faz `from player_subprocess import main; main(); sys.exit(0)`
- Permite `IPMadalena.exe --player-mode video_id x y w h` rodar como player sem GUI

## Instalação e Distribuição

### instalar.bat — Instalação sem compilar

Script bat para usuários finais que instalam direto do código-fonte:
1. Verifica/instala Python 3.12 via `winget`
2. Instala dependências pip (`yt-dlp`, `customtkinter`, `tkcalendar`, `google-api-python-client`, `google-auth-oauthlib`, `plyer`, `pywebview`)
3. Baixa ffmpeg de BtbN GitHub releases via PowerShell (`Invoke-WebRequest` + `Expand-Archive`)
4. Cria atalho na área de trabalho via `WScript.Shell` apontando para `pythonw.exe app.py`
5. Oferece abrir o app imediatamente

### build_app.spec — PyInstaller

Empacota o app em executável standalone `dist/IPMadalena/IPMadalena.exe`:
- Prioriza `yt-dlp.exe` standalone local (baixado por `build_installer.bat`); fallback para `shutil.which()` — o launcher pip **não funciona** fora do ambiente Python e não deve ser usado
- Inclui `ffmpeg/bin/ffmpeg.exe` local
- Inclui `icon.ico` nos `datas` para que `app.py` possa chamá-lo via `sys._MEIPASS`
- `collect_all("customtkinter")` para assets de tema/imagens
- `collect_data_files("babel")` para localização do tkcalendar
- `hiddenimports` completo: google-auth, google-auth-oauthlib, googleapiclient, plyer.platforms.win, tkcalendar, babel
- `console=False` — sem janela de terminal
- `icon="icon.ico"` se existir

### build_installer.bat — Geração do instalador

Orquestra a geração completa em 4 passos:
1. Baixa/atualiza `yt-dlp.exe` standalone do GitHub releases (`yt-dlp/yt-dlp`) — necessário antes do PyInstaller
2. Verifica/instala PyInstaller
3. Executa `pyinstaller build_app.spec --noconfirm --clean` → `dist/IPMadalena/`
4. Detecta Inno Setup em `%ProgramFiles(x86)%`, `%ProgramFiles%` e `%LOCALAPPDATA%\Programs` (winget instala sem admin); executa `ISCC.exe installer.iss` → `dist/IPMadalena_Setup.exe`
5. Se Inno Setup não encontrado, exibe aviso mas o bundle PyInstaller ainda pode ser distribuído como pasta

**IMPORTANTE:** O arquivo `build_installer.bat` deve conter **apenas caracteres ASCII**. Caracteres UTF-8 como `─`, `—` nos comentários ou no `title` corrompem o parsing do `cmd.exe` antes que o `chcp 65001` entre em vigor, fazendo o bat falhar silenciosamente no passo do PyInstaller sem exibir erro. Use `=`, `-` e hifens simples em todos os echos e comentários.

**Como gerar o build corretamente (via Claude ou terminal):**

Se o `build_installer.bat` falhar ou não rodar pelo Claude, execute os dois comandos abaixo em sequência:

```powershell
# Passo 1 — PyInstaller (recompila o bundle do zero)
& "C:\Users\rasantos\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller build_app.spec --noconfirm --clean

# Passo 2 — Inno Setup (gera o instalador)
& "C:\Users\rasantos\AppData\Local\Programs\Inno Setup 6\ISCC.exe" "C:\Users\rasantos\youtube_to_drive\installer.iss"
```

O instalador final fica em `dist\IPMadalena_Setup.exe`.

### installer.iss — Inno Setup

Gera `dist/IPMadalena_Setup.exe`:
- `PrivilegesRequired=lowest` — instala sem admin
- `DefaultDirName={autopf}\IPMadalena`
- Atalhos em Start Menu + opcional na área de trabalho
- `[Code]`: exibe mensagem na desinstalação preservando a pasta `credentials/`
- `[UninstallDelete]`: remove `downloads/`, `logs/`, `__pycache__/` na desinstalação
- Idioma: Português Brasileiro

## Comportamento especial — transmissões ao vivo

Cultos ao vivo podem ser publicados no YouTube com a data do dia seguinte ao evento. O script usa `--dateafter (data - 1 dia)` para garantir que o yt-dlp não rejeite esses vídeos, e depois filtra explicitamente por `upload_date ∈ {data_alvo, data_alvo + 1 dia}` — sem esse filtro, todos os vídeos a partir da data seriam retornados.

## Testes automatizados

```
tests/
├── conftest.py              ← sys.path + fixture shared_app (sessão)
├── test_baixar_audio.py     ← 39 testes unitários do módulo principal
├── test_app.py              ← 45 testes de integração da GUI
├── test_player_window.py    ← 33 testes do player e utilitários de tempo
├── test_domain.py           ← 42 testes puros da camada de domínio
└── test_ytdlp_source.py     ← 26 testes da infraestrutura YouTube (subprocess mockado)
```

**Total: 185 testes (186 com setup)**

**Como rodar:**
```bash
python -m pytest tests/ -v
# ou pelo atalho:
run_tests.bat
```

**O que é coberto:**
- `check_internet`, `check_disk_space`, `cleanup_downloads`
- `load_history` / `save_history` (arquivo ausente, JSON corrompido, round-trip)
- `_check_cancel` / `OperacaoCancelada`
- `get_drive_service` com token corrompido (verifica log + reauth forçado); usa `from_client_config` (credenciais embutidas)
- `--socket-timeout 30`, `--dateafter`, `--break-on-reject` nos comandos yt-dlp
- `download_selected_sections`: flag `--download-sections`, vídeo completo, um subprocess por vídeo, cancelamento entre vídeos
- Modo debug: arquivo mantido em `downloads/` quando não-frozen; removido quando frozen
- Instância única (mock de socket)
- Processamento de todos os tipos de mensagem da fila (`log`, `status`, `progress`, `download_progress`, `done`, `cancelled`, `error`, `preflight_error`, `history_warning`, `open_player`)
- `_worker_preflight`: sem internet, disco insuficiente, data já processada, tudo OK
- `_on_done`: salva histórico, notificação desktop (mock plyer), estado idle
- Cancelamento: sinaliza evento, desabilita botão, oculta barras
- Validação de data: vazia, formato errado, formato correto, sem autorização Drive
- Log em arquivo: criado na pasta `logs/`, nome com data de hoje, entrada de início
- `_seconds_to_hms` / `_hms_to_seconds`: conversão bidirecional, casos inválidos, roundtrip
- `_build_player_cmd`: modo script vs frozen, argumentos de posição
- `PlayerWindow`: inicialização, título e contador, validação de trecho (fim ≤ início, zeros, formato inválido), segmento com start/end, vídeo completo (start/end nulos), avanço entre vídeos, segmentos de múltiplos vídeos, cancelamento, cálculo de duração

**O que NÃO é testado automaticamente** (requer execução manual):
- Fluxo real com YouTube (rede + canal ativo)
- Popup de seleção de vídeos (interação humana)
- Upload real para o Drive (credenciais ativas)
- Notificação desktop visível na bandeja
- Player webview abrindo a página do YouTube

**Notas de implementação:**
- Mocks via `unittest.mock` (biblioteca padrão, sem dependências extras)
- `conftest.py` provê `shared_app` (escopo session) — uma única instância `App` para toda a sessão; evita corrupção do intérprete Tcl ao criar/destruir múltiplas janelas `ctk.CTk()` no mesmo processo
- Fixture `_reset_app_state` (autouse, function-scope) reseta `_running`, barras, fila e log box antes de cada teste
- `PlayerWindow` testado com `patch.object(PlayerWindow, "_start_player")` para evitar abrir subprocess real
- `patch('plyer.notification.notify')` direto — evita `patch.dict(sys.modules)` que corrompe o estado Tcl entre testes
- `MagicMock` não é serializável via pickle → usar `patch('pickle.dump')` nos testes de token

---

## Versionamento

- **Repositório:** [https://github.com/rodrigoleao111/youtube-to-drive-ipmadalena](https://github.com/rodrigoleao111/youtube-to-drive-ipmadalena)
- **Visibilidade:** público
- **Branch principal:** `main`
- **Git config:** `user.name = Rodrigo Augusto Leão dos Santos` / `user.email = rodrigoleao1995@gmail.com`

**Arquivos ignorados via `.gitignore`** (não commitar):
- `credentials/token.pkl` — token OAuth por usuário (sensível, não commitar)
- `downloads/` — pasta temporária de áudios
- `logs/` — logs locais de execução
- `historico.json` — estado local de datas processadas
- `config.json` — configurações locais (canal, pasta Drive)
- `ffmpeg/` — binário grande; instalar localmente
- `dist/`, `build/` — artefatos de compilação PyInstaller
- `*.exe` — binários gerados (inclui `yt-dlp.exe` standalone baixado pelo build)
- `icon.ico` — **rastreado** no repositório (removido do .gitignore)

**Fluxo de commit:**
```bash
git add <arquivos>
git commit -m "mensagem"
git push
```

---

## Autenticação YouTube — Caminhos investigados e resultados

Esta seção documenta todas as abordagens testadas para obter acesso autenticado ao YouTube via yt-dlp, com o objetivo de acessar formatos de áudio isolado (251/140) em vez do formato 18 (vídeo+áudio). **Não reabrir esses caminhos sem uma razão nova concreta.**

### Contexto: por que formatos de áudio isolado importam

| Formato | Tipo | Qualidade | Tamanho/hora |
|---------|------|-----------|--------------|
| 18 | MP4 vídeo+áudio | ~126kbps AAC | ~500 MB |
| 140 | M4A áudio-only | 128kbps AAC | ~57 MB |
| 251 | WebM áudio-only | ~136kbps Opus | ~61 MB |

Formato 251 e 140 são preferíveis: menor download, melhor ou igual qualidade. O yt-dlp já tem `-f "251/140/18"` preparado no código para usar automaticamente quando houver acesso.

### Abordagens testadas (todas falharam para lives)

**1. bgutil-ytdlp-pot-provider** *(instalado, parcialmente útil)*
- Plugin Python + servidor Node.js que gera GVS PO Tokens para o cliente `web`
- Servidor instalado em `~/bgutil-ytdlp-pot-provider/server/` (porta 4416)
- **Resultado:** gera token para `web`, mas o cliente `web` com PO Token ainda só acessa formato 18 para live stream replays. Clientes `ios` e `android` precisam de tokens GVS próprios que o bgutil não fornece
- **Veredito:** útil como preparação para o futuro, não resolve o problema atual

**2. Google OAuthLogin endpoint**
- Tentativa: `GET https://accounts.google.com/accounts/OAuthLogin?access_token=<token>&service=youtube`
- **Resultado:** HTTP 403 Forbidden — endpoint restrito a OAuth clients primeiro-party do Google (Chrome, apps Google). Não funciona para apps de terceiros
- **Não tentar novamente**

**3. AuthorizedSession (google-auth) → YouTube**
- Tentativa: visitar `https://www.youtube.com/` com Bearer token OAuth, capturar cookies da resposta
- **Resultado:** retorna apenas cookies anônimos/analytics (`GPS`, `YSC`, `VISITOR_INFO1_LIVE`) — não são cookies de sessão autenticada. Inúteis para o yt-dlp
- **Não tentar novamente**

**4. yt-dlp device auth (`--username oauth2 --password ""`)**
- Fluxo de device code (Smart TV), sem browser
- **Resultado:** removido pelo yt-dlp em novembro de 2024 porque o YouTube desativou esse método. Resulta em `ERROR: Login with OAuth is no longer supported`
- **Não tentar novamente**

**5. Escopo `youtube.readonly` no OAuth Drive existente**
- Tentativa: adicionar escopo YouTube ao fluxo OAuth já existente (Drive) e usar o token resultante para qualquer das abordagens acima
- **Resultado:** não ajuda — o problema não é autenticação com a API YouTube, mas sim obter cookies de sessão web do YouTube, que o Google não emite via OAuth de terceiros
- **Não tentar novamente**

### Único caminho viável não implementado

**`--cookies-from-browser chrome`** (ou `edge`, `firefox`): lê cookies de sessão diretamente do browser instalado. Requer que o usuário esteja logado no YouTube no browser. Simples de implementar (1 flag no comando yt-dlp), mas cria dependência de browser aberto/logado. Adequado para uso pessoal, menos robusto para app compartilhado.

### Estado atual

O app baixa formato 18 (vídeo+áudio), extrai o áudio via ffmpeg e converte para MP3. O resultado final é qualitativamente equivalente. A seleção `-f "251/140/18"` já está no código — se autenticação via browser cookies for implementada no futuro, os formatos melhores serão usados automaticamente.

---

## Problemas conhecidos / já resolvidos

- Terminal Windows pode ter erro de encoding com títulos especiais → resolvido com `sys.stdout.reconfigure(encoding="utf-8")` no processo principal e `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` injetados no ambiente dos subprocessos yt-dlp
- Listagem retornava vídeos de datas além da data alvo → `--dateafter` só filtra o passado; é necessário filtrar `upload_date` explicitamente no código após receber cada linha do yt-dlp
- `player_client=tv_embedded` descontinuado pelo YouTube → substituído por `ios,android,web`; `tv_embedded` causa `Only images are available for download` em lives recentes
- Rodar via `powershell.exe` a partir do bash (MINGW64) não repassa output corretamente → preferir rodar Python diretamente pelo bash com caminho completo
- `--date` ignora `--dateafter` no yt-dlp → usar apenas `--dateafter` + `--break-on-reject`
- Cancelar operação mostrava popup de erro → separado em mensagem `("cancelled", None)` → `_on_cancelled()` sem popup, texto cinza
- Barra de progresso mostrava marcador em 0% → resolvido com `progress_color=fg_color`
- Upload `PermissionError WinError 32` (arquivo em uso por outro processo) → matar processo Python anterior com `taskkill`
- Upload lento em rede doméstica (~0,05 MB/s) mas normal em hotspot 5G (~0,73 MB/s) → causa confirmada: roteador/ISP aplicando traffic shaping em uploads HTTPS não originados do browser; **workaround: usar hotspot**; investigar QoS do roteador e VPN
- Cancelamento durante upload travava (next_chunk() bloqueava ~55s) → resolvido substituindo googleapiclient MediaFileUpload por streaming via `_ProgressFile` + `AuthorizedSession`
- Log de upload poluído (1 linha por MB) → resolvido logando apenas nos marcos 25 %, 50 %, 75 % e na conclusão
- OAuth timeout em 5 segundos (ERR_CONNECTION_REFUSED) → `check_internet()` definia `socket.setdefaulttimeout(5)` globalmente sem resetar; corrigido com `finally: socket.setdefaulttimeout(None)`
- Fechar popup de seleção de vídeos travava o app → sem handler para `WM_DELETE_WINDOW`, `self._running` ficava `True` sem thread ativa; corrigido adicionando `_cancelar()` + `popup.protocol("WM_DELETE_WINDOW", _cancelar)`
- yt-dlp não encontrava vídeos no exe instalado → `shutil.which()` retornava o launcher pip (não funciona fora do ambiente Python); corrigido baixando o standalone oficial e priorizando-o no `build_app.spec`
- Encoding corrompido no exe instalado (`Evid?ncia`) → `PYTHONUTF8=1` é ignorado pelo standalone yt-dlp (PyInstaller próprio); corrigido passando `--encoding utf-8` diretamente nos comandos yt-dlp
- Janela preta do yt-dlp aparecia na inicialização → `update_ytdlp()` usava `subprocess.run()` sem `CREATE_NO_WINDOW`; corrigido aplicando o flag em todos os `subprocess.run()` da função
- Ícone errado na barra de tarefas → faltava `self.iconbitmap()` no `__init__` e `icon.ico` nos `datas` do PyInstaller; corrigido nas duas frentes
- Fundo branco no ícone → PNG gerado com canvas branco; corrigido com flood-fill BFS a partir dos 4 cantos para tornar área externa transparente sem afetar o branco interno (cruz)
