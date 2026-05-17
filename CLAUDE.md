# IPMadalena — YouTube to Drive

## Regras de trabalho

- **Commits:** somente quando o usuário solicitar explicitamente. Nunca commitar automaticamente após implementar uma mudança.
- **Antes de cada commit:** verificar se `CLAUDE.md` e `README.md` precisam ser atualizados para refletir as mudanças. Atualizar ambos antes de commitar se necessário.
- **Antes de qualquer push:** rodar `python -m pytest tests/` e garantir 100% verde. Nunca fazer push com testes falhando.

## O que é este projeto

Script Python com interface gráfica que baixa o áudio dos cultos do canal [@IPMadalena](https://www.youtube.com/@IPMadalena/streams) no YouTube e faz upload para o Google Drive, organizando por pasta de mês.

## Como rodar

### GUI
```bash
python app.py
```

### CLI (processa todos os vídeos da data inteiros, sem corte)
```bash
python baixar_audio.py DD/MM/AAAA
```

Exemplo:
```bash
python baixar_audio.py 19/04/2026
```

### Testes
```bash
python -m pytest tests/
# ou:
run_tests.bat
```

## Estrutura de arquivos

```
youtube_to_drive/
│
├── domain/                         ← núcleo (zero dependências externas)
│   ├── entities.py                 Video, Segment, AudioFile, ProcessingResult,
│   │                                EqBand, AudioEditConfig
│   ├── audio_presets.py            EQ_FREQS, EQ_PRESET_VOZ_MASCULINA, NOISE_INTENSITIES
│   ├── ports.py                    IVideoSource, IAudioDownloader, IAudioEditor,
│   │                                ICloudStorage, IHistoryRepository,
│   │                                IConfigRepository, INotifier
│   └── exceptions.py               IPMadalenaError, OperacaoCancelada, DomainError, ...
│
├── infrastructure/                 ← adaptadores que implementam os ports
│   ├── youtube/
│   │   ├── _utils.py               ytdlp_exe(), ffmpeg_dir(), start_process(), check_cancel()
│   │   └── ytdlp_source.py         YtDlpVideoSource, YtDlpAudioDownloader
│   ├── audio/
│   │   ├── _utils.py               ffmpeg_exe(), ffprobe_exe(), start_process()
│   │   └── ffmpeg_editor.py        FfmpegAudioEditor (denoise/EQ/fade/concat de vinhetas)
│   ├── drive/
│   │   └── gdrive_storage.py       GoogleDriveStorage, _ProgressFile
│   ├── persistence/
│   │   └── json_repositories.py    JsonHistoryRepository, JsonConfigRepository
│   └── notification/
│       └── plyer_notifier.py       PlyerNotifier
│
├── application/                    ← use cases (orquestradores de domínio)
│   └── use_cases.py                ListVideosUseCase, DownloadSegmentsUseCase,
│                                    EditAudioUseCase, UploadAudioUseCase
│
├── presentation/                   ← adaptadores de UI
│   ├── processing_presenter.py     ProcessingPresenter (download → edit → upload)
│   └── audio_test_presenter.py     AudioTestPresenter (preview da config de áudio)
│
├── composition_root.py             ← fábrica única (DI) de ProcessingPresenter,
│                                    AudioTestPresenter e PlyerNotifier
│
├── app.py                          interface gráfica (PyQt6) com SettingsDialog
│                                    em duas subpáginas (Geral / Edição de áudio)
├── baixar_audio.py                 constantes, utilidades de SO, OAuth config, CLI
├── setup_wizard.py                 wizard de primeira execução
├── player_window_qt.py             launcher do player Qt (subprocess)
├── player_subprocess_qt.py         subprocesso do player YouTube (QWebEngine)
│
├── tests/                          suíte com 673 testes (pytest + unittest.mock)
│
├── historico.json                  datas já processadas (gerado em runtime)
├── config.json                     canal/pasta Drive + audio_edit (gerado em runtime)
├── credentials/token.pkl           token OAuth (gerado em runtime)
├── downloads/                      pasta temporária (limpa após upload em produção)
├── assets/vinhetas/                vinhetas de entrada e saída (intro.{ext}, outro.{ext})
├── logs/DD-MM-YYYY.log             log diário (gerado em runtime)
├── ffmpeg/bin/ffmpeg.exe           conversor de áudio local (+ ffprobe.exe)
│
├── instalar.bat                    instalador sem PyInstaller
├── build_app.spec                  spec do PyInstaller (inclui QtMultimedia)
├── build_installer.bat             gera IPMadalena_Setup.exe
└── installer.iss                   script Inno Setup
```

## Dependências Python

```
PyQt6                        ← UI principal + QWebEngine + QtMultimedia
yt-dlp                       ← listagem e download de áudio
google-api-python-client     ← Google Drive API
google-auth-oauthlib         ← OAuth 2.0 com browser
plyer                        ← notificações desktop
```

**Binários nativos** (em `ffmpeg/bin/` ou no bundle PyInstaller):
- `ffmpeg.exe` — conversor + filtros de edição
- `ffprobe.exe` — duração de áudio (usado pelo `FfmpegAudioEditor`)
- `yt-dlp.exe` — extração do YouTube

---

# Arquitetura

O projeto segue **Clean Architecture** com 4 camadas concêntricas, conectadas por um *composition root*:

```
presentation/   →  application/   →  domain/
                                       ▲
                                       │ implementa
                                  infrastructure/
                                       ▲
                                       │ wired por
                                composition_root.py
```

## Princípios

1. **Domínio é o centro.** `domain/` define entidades, exceções e Protocols (ports). NÃO importa nada de fora — nem de stdlib além do estritamente necessário (`dataclasses`, `typing`).
2. **Infraestrutura depende do domínio**, não o contrário. `infrastructure/X` implementa Protocols definidos em `domain/ports.py` por *duck typing* (sem herança).
3. **Application orquestra o domínio.** Use cases recebem ports via DI no construtor e os compõem em sequências de operações.
4. **Presentation conhece application + domain**, não infraestrutura. O `ProcessingPresenter` recebe use cases via DI; converte tipos do domínio (`Video`, `Segment`) para tipos da View (`dict`).
5. **Composition root é o único módulo que conhece todas as camadas.** É o lugar legítimo onde a regra "camadas internas não conhecem externas" é deliberadamente quebrada — porque ele PRECISA conhecer todas para conectá-las.

## Mapa: Protocol → Implementação

Todos os Protocols do domínio têm implementação concreta em `infrastructure/`:

| Protocol (`domain/ports.py`) | Implementação |
|---|---|
| `IVideoSource` | `infrastructure.youtube.ytdlp_source.YtDlpVideoSource` |
| `IAudioDownloader` | `infrastructure.youtube.ytdlp_source.YtDlpAudioDownloader` |
| `IAudioEditor` | `infrastructure.audio.ffmpeg_editor.FfmpegAudioEditor` |
| `ICloudStorage` | `infrastructure.drive.gdrive_storage.GoogleDriveStorage` |
| `IHistoryRepository` | `infrastructure.persistence.json_repositories.JsonHistoryRepository` |
| `IConfigRepository` | `infrastructure.persistence.json_repositories.JsonConfigRepository` |
| `INotifier` | `infrastructure.notification.plyer_notifier.PlyerNotifier` |

## Fluxo de execução (GUI)

```
App._start(date_str)
  └─> _worker_preflight (thread)              [internet, disco, histórico]
       └─> _worker (thread)                    [delega → ProcessingPresenter.list_videos]
            └─> popup de seleção de vídeos     [interação humana]
                 └─> PlayerWindow              [marcação de trechos]
                      └─> _worker_phase2       [delega → ProcessingPresenter.process_segments]
                           ├─> DownloadSegmentsUseCase
                           ├─> EditAudioUseCase  (no-op rápido se nada habilitado)
                           ├─> UploadAudioUseCase  (grava histórico via IHistoryRepository)
                           └─> _on_done           [notificação via INotifier]
```

### Pipeline de edição de áudio (`EditAudioUseCase` → `FfmpegAudioEditor`)

Aplicado entre o download do trecho e o upload para o Drive. Etapas no
filter graph do ffmpeg, **nessa ordem**:

```
trecho.mp3 ──► afftdn (denoise) ──► equalizer ×5 (EQ) ──► afade (fade in/out)
                                                              │
                                                              ▼
                                          aresample=44100 normalizado
                                                              │
                                                              ▼
                              concat (ou acrossfade) com intro + outro
                                                              │
                                                              ▼
                                                   trecho.mp3 substituído
                                                   (os.replace atômico)
```

Se `AudioEditConfig.has_any_filter_enabled` é False, é um no-op rápido —
nenhum subprocess é disparado e o arquivo original é preservado.

A configuração vive em `config.json` na chave `audio_edit`. Paths de
vinheta são persistidos como **basename** (ex.: `"intro.mp3"`) e expandidos
em runtime para `assets/vinhetas/intro.mp3` via `audio_edit_resolve_paths` —
isso torna a config portátil entre instalações (mover a pasta do app não
quebra a referência).

**Cuidado com a flag `-f mp3`:** o ffmpeg grava em `arquivo.mp3.tmp` (sufixo
necessário para `os.replace` atômico) mas a extensão `.tmp` impede o ffmpeg
de inferir o formato de saída. Sem `-f mp3` explícito, o pipeline falha com
`Unable to choose an output format for '...mp3.tmp'`. A flag está em
`FfmpegAudioEditor._build_cmd` — NÃO remover.

**Diagnóstico de erros do ffmpeg:** `FfmpegAudioEditor.process` acumula as
últimas 20 linhas do stdout/stderr (`deque(maxlen=20)`) e as inclui na
`RuntimeError` quando o ffmpeg falha — assim o erro real (ex.: arquivo
corrompido, codec faltando) fica visível no log do app sem precisar abrir
um terminal.

---

# Regras para criação de código novo

Esta seção é a **norma para qualquer mudança ou adição** ao projeto. Seguir estas regras mantém a arquitetura saudável.

## 1. Onde colocar código novo

| O que você quer adicionar | Onde colocar |
|---|---|
| Conceito de negócio puro (entidade, valor) | `domain/entities.py` |
| Erro de negócio | `domain/exceptions.py` (herda `IPMadalenaError` ou `DomainError`) |
| Novo contrato para uma capacidade externa | Novo Protocol em `domain/ports.py` |
| Implementação de um Protocol (yt-dlp, Drive, ...) | `infrastructure/<area>/<adapter>.py` |
| Operação que combina 2+ ports | Novo use case em `application/use_cases.py` |
| Tradução de tipos do domínio para a View | `presentation/processing_presenter.py` (ou novo presenter) |
| Wiring de dependências | `composition_root.py` |
| Constante ou path do projeto | `baixar_audio.py` (até existir motivo para extrair) |
| Preset / constante do domínio | `domain/audio_presets.py` ou módulo similar (sem lógica) |
| UI / PyQt6 | `app.py` (ou novo módulo de UI sem deps de domínio) |

## 2. Regras de dependência (NÃO QUEBRAR)

- ❌ `domain/` NUNCA importa de `application/`, `infrastructure/`, `presentation/`, `app.py`, `baixar_audio.py`
- ❌ `application/` SÓ importa de `domain/`
- ❌ `infrastructure/X` importa de `domain/` (para implementar Protocols); NÃO importa de outras subpastas de `infrastructure/`, `application/` ou `presentation/`
- ❌ `presentation/` importa de `application/` e `domain/`; NÃO importa de `infrastructure/`
- ✅ `composition_root.py` pode importar de TODAS as camadas — é seu único papel

**Como verificar:** `grep -r "from infrastructure" domain/ application/ presentation/` deve ser vazio. `grep -r "from presentation" domain/ application/ infrastructure/` deve ser vazio.

## 3. Convenções de código

- **Entidades:** `@dataclass(frozen=True)` em `domain/entities.py`. Sem método com I/O. Métodos só para cálculos derivados (ex.: `Segment.is_full_video`).
- **Protocols:** `typing.Protocol` com `@runtime_checkable` em `domain/ports.py`. Nome com prefixo `I` (de Interface).
- **Use cases:** `@dataclass` com ports injetados no `__init__`. Método público `execute(...)`. Sem estado mutável entre chamadas.
- **Adaptadores de infra:** classe stateless (estado só no construtor para configuração). Implementa o Protocol por duck typing — sem herdar dele.
- **Callbacks opcionais (`on_log`, `on_status`, `on_progress`):** aceitar `Optional[Callable]`. Pattern: `log = on_log if callable(on_log) else _noop`. `_noop` é função privada do módulo.
- **Cancelamento:** qualquer operação longa aceita `cancel_event: Optional[threading.Event]`. Em pontos seguros, chamar `check_cancel(cancel_event)` (de `infrastructure.youtube._utils`) — levanta `OperacaoCancelada`.
- **Best-effort em coisas opcionais:** notificação desktop, cleanup de arquivos residuais, log de stats — usar `try/except: pass` ou silenciar I/O errors (ver `JsonHistoryRepository.save`).
- **Logging para diagnóstico:** mensagens de baixo nível (comando ffmpeg construído, durações detectadas, stderr de subprocess) usam `logging.getLogger("audio_edit")` — vai para `logs/DD-MM-YYYY.log`. NÃO usar `print(..., file=sys.stderr)` em código que rode no .exe empacotado: o usuário não vê stderr.

## 4. Regras de teste

**Toda mudança em código de produção exige um teste.** Sem exceção.

| Camada | Estilo de teste | Mocks |
|---|---|---|
| `domain/` | Testes puros | NENHUM mock |
| `application/use_cases.py` | Testes unitários | Mockar os ports (Protocols) com `MagicMock` |
| `presentation/` | Testes unitários | Mockar os use cases |
| `infrastructure/X` | Testes unitários | Mockar o I/O externo (`subprocess`, `requests`, `plyer`, etc.). Para `persistence/`, usar `tmp_path` pytest fixture com I/O real. |
| `composition_root.py` | Validar wiring | Patch `baixar_audio.load_config` para customizar config; verificar tipos retornados |
| `app.py` | Integração da GUI | Mockar `_build_presenter` ou os métodos do presenter |

**Convenções de teste:**
- Um arquivo `tests/test_<modulo>.py` por módulo de produção.
- Usar `pytest` + `unittest.mock` apenas (zero deps extras).
- `tmp_path` fixture quando I/O real for desejável (mais robusto que mockar `open`).
- Cada teste tem nome descritivo em português: `test_<comportamento>_<condicao>`.
- Agrupar testes em classes `Test<Capability>` por sub-funcionalidade.
- Para regressão de bug: comentário no teste citando o ID do bug ou a referência da revisão.

## 5. Encapsulamento

- **Atributos privados:** prefixo `_` para o que não é parte do contrato externo (ex.: `_history_repo`, `_save_token`, `_DL_PCT_RE`).
- **NÃO acessar atributos privados de outros módulos.** Se precisar, ou expõe (renomeia sem `_`) ou cria getter/factory público.
- **Composition root é a fronteira** entre constantes/configuração e wiring. `app.py` e `baixar_audio.run()` NÃO devem chamar `_history_repo()`, `_make_drive_storage()` etc. diretamente — usam `composition_root.build_processing_presenter()`.

## 6. Antes de fazer push

1. `python -m pytest tests/` — DEVE passar 100% (atualmente 673/673).
2. Atualizar `CLAUDE.md` se a arquitetura, convenções ou estrutura mudaram.
3. Atualizar `README.md` se o comportamento visível ao usuário/dev mudou.
4. Mensagem de commit em formato convencional: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
5. Push para `main` (não há outras branches; é projeto solo).

---

# Detalhes técnicos por módulo

## `baixar_audio.py`

Módulo "raiz" do projeto: hospeda constantes, configuração OAuth, utilidades de robustez do SO, wrappers finos para auth do Drive e a CLI. **NÃO contém lógica de negócio** — toda a orquestração delega ao `ProcessingPresenter` via `composition_root`.

- **Python:** `C:\Users\rasantos\AppData\Local\Programs\Python\Python312\python.exe`
- **`BASE_DIR`:** `os.path.dirname(sys.executable)` se `sys.frozen`, senão `os.path.dirname(__file__)` — dados do usuário (credentials/, downloads/, etc.) ficam ao lado do .exe quando empacotado
- **`_ytdlp_cmd()`:** retorna `sys._MEIPASS/yt-dlp.exe` quando frozen, senão `"yt-dlp"`
- **`_LOCAL_FFMPEG`:** verifica `sys._MEIPASS/ffmpeg/bin/ffmpeg.exe` como fallback quando frozen
- **`_OAUTH_CLIENT_CONFIG`:** credenciais OAuth EMBUTIDAS — não é necessário distribuir `client_secret.json`. `GoogleDriveStorage.get_service()` usa `InstalledAppFlow.from_client_config(_OAUTH_CLIENT_CONFIG, SCOPES)`. Token por usuário (`token.pkl`) é gerado na 1ª autorização.
- **`check_internet()`:** `socket.setdefaulttimeout(5)` com `finally: socket.setdefaulttimeout(None)` — sem o `finally`, timeout global ficava ativo e causava falha no servidor OAuth após 5 s
- **`update_ytdlp()`:** frozen → `yt-dlp -U` (auto-update standalone); script → `pip install --upgrade yt-dlp`. Em ambos: `creationflags=CREATE_NO_WINDOW` no Windows.
- **`run()` (CLI):** delega ao `composition_root.build_processing_presenter()`; processa todos os vídeos da data inteiros (sem corte de trecho).
- **Re-export:** `OperacaoCancelada` é importada de `domain.exceptions` (mesma classe; código legado que importa de `baixar_audio` continua funcionando).
- **`VINHETAS_DIR`:** `BASE_DIR/assets/vinhetas/` — pasta interna do app onde as vinhetas selecionadas pelo usuário são copiadas. Sobrevive a renomeações da pasta original.
- **`config_repo()`:** público (não mais `_config_repo`) — fábrica do `JsonConfigRepository` com defaults do projeto, incluindo `audio_edit` (config padrão do pipeline de edição). Usado pelo composition root para injetar o repo em use cases.
- **`audio_edit_persist_paths(d)` / `audio_edit_resolve_paths(d)`:** convertem entre formato persistido (basename) e runtime (path absoluto em `VINHETAS_DIR`). Chamados respectivamente no save da UI e no load do `EditAudioUseCase`. Configs antigas com paths absolutos continuam funcionando (resolve só age em paths não-absolutos).

## `infrastructure/youtube/`

### `_utils.py`
- **`ytdlp_exe()`:** localiza o binário yt-dlp (bundled vs PATH).
- **`ffmpeg_dir()`:** localiza diretório do ffmpeg.exe (local → MEIPASS).
- **`start_process(cmd, cancel_event=None)`:** subprocess.Popen com encoding UTF-8 + `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `CREATE_NO_WINDOW` no Windows. Watchdog daemon que polla `cancel_event.wait(timeout=0.5)` em loop até `process.poll() != None` — termina o subprocess se cancelado, encerra naturalmente caso contrário (não vaza thread).
- **`check_cancel(cancel_event)`:** levanta `OperacaoCancelada` se evento sinalizado; passa silenciosamente se `None`.

### `ytdlp_source.py`
- **`YtDlpVideoSource.list_videos`:** `--simulate --print "%(id)s|||%(title)s|||%(upload_date)s"` + `--dateafter (data-1d)` + `--break-on-reject` (o canal tem ~1300 vídeos — sem isso varre tudo). Filtra `upload_date ∈ {data_alvo, data_alvo+1}` (lives publicadas com data posterior ao culto). `--socket-timeout 30`. Levanta `VideoNaoEncontrado` se nenhum vídeo bate.
- **`YtDlpAudioDownloader.download`:** um subprocess por segmento. URLs por ID (`youtube.com/watch?v=<id>`); player_client `ios,android,web` (`tv_embedded` foi descontinuado e causa "Only images are available for download" em lives). Trecho via `--download-sections "*HH:MM:SS-HH:MM:SS"`. **Captura o caminho do MP3 da linha `[ExtractAudio] Destination:`** do stdout — não usa glob para evitar contaminação por arquivos pré-existentes em `output_dir`. `AudioFile.video_id` é preservado do `Segment` original.
- **Encoding do subprocess yt-dlp standalone:** `PYTHONUTF8=1` é IGNORADO pelo standalone (PyInstaller próprio). Por isso usamos `--encoding utf-8` direto nos comandos yt-dlp.
- **Progresso normalizado:** linha `[download] X%` → `(idx + X/100) / total`; linha `[ExtractAudio]` → `(idx+1)/total`.

## `infrastructure/drive/gdrive_storage.py`

- **Google Drive API v3 + OAuth2.** Token salvo em `credentials/token.pkl` via `pickle`.
- **`get_service()`:** lê token; refresh se expirado; abre browser (porta 8085) se necessário; salva via `_save_token()` (que cria `credentials/` se não existir).
- **Token corrompido:** captura exceção no `pickle.load()`, remove o arquivo e força reauth. Idem para falha no refresh.
- **`build("drive", "v3", credentials=creds, cache_discovery=False)`:** silencia o warning "file_cache is only supported with oauth2client<4.0.0".
- **`check_auth()`:** valida token e tenta refresh; retorna `bool`. Usado pela GUI para bloquear processamento sem autorização.
- **`_find_or_create_month_folder()`:** match fuzzy contra candidatos `"{mes} {ano}"`, `"{mes}-{ano}"`, `"{mes}/{ano}"`, `"{ano}-{MM}"`, `"{MM}/{ano}"`. Sem candidato bare `mes` (era permissivo demais — match com "Maio Festival 2025" para qualquer ano). Cria automaticamente se não encontrar.
- **`_upload_single()`:** verifica duplicata com escape correto de Drive Query Language (`\\` e `\'` — não remover apóstrofo, isso causaria falso negativo). Resumable upload via `AuthorizedSession.post()` para obter URI, `session.put(data=_ProgressFile)` para streaming. Cancel check antes do POST e durante cada `read()` do `_ProgressFile`.
- **`_ProgressFile`:**
  - Cancelamento verificado a cada `read()` (~65 KB) → resposta < 100 ms.
  - Label de stats na GUI atualizado a cada 1 MB (taxa instantânea do último chunk).
  - Log de texto apenas nos marcos 25 %, 50 %, 75 % (taxa média acumulada) + linha final.
  - Guard contra divisão por zero quando `_size == 0`.
- **`upload()`:** orquestra duplicate-check → upload streaming → remove arquivo local se `delete_after_upload=True`. Retorna `ProcessingResult(uploaded_files, skipped_files)`.
- **`delete_after_upload`** é controlado pelo `composition_root` (reflete `sys.frozen`). Em modo script, MP3s ficam em `downloads/` e linha `[DEBUG] Arquivo mantido em: ...` é logada.

## `infrastructure/persistence/json_repositories.py`

- **`JsonHistoryRepository`:** `load()` retorna `{}` se arquivo ausente/corrompido. `save()` SILENCIA I/O errors (histórico não pode quebrar o fluxo principal). `record(date_str, titles)` adiciona timestamp ISO. `is_processed(date_str)` consulta `load()`.
- **`JsonConfigRepository`:** `load()` preenche chaves ausentes com defaults (`channel_url`, `drive_folder_id`). `save()` LANÇA exceção em erro (config é crítico — usuário espera confirmação). `update(**kwargs)` strips strings, ignora `None`, persiste apenas campos fornecidos.

## `infrastructure/notification/plyer_notifier.py`

- **`PlyerNotifier.notify(title, message, *, app_name="IPMadalena", timeout=8)`:** import lazy de `plyer.notification` (evita carregar plyer se nunca chamado). Best-effort: `try/except: pass` envolve toda a chamada — plyer ausente, sem DBus, etc., são silenciados. Não interrompe o fluxo principal.

## `application/use_cases.py`

- **`ListVideosUseCase(source: IVideoSource)`:** wrapper fino sobre `IVideoSource.list_videos()`. Existe para isolar callers da implementação concreta.
- **`DownloadSegmentsUseCase(downloader: IAudioDownloader)`:** wrapper fino sobre `IAudioDownloader.download()`.
- **`UploadAudioUseCase(storage: ICloudStorage, history: IHistoryRepository)`:** orquestra `storage.upload()` + `history.record()`. Grava histórico apenas quando `result.uploaded_files` é não vazio. Aceita `**extra_storage_kwargs` para repassar callbacks específicos do storage (ex.: `on_upload_stats`).

## `presentation/processing_presenter.py`

- **`ProcessingPresenter`** (dataclass) compõe os três use cases em duas operações de alto nível:
  - `list_videos(date_str, *, cancel_event, on_log, on_status) -> List[dict]` — fase 1.
  - `process_segments(date_str, segments_data, *, cancel_event, on_log, on_status, on_download_progress, on_upload_progress, on_upload_stats) -> List[str]` — fase 2.
- Conversão `Video → dict` (saída) e `dict → Segment` (entrada) acontece no presenter, isolando a View dos tipos de domínio.
- `VideoNaoEncontrado` é convertido para `RuntimeError` (mantém contrato histórico de `baixar_audio.list_videos()`).
- Não conhece Tk/customtkinter — recebe os use cases via DI e expõe callbacks que a View aciona.

## `composition_root.py`

- **`build_processing_presenter()`:** constrói um `ProcessingPresenter` fresco com toda a infraestrutura wired. Reconstruir a cada chamada permite refletir mudanças em `drive_folder_id`/`channel_url` que o usuário tenha feito desde a última invocação. Lê config via `baixar_audio.load_config()` (público).
- **`build_notifier()`:** retorna um `PlyerNotifier`.
- Único módulo do projeto que conhece todas as camadas. Eliminou a duplicação de wiring que existia entre `app._build_presenter()` e `baixar_audio.run()`.

## `app.py`

- **Framework:** PyQt6. **Janela:** `QMainWindow` com sidebar à esquerda + `QStackedWidget` à direita (4 páginas: Início / Processar / Histórico / Configurações).
- **`APP_VERSION`:** constante de módulo (`"v3.2.0"`) usada na sidebar e no rodapé da aba Configurações. Bumpar aqui ao fechar cada versão.
- **Página Início (`_build_home_page`):** lista arquivos MP3 em `DOWNLOAD_DIR` como cards (220×262 px). Topbar com `QComboBox` de ordenação ("Mais recentes" / "A–Z"). Estado vazio com ícone grande + instrução de ação. Subtítulo mostra contagem e tamanho total. Badge "✓ Enviado ao Drive" (verde) ou "● Local" (cinza) detectado pelo título do arquivo vs. `historico.json`. Botão "↑" (SP_ArrowUp) dispara re-upload individual em thread daemon; botão lixeira (SP_TrashIcon) exclui local com confirmação em português.
- **`_reupload_file(fpath, btn)`:** constrói `AudioFile(video_id="")` com `mtime` como `date_str`, chama `upload_uc.execute()` em thread, atualiza badge via `QTimer.singleShot(0, _refresh_home)`.
- **`_open_today_log()`:** abre `LOGS_DIR/DD-MM-YYYY.log` com `os.startfile()`; avisa com `QMessageBox.information` se o arquivo não existe ainda.
- **`_on_home_sort_changed(idx)`:** atualiza `self._home_sort_order` e relama `_refresh_home()`. Preferência in-memory (sem persistência).
- **`closeEvent`:** verifica `self._running`; se True, exibe `QMessageBox` de confirmação em português antes de aceitar o fechamento. Sem operação em curso, fecha imediatamente.
- **Thread safety:** `queue.Queue` para o pipeline principal (download → edit → upload) + polling com `QTimer` no main thread. Para o preview de áudio, ver "Dispatcher cross-thread" abaixo.
- **Cancelamento:** `threading.Event` passado a todas as fases; watchdog daemon termina o subprocess; `check_cancel()` no loop de leitura do stdout.
- **Instância única:** porta TCP 47892 reservada via `_acquire_single_instance()`; segunda instância exibe alerta e encerra.
- **Log em arquivo:** `logs/DD-MM-YYYY.log` via `logging.basicConfig`. **No modo script (não-frozen), também escreve em stderr** — `_setup_file_logging()` adiciona um `StreamHandler` quando `sys.frozen` é False. Isso faz `logging.getLogger("audio_edit").info(...)` aparecer no console do dev, sem prejudicar o .exe empacotado (que não tem stderr visível).
- **Auto-update yt-dlp:** thread daemon roda `update_ytdlp()` ao iniciar.
- **Primeira execução:** se `credentials/token.pkl` não existe, janela principal é `hide()` e `SetupWizard` abre; ao concluir, `_check_auth_visibility()` é chamado e a janela é exibida.
- **Banner de autorização:** `QFrame` condicional no topo — visível quando Drive não autorizado.
- **`_set_status(text, state)`:** atualiza `status_label` e `_status_dot`; estados: `idle` (cinza), `running` (verde), `done` (verde), `error` (vermelho).
- **Barras de progresso (3 uniformes):** `download_bar`, `convert_bar` (mostra progresso REAL da edição de áudio quando habilitada; anima até 90% no fallback de yt-dlp), `progress_bar` (upload). Agrupadas em `_progress_frame`.
- **Página Configurações (`_build_config_page`):** título + subtítulo + **`QTabWidget`** com 2 abas:
  - **Geral** (`_build_general_tab`): Drive auth, canal YouTube, pasta Drive.
  - **Edição de áudio** (instância de `_AudioSettingsTab`): 4 cards funcionais (vinhetas, fade, EQ, redução de ruído) + card de teste de configuração.
  - Save unificado no rodapé (`_cfg_save`): persiste AMBAS as abas em uma única gravação — evita o footgun de o usuário clicar Save com a aba errada visível e perder mudanças.
- **`_AudioSettingsTab(QWidget)`:** widget self-contained com a sub-aba de edição de áudio. Lê `audio_edit` do `config.json` no construtor (basenames são expandidos para abs paths via `audio_edit_resolve_paths`). Expõe `read_config_from_ui()` para o save unificado da página principal.
- **`_AudioPlayerDialog(QDialog)`:** popup modal de player de áudio (usado pelo botão "Tocar" do card de teste). Tem slider de posição draggable, botões `⏪ -10s` / `▶|⏸` / `+10s ⏩`, display `MM:SS / MM:SS`. Auto-play ao abrir; para o `QMediaPlayer` no `closeEvent`. Flag `_slider_dragging` evita conflito entre player tick e arrasto do usuário.
- **Dispatcher cross-thread (`_AudioPreviewDispatcher(QObject)`):** ponte thread→GUI para o worker do preview de teste. Razão: `QTimer.singleShot(0, callable)` chamado de uma `threading.Thread` Python NÃO dispara — não há event loop nessa thread. Solução: sinais `pyqtSignal` num `QObject` criado na thread principal; Qt entrega via `QueuedConnection` automático. Sinais: `log_received(str)`, `progress_changed(float)`, `completed(str)`, `cancelled()`, `failed(str)`.
- **`_build_presenter()`:** delega ao `composition_root.build_processing_presenter()`. Reconstrói a cada operação para refletir mudanças nas configurações.
- **`_worker()` (Fase 1) e `_worker_phase2()` (Fase 2):** delegam ao presenter; convertem `OperacaoCancelada` em `("cancelled", None)`, exceções genéricas em `("error", str(e))`.
- **`_worker_preflight`:** chama `baixar_audio.check_internet()`, `check_disk_space()`, `cleanup_downloads()`, `load_history()` diretamente (utilidades, não use cases).
- **`_on_done()`:** salva histórico (`baixar_audio.save_history`) + notificação via `self._notifier.notify(...)` (instância de `PlyerNotifier`).
- **Mensagens da fila:** `log`, `status`, `progress`, `download_progress`, `edit_progress`, `upload_stats`, `done`, `cancelled`, `error`, `preflight_error`, `history_warning`, `auth_done`, `auth_error`, `select_videos`, `open_player`.
- **Modo subprocesso do player (frozen exe):** `app.py` detecta `--player-mode-qt` antes de qualquer import Qt; importa `player_subprocess_qt` e chama `main()`, encerrando em seguida — permite que `IPMadalena.exe --player-mode-qt` rode o player sem inicializar a GUI principal.

## `setup_wizard.py`

`SetupWizard(ctk.CTkToplevel)` — wizard de primeira execução, aberto automaticamente quando `credentials/token.pkl` não existe.

5 passos: Boas-vindas → Canal YouTube → Pasta Drive → Autorização Google → Conclusão.

Indicador de passos: dots coloridos — verde (concluído), azul (atual), cinza (pendente). `_on_close()`: se wizard não foi concluído, destrói a janela mestre. `_finish()`: `grab_release()` → `destroy()` → callback `on_complete`.

## `player_window.py` + `player_subprocess.py`

**Problema de threading:** `webview.start()` exige ser chamado da thread principal do processo. Tkinter já ocupa essa thread com `mainloop()`. **Solução:** rodar o webview em processo separado (`player_subprocess.py`).

**Comunicação por pipes (JSON):**
- subprocess → pai (stdout): `{"type": "ready"}`, `{"type": "mark", "target": "start"|"end", "seconds": float}`, `{"type": "error"}`, `{"type": "closed"}`
- pai → subprocess (stdin): `{"cmd": "load", "video_id": "..."}`, `{"cmd": "eval", "js": "..."}`, `{"cmd": "quit"}`

**`PlayerWindow(ctk.CTkToplevel)`** — barra horizontal de 860×118 px posicionada diretamente abaixo da janela do player, formando unidade visual integrada. Reutiliza o subprocess via `{"cmd": "load"}` quando avança entre vídeos (não fecha/reabre a janela).

**`player_subprocess.py`:** carrega `https://www.youtube.com/watch?v=<id>` (página completa, evita erro 153 de incorporação em livestreams). `webview.start(gui="edgechromium")` na thread principal. Bridge `_Bridge.on_time_result` chamado pelos botões overlay no player. `_OVERLAY_JS` injetado via `evaluate_js()` adiciona botões "▶ Marcar Início" / "■ Marcar Fim" sobre o vídeo (retry até `<video>` estar disponível). `evaluate_js()` ignora CSP da página — roda no contexto do renderer.

---

# Comportamento especial — transmissões ao vivo

Cultos ao vivo podem ser publicados no YouTube com a data do dia seguinte ao evento. O script usa `--dateafter (data - 1 dia)` para garantir que o yt-dlp não rejeite esses vídeos, e depois filtra explicitamente por `upload_date ∈ {data_alvo, data_alvo + 1 dia}` — sem esse filtro, todos os vídeos a partir da data seriam retornados.

---

# Testes automatizados

```
tests/
├── conftest.py                ← sys.path + fixture shared_app (sessão)
├── test_domain.py             ← 87 testes puros do domínio
├── test_ytdlp_source.py       ← 41 testes da infra YouTube (subprocess mockado)
├── test_ffmpeg_editor.py      ← 43 testes do FfmpegAudioEditor (subprocess mockado)
├── test_gdrive_storage.py     ← 38 testes do adaptador Drive (HTTP/Drive API mockados)
├── test_persistence.py        ← 33 testes dos repositórios JSON (I/O real em tmp_path)
├── test_plyer_notifier.py     ← 10 testes do PlyerNotifier (plyer mockado)
├── test_use_cases.py          ← 50 testes dos use cases (ports mockados)
├── test_presenter.py          ← 30 testes do ProcessingPresenter (use cases mockados)
├── test_audio_test_presenter.py ← 17 testes do AudioTestPresenter
├── test_composition_root.py   ← 22 testes do composition root (DI/wiring)
├── test_baixar_audio.py       ← 38 testes de utilidades + auth wrappers + update_ytdlp
├── test_app.py                ← 201 testes de integração da GUI
├── test_player_window.py      ← 34 testes do PlayerWindow
└── test_player_window_qt.py   ← 29 testes do PlayerWindowQt
```

**Total: 673 testes.**

**Como rodar:**
```bash
python -m pytest tests/ -v
# atalho:
run_tests.bat
```

**O que NÃO é testado automaticamente** (requer execução manual com rede/credenciais):
- Fluxo real com YouTube (rede + canal ativo)
- Popup de seleção de vídeos (interação humana)
- Upload real para o Drive (credenciais ativas)
- Notificação desktop visível na bandeja
- Player webview abrindo a página do YouTube

**Notas de implementação:**
- Mocks via `unittest.mock` (biblioteca padrão, sem dependências extras).
- `conftest.py` provê `shared_app` (escopo session) — uma única instância `App` para toda a sessão; evita corrupção do intérprete Tcl ao criar/destruir múltiplas janelas `ctk.CTk()` no mesmo processo. O patch de `update_ytdlp`/`check_auth_status` é desfeito após `App()` ser construído (a thread daemon já capturou a referência ao Mock).
- Fixture `_reset_app_state` (autouse, function-scope) reseta `_running`, barras, fila e log box antes de cada teste.
- `PlayerWindow` testado com `patch.object(PlayerWindow, "_start_player")` para evitar abrir subprocess real.
- `MagicMock` não é serializável via pickle → patch `pickle.dump` nos testes de token.
- Para testar `update_ytdlp` em modo frozen, mockar `baixar_audio._ytdlp_cmd` (acesso a `sys._MEIPASS` falha em ambiente de teste).

---

# Instalação e Distribuição

## `instalar.bat` — Instalação sem compilar

Script `.bat` para usuários finais que instalam direto do código-fonte:
1. Verifica/instala Python 3.12 via `winget`.
2. Instala dependências pip (`yt-dlp`, `customtkinter`, `tkcalendar`, `google-api-python-client`, `google-auth-oauthlib`, `plyer`, `pywebview`).
3. Baixa ffmpeg de BtbN GitHub releases via PowerShell.
4. Cria atalho na área de trabalho via `WScript.Shell` apontando para `pythonw.exe app.py`.
5. Oferece abrir o app imediatamente.

## `build_app.spec` — PyInstaller

Empacota o app em executável standalone `dist/IPMadalena/IPMadalena.exe`:
- Prioriza `yt-dlp.exe` standalone local (baixado por `build_installer.bat`); fallback para `shutil.which()` — o launcher pip **não funciona** fora do ambiente Python e não deve ser usado.
- Inclui `ffmpeg/bin/ffmpeg.exe` local.
- Inclui `icon.ico` nos `datas` para que `app.py` possa chamá-lo via `sys._MEIPASS`.
- `collect_all("customtkinter")` para assets de tema.
- `collect_data_files("babel")` para localização do tkcalendar.
- `hiddenimports` completo: google-auth, google-auth-oauthlib, googleapiclient, plyer.platforms.win, tkcalendar, babel.
- `console=False` (sem janela de terminal); `icon="icon.ico"` se existir.

## `build_installer.bat` — Geração do instalador

Orquestra a geração completa em 4 passos:
1. Baixa/atualiza `yt-dlp.exe` standalone do GitHub releases (`yt-dlp/yt-dlp`).
2. Verifica/instala PyInstaller.
3. Executa `pyinstaller build_app.spec --noconfirm --clean` → `dist/IPMadalena/`.
4. Detecta Inno Setup em `%ProgramFiles(x86)%`, `%ProgramFiles%` e `%LOCALAPPDATA%\Programs`; executa `ISCC.exe installer.iss` → `dist/IPMadalena_Setup.exe`.

**IMPORTANTE:** o arquivo `build_installer.bat` deve conter **apenas caracteres ASCII**. Caracteres UTF-8 como `─`, `—` corrompem o parsing do `cmd.exe` antes que `chcp 65001` entre em vigor, fazendo o bat falhar silenciosamente. Use `=`, `-` e hifens simples.

**Comando manual (se o `.bat` falhar):**
```powershell
& "C:\Users\rasantos\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller build_app.spec --noconfirm --clean
& "C:\Users\rasantos\AppData\Local\Programs\Inno Setup 6\ISCC.exe" "C:\Users\rasantos\youtube_to_drive\installer.iss"
```

## `installer.iss` — Inno Setup

Gera `dist/IPMadalena_Setup.exe`:
- `PrivilegesRequired=lowest` — instala sem admin.
- `DefaultDirName={autopf}\IPMadalena`.
- Atalhos em Start Menu + opcional na área de trabalho.
- `[Code]`: mensagem na desinstalação preservando `credentials/`.
- `[UninstallDelete]`: remove `downloads/`, `logs/`, `__pycache__/` na desinstalação.
- Idioma: Português Brasileiro.

---

# Versionamento

- **Repositório:** [https://github.com/rodrigoleao111/youtube-to-drive-ipmadalena](https://github.com/rodrigoleao111/youtube-to-drive-ipmadalena)
- **Visibilidade:** público.
- **Branch principal:** `main` (única branch ativa).
- **Git config:** `user.name = Rodrigo Augusto Leão dos Santos` / `user.email = rodrigoleao1995@gmail.com`.

**Arquivos ignorados via `.gitignore`** (não commitar):
- `credentials/token.pkl` — sensível.
- `downloads/`, `logs/` — runtime.
- `historico.json`, `config.json` — estado local.
- `ffmpeg/` — binário grande; instalar localmente.
- `dist/`, `build/` — artefatos PyInstaller.
- `*.exe` — binários gerados (inclui `yt-dlp.exe` standalone do build).
- `icon.ico` — **rastreado** no repositório (removido do .gitignore).

**Fluxo de commit:**
```bash
python -m pytest tests/        # garantir 100% verde
git add <arquivos>
git commit -m "<tipo>: <mensagem>"
git push
```

---

# Autenticação YouTube — caminhos investigados

Esta seção documenta abordagens testadas para obter acesso autenticado ao YouTube via yt-dlp, com o objetivo de baixar formatos de áudio isolado (251/140) em vez do formato 18 (vídeo+áudio). **Não reabrir esses caminhos sem uma razão nova concreta.**

## Por que formatos de áudio isolado importam

| Formato | Tipo | Qualidade | Tamanho/hora |
|---------|------|-----------|--------------|
| 18 | MP4 vídeo+áudio | ~126 kbps AAC | ~500 MB |
| 140 | M4A áudio-only | 128 kbps AAC | ~57 MB |
| 251 | WebM áudio-only | ~136 kbps Opus | ~61 MB |

O yt-dlp já tem `-f "251/140/18"` preparado no código para usar automaticamente quando houver acesso.

## Abordagens testadas (todas falharam para lives)

1. **bgutil-ytdlp-pot-provider** *(parcial)*: gera GVS PO Tokens para cliente `web`, mas `web` ainda só acessa formato 18 em livestream replays. `ios`/`android` precisam de tokens GVS próprios não fornecidos.
2. **Google OAuthLogin endpoint**: HTTP 403 — restrito a OAuth clients first-party (Chrome, apps Google).
3. **AuthorizedSession → YouTube**: retorna apenas cookies anônimos (`GPS`, `YSC`, `VISITOR_INFO1_LIVE`), inúteis para autenticação.
4. **yt-dlp device auth (`--username oauth2`)**: removido em nov/2024 — YouTube desativou o método.
5. **Escopo `youtube.readonly` no OAuth Drive existente**: não ajuda — o problema não é autenticar com a API YouTube, mas obter cookies de sessão web (Google não emite via OAuth de terceiros).

## Único caminho viável não implementado

**`--cookies-from-browser chrome|edge|firefox`**: lê cookies de sessão diretamente do browser instalado. Requer usuário logado no YouTube. Simples (1 flag). Cria dependência de browser aberto/logado.

## Estado atual

App baixa formato 18 e extrai áudio via ffmpeg → MP3. Resultado final equivalente. Se autenticação via browser cookies for implementada, formatos melhores serão usados automaticamente pela seleção `-f "251/140/18"`.

---

# Problemas conhecidos / já resolvidos

- Terminal Windows com erro de encoding em títulos especiais → `sys.stdout.reconfigure(encoding="utf-8")` no processo principal e `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` injetados no ambiente dos subprocessos yt-dlp.
- Listagem retornava vídeos de datas além da data alvo → `--dateafter` só filtra o passado; necessário filtrar `upload_date` explicitamente após receber cada linha do yt-dlp.
- `player_client=tv_embedded` descontinuado pelo YouTube → substituído por `ios,android,web`.
- `--date` ignora `--dateafter` no yt-dlp → usar apenas `--dateafter` + `--break-on-reject`.
- Cancelar operação mostrava popup de erro → separado em mensagem `("cancelled", None)` → `_on_cancelled()` sem popup.
- Barra de progresso mostrava marcador em 0% → `progress_color=fg_color`.
- Upload `PermissionError WinError 32` (arquivo em uso) → matar processo Python anterior com `taskkill`.
- Upload lento em rede doméstica (~0,05 MB/s) mas normal em hotspot 5G → ISP/roteador aplicando traffic shaping em uploads HTTPS não-browser. **Workaround:** hotspot.
- Cancelamento durante upload travava (next_chunk() bloqueava ~55 s) → resolvido com streaming via `_ProgressFile` + `AuthorizedSession`.
- Log de upload poluído (1 linha por MB) → resolvido logando apenas nos marcos 25/50/75 % e na conclusão.
- OAuth timeout em 5 segundos → `check_internet()` deixava `socket.setdefaulttimeout(5)` global; corrigido com `finally: socket.setdefaulttimeout(None)`.
- Fechar popup de seleção de vídeos travava o app → adicionado `_cancelar()` + `popup.protocol("WM_DELETE_WINDOW", _cancelar)`.
- yt-dlp não encontrava vídeos no exe instalado → `shutil.which()` retornava launcher pip; corrigido baixando standalone oficial.
- Encoding corrompido no exe instalado (`Evid?ncia`) → standalone yt-dlp ignora `PYTHONUTF8=1`; corrigido com `--encoding utf-8` direto.
- Janela preta do yt-dlp na inicialização → `update_ytdlp()` sem `CREATE_NO_WINDOW`; corrigido aplicando o flag.
- Ícone errado na barra de tarefas → `iconbitmap()` faltando + `icon.ico` ausente em PyInstaller `datas`; corrigido nas duas frentes.
- Watchdog de cancelamento vazava thread daemon → polla `cancel_event.wait(timeout=0.5)` em loop até `process.poll() != None`.
- `_ProgressFile` divisão por zero quando `_size == 0` → guard `if self._size`.
- Duplicate-check no Drive falhava com apóstrofo → escape correto Drive Query Language (`\\` e `\'` em vez de remover).
- `pickle.dump` falhava em primeira execução com `credentials/` ausente → `_save_token()` cria diretório se não existir.
- `YtDlpAudioDownloader.download()` retornava arquivos errados (glob promíscuo) → captura caminho da linha `[ExtractAudio] Destination:` do stdout, preserva ordem dos segments e `video_id` do Segment original.
