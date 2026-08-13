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
│   │                                EqBand, AudioEditConfig, PodcastEpisode
│   ├── audio_presets.py            EQ_FREQS, EQ_PRESET_VOZ_MASCULINA, NOISE_INTENSITIES
│   ├── ports.py                    IVideoSource, IVideoFetcher, IChapterSource,
│   │                                IAudioDownloader, IAudioEditor, IArchiver,
│   │                                ICloudStorage, IHistoryRepository,
│   │                                IConfigRepository, INotifier, ISpotifySession
│   └── exceptions.py               IPMadalenaError, OperacaoCancelada, DomainError, ...
│
├── infrastructure/                 ← adaptadores que implementam os ports
│   ├── youtube/
│   │   ├── _utils.py               ytdlp_exe(), ffmpeg_dir(), start_process(), check_cancel()
│   │   └── ytdlp_source.py         YtDlpVideoSource, YtDlpAudioDownloader
│   ├── audio/
│   │   ├── _utils.py               ffmpeg_exe(), ffprobe_exe(), start_process()
│   │   └── ffmpeg_editor.py        FfmpegAudioEditor (denoise/EQ/fade/concat de vinhetas)
│   ├── archive/
│   │   └── zip_archiver.py         ZipArchiver (pacote .zip do episódio)
│   ├── drive/
│   │   └── gdrive_storage.py       GoogleDriveStorage, _ProgressFile
│   ├── persistence/
│   │   └── json_repositories.py    JsonHistoryRepository, JsonConfigRepository
│   ├── spotify/
│   │   └── session.py              SpotifyWebSession (perfil persistente + login)
│   ├── notification/
│   │   └── plyer_notifier.py       PlyerNotifier
│   └── updater/
│       └── github_updater.py       check_latest_version, download_release
│
├── application/                    ← use cases (orquestradores de domínio)
│   └── use_cases.py                ListVideosUseCase, FetchVideoUseCase,
│                                    GetChaptersUseCase, DownloadSegmentsUseCase,
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
│                                    e tela Processar com 2 modos de entrada
│                                    (busca por data | link direto do vídeo)
├── baixar_audio.py                 constantes, utilidades de SO, OAuth config, CLI
├── setup_wizard.py                 wizard de primeira execução
├── player_window_qt.py             launcher do player Qt (subprocess)
├── player_subprocess_qt.py         subprocesso do player YouTube (QWebEngine)
│
├── tests/                          suíte com 860 testes (pytest + unittest.mock)
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
| `IVideoFetcher` | `infrastructure.youtube.ytdlp_source.YtDlpVideoSource` |
| `IChapterSource` | `infrastructure.youtube.ytdlp_source.YtDlpVideoSource` |
| `IAudioDownloader` | `infrastructure.youtube.ytdlp_source.YtDlpAudioDownloader` |
| `IAudioEditor` | `infrastructure.audio.ffmpeg_editor.FfmpegAudioEditor` |
| `IArchiver` | `infrastructure.archive.zip_archiver.ZipArchiver` |
| `ICloudStorage` | `infrastructure.drive.gdrive_storage.GoogleDriveStorage` |
| `IHistoryRepository` | `infrastructure.persistence.json_repositories.JsonHistoryRepository` |
| `IConfigRepository` | `infrastructure.persistence.json_repositories.JsonConfigRepository` |
| `INotifier` | `infrastructure.notification.plyer_notifier.PlyerNotifier` |
| `ISpotifySession` | `infrastructure.spotify.session.SpotifyWebSession` |

## Fluxo de execução (GUI)

A tela Processar tem **dois modos de entrada** (rádios no card de origem): busca
por data (padrão) ou link direto do vídeo. O modo link pula a listagem do canal
e o popup de seleção — o resto do pipeline é idêntico.

```
App._start()
  ├─ modo data → _start_by_date(date_str)
  │    └─> _worker_preflight (thread)          [internet, disco, histórico]
  │         └─> _worker (thread)                [delega → Presenter.list_videos]
  │              └─> popup de seleção de vídeos [interação humana]
  │                   └─> ("check_chapters", …)
  │
  └─ modo link → _start_by_link(url)           [valida via extract_video_id]
       └─> _worker_preflight(None, video_url)  [internet, disco — sem histórico]
            └─> _worker_link (thread)           [delega → Presenter.fetch_video]
                 └─> ("check_chapters", …)      [data derivada do upload_date]

  ("check_chapters") ─> _worker_check_chapters  [capítulo automático, se configurado]
       └─> PlayerWindow                         [marcação de trechos]
            └─> _worker_phase2                  [delega → Presenter.process_segments]
                 ├─> DownloadSegmentsUseCase
                 ├─> EditAudioUseCase  (no-op rápido se nada habilitado)
                 ├─> _build_upload_list  (zip: áudio + capa + descrição)
                 ├─> UploadAudioUseCase  (grava histórico via IHistoryRepository)
                 └─> _on_done           [notificação via INotifier]
```

### Modo link — de onde vem a data

O fluxo inteiro a jusante é indexado por `date_str` (pasta do mês no Drive e
chave do `historico.json`). No modo link não há data digitada, então ela é
derivada do `upload_date` do próprio vídeo por `app._upload_date_to_br()`
(`YYYYMMDD` → `DD/MM/AAAA`); se o provedor não informar a data, cai para a data
de hoje em vez de abortar. O aviso bloqueante de "data já processada" **não**
se aplica aqui — o usuário apontou o vídeo explicitamente; apenas uma linha de
log registra que a data já constava no histórico.

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

### Duração medida — o pipeline inteiro depende dela

`FfmpegAudioEditor._probe_duration()` mede o áudio principal e as vinhetas.
Tudo que é ancorado no **fim** do arquivo depende desse número: `afade=t=out`
(`st = duração − fade`) e o `atrim`/fade out da música de fundo.

Quando a medição falhava (retornava `0.0`), o filter graph saía destrutivo:
`afade=t=out:st=0` silenciava o episódio a partir do primeiro segundo e
`atrim=end=0.001+intro_musical` fazia a música sumir logo depois da abertura.
Foi exatamente esse o sintoma de "a música de fundo sumiu após 8 segundos" —
o usuário tinha 8 s de intro musical configurados.

A causa era o `build_app.spec` empacotar **apenas `ffmpeg.exe`**: sem
`ffprobe.exe` no bundle, toda medição falhava no app instalado (em modo script
funcionava, porque o `ffmpeg/bin/` local costuma ter os dois). Correções:

1. `_probe_duration` tenta o ffprobe e **cai para o próprio ffmpeg**, lendo a
   linha `Duration: HH:MM:SS.ss` (`_RE_DURATION`, que já existia no código e
   nunca era usada);
2. `build_app.spec` passou a empacotar `ffprobe.exe`;
3. sem duração medida, as etapas ancoradas no fim são **puladas com aviso no
   log** — nunca emitidas com `st=0`/`atrim` curto.

### Regras do trecho de música de fundo

- **`amix=inputs=2:duration=first` com o episódio como primeiro input.** A saída
  passa a ter sempre o comprimento do episódio (+ intro musical), com a música
  em loop infinito ou com uma faixa curta que acaba antes. O par
  `shortest`/`longest` anterior só funcionava enquanto bg e episódio tivessem a
  mesma duração medida.
- **`-stream_loop -1` é opção de INPUT** — tem de vir imediatamente antes do
  `-i` da música, depois dos inputs das vinhetas.
- **`bg_music_delay` é intro musical**: a música começa em 0 e o **episódio** é
  empurrado com `adelay`. A saída fica `episódio + delay`.
- **`_bg_end(config, output_dur, bg_dur)` é a âncora do fade out.** Com o loop
  ligado a música é infinita e o fim é o da saída; com o loop **desligado** ela
  acaba na própria duração (`bg_dur`, medida por `_probe_duration`) e é aí que a
  rampa precisa fechar. Ancorar sempre no fim do episódio — como era feito —
  agendava o fade para um ponto onde já não havia música: **defeito visto em
  produção** (log de 31/08/2025, faixa de poucos minutos num culto de 48 min,
  `afade=t=out:st=2904` inaudível e a música cortando seca no meio). Quando a
  faixa é mais curta que o episódio e o loop está desligado, o log explica o que
  vai acontecer e sugere marcar "Repetir em loop".
- **`_fit_bg_fades(fade_in, fade_out, bg_end)`** é a única fonte da verdade dos
  fades da música, usada tanto pelo filter graph quanto pelo log. O orçamento é
  o trecho que a música **de fato ocupa** (`bg_end`), não a saída inteira.
  Quando a soma pedida não cabe, reduz os dois pelo **mesmo fator** (mantém a
  proporção escolhida e faz as rampas se encostarem). Corrige três defeitos:
  fade out maior que o áudio era **descartado inteiro** (a música parava seca)
  enquanto o fade in era encurtado; o fade in tinha um teto arbitrário e
  silencioso de 40 % da saída; e `fade_in + fade_out > output_dur` fazia as
  rampas se sobreporem, com a música nunca alcançando o volume configurado.
  `st=0` no fade out é válido (cobre a faixa toda) e não deve ser filtrado.

### Sobreposição das vinhetas (acrossfade)

`acrossfade=d=X` consome X segundos do fim de um stream e do início do outro.
Com X maior que a vinheta o ffmpeg **não** reclama: engole a vinheta inteira e
ainda come o começo do sermão (vinheta de 4 s com sobreposição de 10 s devorava
6 s de pregação). O painel permite até 10 s, então `_clamp_overlaps()` limita
cada sobreposição à peça mais curta do cruzamento e avisa no log.

`process()` também descarta assets que sumiram do disco (`_drop_missing_assets`)
antes de decidir o fast path — um input inexistente abortaria a edição inteira.

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

1. `python -m pytest tests/` — DEVE passar 100% (atualmente 1223/1223, ~40 s num único processo).
2. Atualizar `CLAUDE.md` se a arquitetura, convenções ou estrutura mudaram.
3. Atualizar `README.md` se o comportamento visível ao usuário/dev mudou.
4. Mensagem de commit em formato convencional: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`.
5. Push para `main` (não há outras branches; é projeto solo).

---

# Detalhes técnicos por módulo

## `baixar_audio.py`

Módulo "raiz" do projeto: hospeda constantes, configuração OAuth, utilidades de robustez do SO, wrappers finos para auth do Drive e a CLI. **NÃO contém lógica de negócio** — toda a orquestração delega ao `ProcessingPresenter` via `composition_root`.

- **Python:** `C:\Users\Rodrigo\AppData\Local\Programs\Python\Python312\python.exe`
- **`BASE_DIR`:** `os.path.dirname(sys.executable)` se `sys.frozen`, senão `os.path.dirname(__file__)` — dados do usuário (credentials/, downloads/, etc.) ficam ao lado do .exe quando empacotado
- **`_ytdlp_cmd()`:** retorna `sys._MEIPASS/yt-dlp.exe` quando frozen, senão `"yt-dlp"`
- **`_LOCAL_FFMPEG`:** verifica `sys._MEIPASS/ffmpeg/bin/ffmpeg.exe` como fallback quando frozen
- **`_OAUTH_CLIENT_CONFIG`:** credenciais OAuth EMBUTIDAS — não é necessário distribuir `client_secret.json`. `GoogleDriveStorage.get_service()` usa `InstalledAppFlow.from_client_config(_OAUTH_CLIENT_CONFIG, SCOPES)`. Token por usuário (`token.pkl`) é gerado na 1ª autorização.
- **`check_internet()`:** `socket.setdefaulttimeout(5)` com `finally: socket.setdefaulttimeout(None)` — sem o `finally`, timeout global ficava ativo e causava falha no servidor OAuth após 5 s
- **`update_ytdlp()`:** frozen → `yt-dlp -U` (auto-update standalone); script → `pip install --upgrade yt-dlp`. Em ambos: `creationflags=CREATE_NO_WINDOW` no Windows.
- **`run()` (CLI):** delega ao `composition_root.build_processing_presenter()`; processa todos os vídeos da data inteiros (sem corte de trecho).
- **Re-export:** `OperacaoCancelada` é importada de `domain.exceptions` (mesma classe; código legado que importa de `baixar_audio` continua funcionando).
- **`GITHUB_REPO`:** `"rodrigoleao111/youtube-to-drive-ipmadalena"` — repo usado pelo worker de auto-update para consultar GitHub Releases.
- **`VINHETAS_DIR`:** `BASE_DIR/assets/vinhetas/` — pasta interna do app onde as vinhetas selecionadas pelo usuário são copiadas. Sobrevive a renomeações da pasta original.
- **`SPOTIFY_PROFILE_DIR`:** `BASE_DIR/credentials/spotify/` — perfil do navegador embutido usado no Spotify (cookies de sessão). Fica junto do `token.pkl` porque é da mesma natureza (credencial do usuário) e, como aquela pasta, **não é removido na desinstalação**.
- **`config_repo()`:** público (não mais `_config_repo`) — fábrica do `JsonConfigRepository` com defaults do projeto, incluindo `audio_edit` (config padrão do pipeline de edição), `upload_to_drive: True` (toggle de upload), `save_video: False` (manter MP4 após conversão) e `spotify` (`show_id`, `title_prefix`, `default_tags`, `logged_in`). **O merge de defaults é raso** (`data.setdefault` por chave de topo), então configs existentes chegam com o dict `spotify` antigo, sem `logged_in` — leia sempre com `.get("logged_in", False)`. Usado pelo composition root para injetar o repo em use cases.
- **`audio_edit_persist_paths(d)` / `audio_edit_resolve_paths(d)`:** convertem entre formato persistido (basename) e runtime (path absoluto em `VINHETAS_DIR`). Chamados respectivamente no save da UI e no load do `EditAudioUseCase`. Configs antigas com paths absolutos continuam funcionando (resolve só age em paths não-absolutos).

## `infrastructure/youtube/`

### `_utils.py`
- **`ytdlp_exe()`:** localiza o binário yt-dlp (bundled vs PATH).
- **`ffmpeg_dir()`:** localiza diretório do ffmpeg.exe (local → MEIPASS).
- **`start_process(cmd, cancel_event=None)`:** subprocess.Popen com encoding UTF-8 + `PYTHONUTF8=1`, `PYTHONIOENCODING=utf-8`, `CREATE_NO_WINDOW` no Windows. Watchdog daemon que polla `cancel_event.wait(timeout=0.5)` em loop até `process.poll() != None` — termina o subprocess se cancelado, encerra naturalmente caso contrário (não vaza thread).
- **`check_cancel(cancel_event)`:** levanta `OperacaoCancelada` se evento sinalizado; passa silenciosamente se `None`.

### `ytdlp_source.py`
- **`extract_video_id(url) -> str | None`:** pura, sem I/O. Aceita `watch?v=`, `youtu.be/`, `/live/`, `/shorts/`, `/embed/`, `/v/`, hosts `m.`/`music.`/`youtube-nocookie`, URL sem esquema e o ID cru de 11 caracteres; ignora query extra (`&t=`, `&list=`, `?si=`). Retorna `None` para qualquer outra coisa — é o validador que `app._start_by_link()` usa **antes** de abrir thread ou subprocess.
- **`YtDlpVideoSource.fetch_video(url)`:** resolve UM vídeo pelo link (modo link da tela Processar). Mesmo `--print` de `list_videos` (formato reaproveitado), mas com `--no-playlist` (links de live vêm com `&list=`) e sem filtro de data. Usa só a primeira linha com `|||`, mas continua drenando o stdout para não travar o subprocess com o pipe cheio. Levanta `VideoNaoEncontrado` se o link for inválido (sem chamar yt-dlp), se não houver saída ou se o returncode for != 0.
- **`_normalize_upload_date(value)`:** o yt-dlp imprime `NA` quando não há data de publicação; vira string vazia para o chamador aplicar seu fallback.
- **`YtDlpVideoSource.list_videos`:** busca em **duas fases + fallback** (medido em 13/08/2026: o caminho antigo — `--dateafter` + `--break-on-reject` com extração completa por vídeo — levava ~19 s para a data mais recente, sendo ~15 s só enumerando as ~1400 entradas da aba antes de extrair qualquer vídeo, e crescia ~1,5 s por vídeo mais novo que o alvo; o novo caminho faz a mesma data em ~5,6 s):
  1. **Fase rápida** (`_buscar_candidatos_flat`): `--flat-playlist --lazy-playlist --extractor-args youtubetab:approximate_date` — o yt-dlp converte o "Streamed X ago" em data APROXIMADA sem extrair cada vídeo (1 requisição por ~30 entradas, ~0,2 s cada; `--lazy-playlist` é obrigatório: sem ele o yt-dlp enumera a aba INTEIRA antes de imprimir a 1ª linha). Seleciona candidatos numa janela de tolerância: 3 dias para trás (fixa — o YouTube arredonda a idade para baixo, então a data aproximada nunca é muito anterior à real) e `_flat_janela_futuro_dias(idade)` para frente (7/12/35/400 dias — a resolução do "X ago" piora com a idade; buckets de anos colapsam numa única data). A leitura PARA após 5 entradas consecutivas mais antigas que a janela (lista decrescente por data) e o subprocess é encerrado com `terminate()`. Entradas `NA` (live em andamento/agendada) só entram como candidatas quando o alvo é ~hoje (máx. 5).
  2. **Confirmação** (`_confirmar_datas`): extração completa SÓ dos candidatos (um único processo yt-dlp com todas as watch URLs, `--ignore-errors` para candidato privado/removido não abortar os demais) + o filtro exato de sempre: `upload_date ∈ {data_alvo, data_alvo+1}`.
  3. **Fallback** (`_listar_por_varredura`): se a fase rápida/confirmação não achar nada, roda o caminho original (`--dateafter (data-1d)` + `--break-on-reject`, extração por vídeo) — o resultado final é sempre idêntico ao comportamento antigo, inclusive o `VideoNaoEncontrado`. Custo: o caso "data sem culto" paga as duas buscas (~23 s), mas o caso de sucesso — o uso real — fica 3–4× mais rápido.
- **`YtDlpAudioDownloader.download`:** fluxo MP4-first — para cada segmento: (1) cria subpasta `output_dir/{nome de build_output_names}/`, (2) baixa MP4 via yt-dlp com `-f bestvideo[ext=mp4]+bestaudio[ext=m4a]/... --merge-output-format mp4`, (3) salva `capa.jpg` via CDN do YouTube e `descricao.txt` via `metadata_fetcher` (best-effort), (4) converte MP4 → MP3 via `subprocess.run` com ffmpeg (`-vn -acodec libmp3lame -q:a 0 -f mp3`), (5) se `save_video=False` (default), remove o MP4. Retorna `AudioFile` com `subfolder` preenchido. Caminho do MP4 resolvido: linha `[Merger] Merging formats into "..."` > `[download] Destination: *.mp4` > glob `*.mp4` na subpasta.
- **`sanitize_folder_name(title) -> str`:** remove caracteres proibidos no Windows (`\\/:*?"<>|`), colapsa espaços, remove `.` e espaços no final, trunca a 150 chars.
- **`build_output_names(output_dir, title) -> (pasta, arquivo)`:** aplica o **orçamento de `MAX_PATH`** (260 chars sem `LongPathsEnabled`) e devolve o mesmo nome para a subpasta e para os arquivos dentro dela — o nome entra **duas vezes** no caminho (`output_dir\<nome>\<nome><sufixo>`), então o limite por nome é `(260 − len(output_dir) − 2 − 20) // 2`, com piso de 24 chars. Os 20 chars de folga cobrem os sufixos que o pipeline acrescenta (`.description`, `.mp4.part`, `.f251.webm`, `.mp3.tmp`, `.zip`).
  **Por que existe:** o template de saída era `%(title)s`, que ignora esse orçamento e reintroduz caracteres de largura total (`｜`, `：`) no lugar de `|` e `:`. Um culto com título de 99 chars num `downloads/` a 70 chars da raiz gerava um caminho de 273 chars e o yt-dlp abortava com `ERROR: Cannot write video description file ...` + código 1 — sem nenhuma pista de que a causa era o tamanho do caminho (log de 14/09/2025). Títulos que já cabiam continuam com o nome intacto.
  `%` do título é escapado como `%%` no template — um `%` solto quebraria o parsing do `-o`.
  **`app._worker_phase2` usa esta função** (não `sanitize_folder_name`) para derivar a subpasta do Spotify: com o nome encurtado, o sanitize sozinho aponta para uma pasta que não existe.
- **`_save_extras(video_id, subfolder, *, on_log)`:** salva `capa.jpg` via CDN YouTube (5 qualidades: maxresdefault → default; descarta placeholders < 500 bytes via `urllib.request` com SSL sem verify) e `descricao.txt` via `metadata_fetcher` injetado. Tudo best-effort — falhas silenciadas.
- **`_convert_to_mp3(mp4_path, mp3_path, *, ffdir, on_log)`:** `subprocess.run` com `CREATE_NO_WINDOW` no Windows. Lança `RuntimeError` se ffmpeg retornar código != 0 (inclui stderr nas últimas 500 chars).
- **Encoding do subprocess yt-dlp standalone:** `PYTHONUTF8=1` é IGNORADO pelo standalone (PyInstaller próprio). Por isso usamos `--encoding utf-8` direto nos comandos yt-dlp.
- **Progresso normalizado:** linha `[download] X%` → `(idx + X*0.8/100) / total` (80% do slot); após `_save_extras` → `(idx+0.9)/total`; após `_convert_to_mp3` → `(idx+1.0)/total`.
- **`fetch_video_metadata(video_id, cancel_event=None) -> dict`:** busca descrição e thumbnail_url via `yt-dlp -j --skip-download`. Retorna `{"description": "", "thumbnail_url": ""}` em qualquer falha.
- **`fetch_video_description(video_id, cancel_event=None) -> str`:** wrapper de compatibilidade sobre `fetch_video_metadata`. Retorna só a `description`. Usado pelo `_SpotifyPrePublishDialog` de forma assíncrona.

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
- **`_mime_for_path(file_path) -> str`:** detecta MIME type pela extensão (`.mp3` → `audio/mpeg`, `.mp4` → `video/mp4`, `.jpg`/`.jpeg` → `image/jpeg`, `.txt` → `text/plain`, `.png` → `image/png`, `.zip` → `application/zip`, outros → `application/octet-stream`). Substitui o hardcoded `"audio/mpeg"` anterior — necessário para fazer upload de MP4, capa.jpg e descricao.txt.
- **`upload()`:** orquestra duplicate-check → upload streaming → remove arquivo local se `delete_after_upload=True` → limpa as subpastas. **A limpeza apaga também os arquivos que ficaram na subpasta**, não só os enviados: com o upload em pacote, o que sobe é o `.zip` e o MP3/capa/descrição que o geraram continuariam no disco para sempre (`delete_after_upload=True` significa "não manter nada local"). Depois de esvaziar, `os.rmdir` remove a subpasta. Retorna `ProcessingResult(uploaded_files, skipped_files)`. **Progresso normalizado:** o callback `on_progress` recebido externamente (0–100) é envolto por `_norm_progress` que distribui o intervalo equitativamente entre todos os arquivos do lote — evita o ciclo 0→100 por arquivo quando a subpasta contém MP3 + capa.jpg + descricao.txt (+ MP4 opcional).
- **`delete_after_upload`** é controlado pelo `composition_root` (reflete `sys.frozen`). Em modo script, arquivos ficam em `downloads/` e linha `[DEBUG] Arquivo mantido em: ...` é logada.

## `infrastructure/persistence/json_repositories.py`

- **`JsonHistoryRepository`:** `load()` retorna `{}` se arquivo ausente/corrompido. `save()` SILENCIA I/O errors (histórico não pode quebrar o fluxo principal). `record(date_str, titles)` adiciona timestamp ISO. `is_processed(date_str)` consulta `load()`.
- **`JsonConfigRepository`:** `load()` preenche chaves ausentes com defaults (`channel_url`, `drive_folder_id`). `save()` LANÇA exceção em erro (config é crítico — usuário espera confirmação). `update(**kwargs)` strips strings, ignora `None`, persiste apenas campos fornecidos.

## `infrastructure/updater/github_updater.py`

- **`check_latest_version(repo, current) -> dict | None`:** consulta `GET /repos/{repo}/releases/latest` via `urllib.request` (stdlib). Compara `tag_name` com `current` usando `_version_tuple` (conversão numérica segura — ex.: `"v3.10.0" > "v3.9.0"`). Retorna `{"version": tag, "download_url": url_do_exe, "notes": corpo_do_release}` somente se houver versão nova E um asset `.exe` disponível. Qualquer exceção (rede, HTTP) é propagada para o chamador tratar.
  - **`notes`** vem do campo `body` do release (Markdown, exibido no `_UpdateAvailableDialog`). A API devolve `body: null` quando o release foi publicado sem descrição — daí o `(data.get("body") or "").strip()`, já que `QTextBrowser.setMarkdown(None)` quebraria. **Consequência prática: escrever a descrição do release é o que o usuário lê no aviso de atualização.**
- **`download_release(url, dest, on_progress)`:** usa `urllib.request.urlretrieve` com `reporthook` que chama `on_progress(float)` com valor em `[0.0, 1.0]`. Sem chamada quando `total_size == 0`.
- **`_version_tuple(v)`:** converte `"v3.2.0"` ou `"3.2.0"` em `(3, 2, 0)` para comparação numérica segura.
- **Sem dependências externas** — usa apenas stdlib (`urllib`, `json`).

## `infrastructure/spotify/session.py`

Sessão do usuário no Spotify for Creators. **Leia o docstring do módulo antes de
mexer** — ele registra as medições que sustentam o desenho.

- **Por que existe:** o `QWebEngineView()` sem perfil explícito usa o perfil padrão do Qt, que no Qt 6 é *off-the-record* (`isOffTheRecord() == True`, `NoPersistentCookies` — medido no Qt 6.11). O login morria ao fechar a janela e o usuário reautenticava a cada publicação.
- **`SpotifyWebSession(storage_dir, config_repo)`:** dona do perfil e do estado. Uma instância por execução (o `App` guarda em `self._spotify_session`) — dois `QWebEngineProfile` sobre o mesmo diretório disputariam o banco de cookies.
- **`login_url()` = `accounts.spotify.com/login?continue=<CREATORS_HOME_URL>`.** **Nunca use a área autenticada do Creators como porta de entrada do login.** Deslogado, o roteador dela falha a autenticação silenciosa e **não** segue para a tela de credenciais — a janela fica carregando para sempre. Regressão de campo (reproduzida aqui): console com `[AuthRouter] auth error {"error": "login_required"}` + `requestStorageAccess: Permission denied`, 25 s parado em `/pod/dashboard` com a página em branco e depois só o banner de consentimento. A tela de credenciais renderiza de imediato e é estável. O `continue` faz o Spotify devolver o usuário ao Creators depois do login — é o que produz a transição usada como prova.
- **`profile()`:** cria o `QWebEngineProfile` NOMEADO (`PROFILE_NAME = "ipmadalena_spotify"`, estável entre versões — mudá-lo perderia o login dos usuários) com `persistentStoragePath`, `cachePath` e `ForcePersistentCookies`. **Criação tardia**: instanciar a sessão não inicializa o QtWebEngine, só o primeiro uso.
- **`desktop_user_agent(ua)`:** remove o token `QtWebEngine/<versão>` do UA padrão, sobrando um UA de Chrome legítimo na versão do Chromium embarcado. Derivado do padrão (em vez de string fixa) para não envelhecer a cada atualização do Qt.
- **`ACCEPT_LANGUAGE = "pt-BR,pt;q=0.9,en;q=0.8"`, aplicado em `_make_profile`:** o `QWebEngineProfile` nasce com `httpAcceptLanguage` **vazio** (medido no Qt 6.11 — string vazia, não o locale do Windows), então o navegador embutido não pedia idioma nenhum e o Spotify for Creators respondia em **inglês**. Medido na raiz pública do Creators, mesmo perfil e mesmo UA, variando só o cabeçalho: vazio → "Make your show the next big thing"; `pt-BR` → "Faça seu programa se destacar". O `en` no fim é fallback para telas sem tradução.
  - A **tela de login já vinha em português** por conta própria: o Spotify redireciona `accounts.spotify.com/login` para `/pt-BR/login` (provavelmente por GeoIP). Quem dependia do cabeçalho era só a área do Creators — onde o episódio é publicado.
- **`classify_url(url) -> 'logged_in' | 'logged_out' | 'unknown'`:** função pura. `accounts.spotify.com` → deslogado; `creators.spotify.com` com path além de `/` → logado; resto → desconhecido. A **raiz** `creators.spotify.com/` é a landing page de marketing e carrega deslogada — por isso não conta.
- **`classify(url)` (não persiste) × `mark_logged_in(bool)` (persiste):** a separação é o cerne. Uma URL isolada NÃO prova sessão:
  1. o desvio do Creators para o login é feito pelo site, não por um 302 — `urlChanged` e o primeiro `loadFinished` chegam com a URL interna ainda no lugar (medido: deslogado, os dois dizem `logged_in`);
  2. pior, com o banner de consentimento de cookies na tela a página **fica** na URL interna indefinidamente (medido: 20 s parada em `/pod/dashboard`). Nenhum tempo de espera transforma "continuo na URL interna" em prova de sessão.
  O veredito **negativo**, sim, é conclusivo. Quem decide o positivo é a janela de login, exigindo a transição `logged_out → logged_in` (ver `app.py`).
- **`is_logged_in()`:** exige o flag `spotify.logged_in` **e** o diretório do perfil em disco — se o usuário apagou `credentials/`, o flag estaria mentindo.
- **`logout()`:** `deleteAllCookies()` só funciona se o perfil já carregou uma página nesta execução (o contexto de rede do Chromium nasce sob demanda); apagar os arquivos só funciona se o Chromium ainda não os abriu (no Windows o banco fica travado). Então: perfil nunca instanciado → `rmtree` na hora; perfil vivo → limpa cookies + grava o marcador `<storage_dir>.wipe`, e `_apply_pending_wipe()` (no construtor) apaga a pasta na próxima abertura. O marcador fica FORA da pasta para não ser removido pelo próprio `rmtree`.

## `infrastructure/notification/plyer_notifier.py`

- **`PlyerNotifier.notify(title, message, *, app_name="IPMadalena", timeout=8)`:** import lazy de `plyer.notification` (evita carregar plyer se nunca chamado). Best-effort: `try/except: pass` envolve toda a chamada — plyer ausente, sem DBus, etc., são silenciados. Não interrompe o fluxo principal.

## `application/use_cases.py`

- **`ListVideosUseCase(source: IVideoSource)`:** wrapper fino sobre `IVideoSource.list_videos()`. Existe para isolar callers da implementação concreta.
- **`FetchVideoUseCase(source: IVideoFetcher)`:** wrapper fino sobre `IVideoFetcher.fetch_video()`. Alternativa ao `ListVideosUseCase` quando o usuário já sabe qual vídeo quer (modo link).
- **`DownloadSegmentsUseCase(downloader: IAudioDownloader)`:** wrapper fino sobre `IAudioDownloader.download()`.
- **`UploadAudioUseCase(storage: ICloudStorage, history: IHistoryRepository)`:** orquestra `storage.upload()` + `history.record()`. Grava histórico apenas quando `result.uploaded_files` é não vazio. Aceita `**extra_storage_kwargs` para repassar callbacks específicos do storage (ex.: `on_upload_stats`).

## `presentation/processing_presenter.py`

- **`ProcessingPresenter`** (dataclass) compõe os use cases em operações de alto nível:
  - `list_videos(date_str, *, cancel_event, on_log, on_status) -> List[dict]` — fase 1.
  - `fetch_video(url, *, cancel_event, on_log, on_status) -> dict` — fase 1 alternativa (modo link). Retorna o **mesmo formato** dos itens de `list_videos` (`id`, `title`, `upload_date`), para que a View trate os dois modos com o mesmo código a partir daí. `VideoNaoEncontrado` → `RuntimeError` (igual a `list_videos`).
  - `process_segments(date_str, segments_data, *, cancel_event, on_log, on_status, on_download_progress, on_upload_progress, on_upload_stats) -> List[str]` — fase 2 (download → edit → `_build_upload_list` → upload).
- Campo `upload_enabled: bool = True` — quando `False`, o passo de upload (`UploadAudioUseCase`) é pulado e o áudio fica apenas local. Configurado pelo composition root a partir de `upload_to_drive` no `config.json`.
- Campo `fetch_video_uc: Optional[FetchVideoUseCase] = None` — tem default apenas para não obrigar quem usa só o fluxo por data a montá-lo; o composition root sempre injeta. `fetch_video()` levanta `RuntimeError` se estiver ausente.
- **`_build_upload_list(audio_files, *, on_log) -> List[AudioFile]`:** para cada AudioFile com `subfolder` preenchido e existente, compacta os artefatos do episódio em **um único `<nome do áudio>.zip`** (via `IArchiver`) — é o pacote que sobe para o Drive, não os arquivos soltos. Regras:
  - o nome do zip vem do **arquivo de áudio** (`af.path`), já sanitizado pelo yt-dlp, não do título do segmento;
  - **vídeos** (`.mp4`/`.mkv`/`.webm`) ficam **fora** do pacote e sobem ao lado — zipar formato já comprimido de centenas de MB não reduz nada;
  - `.zip` e `.tmp` de execuções anteriores são **ignorados por completo** (não entram no pacote nem sobem soltos; um zip antigo duplicaria o episódio no Drive);
  - sem `archiver` injetado, cai no comportamento antigo (arquivos individuais);
  - AudioFiles sem subfolder passam direto (retrocompat) e subpastas duplicadas são ignoradas.
- **`build_upload_package(audio, *, on_log) -> List[AudioFile]`:** versão pública para UM áudio, usada pelo re-envio manual da tela Início — sem ela o Drive ficaria com uma mistura de pacotes e MP3 soltos para o mesmo episódio.
- Conversão `Video → dict` (saída) e `dict → Segment` (entrada) acontece no presenter, isolando a View dos tipos de domínio.
- `VideoNaoEncontrado` é convertido para `RuntimeError` (mantém contrato histórico de `baixar_audio.list_videos()`).
- Não conhece Qt/Tk — recebe os use cases via DI e expõe callbacks que a View aciona.

## `composition_root.py`

- **`build_processing_presenter()`:** constrói um `ProcessingPresenter` fresco com toda a infraestrutura wired. `list_videos_uc`, `chapters_uc` e `fetch_video_uc` compartilham a MESMA instância de `YtDlpVideoSource` (é stateless). Reconstruir a cada chamada permite refletir mudanças em `drive_folder_id`/`channel_url` que o usuário tenha feito desde a última invocação. Lê config via `baixar_audio.load_config()` (público).
- **`build_notifier()`:** retorna um `PlyerNotifier`.
- **`build_spotify_session()`:** retorna a `SpotifyWebSession` apontando para `baixar_audio.SPOTIFY_PROFILE_DIR`, com o `JsonConfigRepository` injetado. Deve ser chamado **uma vez por execução** — o `App` guarda a instância.
- Único módulo do projeto que conhece todas as camadas. Eliminou a duplicação de wiring que existia entre `app._build_presenter()` e `baixar_audio.run()`.

## `app.py`

- **Framework:** PyQt6. **Janela:** `QMainWindow` com sidebar à esquerda + `QStackedWidget` à direita (4 páginas: Início / Processar / Histórico / Configurações).
- **`APP_VERSION`:** constante de módulo (`"v3.5.2"`) usada na sidebar e no rodapé da aba Configurações. Bumpar aqui ao fechar cada versão — e **também o `#define AppVersion` do `installer.iss`**, que ficou parado no 3.0.0 por quatro versões.
- **`_build_palette(dark: bool) -> QPalette`:** constrói a QPalette correta para modo escuro/claro. Chamada no startup (`_q.setPalette(...)`) e em `_toggle_theme`. Necessária porque o QSS global **não** define mais `background-color` na regra `QWidget` — o Fusion style usa a QPalette para pintar controles (`QComboBox`, `QDoubleSpinBox`, `QTabBar`, etc.) que não têm regra QSS explícita.
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
- **Auto-update do app:** thread daemon `_check_update_worker()` consulta GitHub Releases ao iniciar via `infrastructure.updater.github_updater.check_latest_version(baixar_audio.GITHUB_REPO, APP_VERSION)`. Resultado colocado na `_queue` como `("update_available", {"version": ..., "download_url": ..., "notes": ...})`. Exceções silenciadas. `_on_update_available(info)` exibe a faixa **e** o aviso modal. `_on_update_clicked()`: em modo script exibe info; em modo frozen confirma → abre `_UpdateDownloadDialog`. `_UpdateDownloadDialog`: modal com `QProgressBar`, baixa o installer em thread daemon via `download_release()`, ao concluir executa `subprocess.Popen([installer_path])` + `sys.exit(0)`.
- **Aviso modal de nova versão (`_UpdateAvailableDialog`):** aberto por `_show_update_dialog()` na inicialização, com a versão nova, a atual e as notas do release renderizadas em Markdown num `QTextBrowser` (`setMarkdown`, com fallback para `setPlainText`). "Atualizar agora" → `accept()`; "Depois" → `reject()`. **Aparece a cada inicialização enquanto houver versão nova** — "Depois" não persiste nada em disco, de propósito, para o usuário não ficar parado numa versão antiga sem perceber.
  - `_on_update_available` só abre o modal se `self.isVisible()`: durante o `SetupWizard` da primeira execução a janela principal está escondida e o modal apareceria órfão na frente do wizard.
  - O modal é aberto direto do `_process_queue` (thread principal), **sem `QTimer.singleShot`** — timer solto não é cancelável e foi exatamente o que travou a suíte de testes (ver `conftest._sem_timers_orfaos`).
- **Banner de atualização (`_update_banner`):** faixa verde construída em `_build_update_banner()` e inserida **fora do `QStackedWidget`**, no topo da coluna de conteúdo (`_build_ui`), portanto visível em todas as páginas. Começa oculto. Botões: "O que mudou" (`_show_update_dialog`), "Atualizar agora" (`_on_update_clicked`) e "✕" (`.hide()`).
  - **Por que fora do stack:** até a v3.5.1 o banner era construído dentro de `_build_processar_page()` (página 1), mas o app abre na Home (página 0) — o aviso de nova versão só aparecia se o usuário navegasse até "Processar", ou seja, era invisível na prática. O `QFrame#update_banner` também não tinha regra de estilo no QSS (fundo transparente); hoje usa `P.D_UPD_BG`/`P.L_UPD_BD`.
- **Primeira execução:** se `credentials/token.pkl` não existe, janela principal é `hide()` e `SetupWizard` abre; ao concluir, `_check_auth_visibility()` é chamado e a janela é exibida.
- **Banner de autorização:** `QFrame` condicional no topo — visível quando Drive não autorizado.
- **`_set_status(text, state)`:** atualiza `status_label` e `_status_dot`; estados: `idle` (cinza), `running` (verde), `done` (verde), `error` (vermelho).
- **Barras de progresso (3 uniformes):** `download_bar`, `convert_bar` (mostra progresso REAL da edição de áudio quando habilitada; anima até 90% no fallback de yt-dlp), `progress_bar` (upload). Agrupadas em `_progress_frame`.
- **Página Configurações (`_build_config_page`):** título + subtítulo + **`QTabWidget`** com 4 abas (ícones SVG reais via `_logo_icon()`):
  - **Drive** (`_build_drive_tab`): toggle "Fazer upload para o Drive" (primeiro, controla todos os outros), auth Google Drive, pasta Drive, manter arquivos, **salvar vídeo (MP4)** (`_cfg_save_video_check`, default=False), abrir log. Quando o toggle está desmarcado, os cards dependentes são desabilitados e o upload é pulado pelo presenter.
  - **YouTube** (`_build_youtube_tab`): canal YouTube, capítulo automático.
  - **Spotify** (`_build_spotify_tab`): **conta** (status + Entrar/Sair + aviso do que falta), Show ID, prefixo de título, tags padrão. O card de conta é o primeiro porque sem login não há publicação, mesmo com Show ID.
  - **Edição de áudio** (instância de `_AudioSettingsTab`): 4 cards funcionais (vinhetas, fade, EQ, redução de ruído) + card de teste de configuração.
  - Save unificado no rodapé (`_cfg_save`): persiste TODAS as abas em uma única gravação — evita o footgun de o usuário clicar Save com a aba errada visível e perder mudanças.
- **`_AudioSettingsTab(QWidget)`:** widget self-contained com a sub-aba de edição de áudio. Lê `audio_edit` do `config.json` no construtor (basenames são expandidos para abs paths via `audio_edit_resolve_paths`). Expõe `read_config_from_ui()` para o save unificado da página principal.
- **`_AudioPlayerDialog(QDialog)`:** popup modal de player de áudio (usado pelo botão "Tocar" do card de teste). Tem slider de posição draggable, botões `⏪ -10s` / `▶|⏸` / `+10s ⏩`, display `MM:SS / MM:SS`. Auto-play ao abrir; para o `QMediaPlayer` no `closeEvent`. Flag `_slider_dragging` evita conflito entre player tick e arrasto do usuário.
- **Dispatcher cross-thread (`_AudioPreviewDispatcher(QObject)`):** ponte thread→GUI para o worker do preview de teste. Razão: `QTimer.singleShot(0, callable)` chamado de uma `threading.Thread` Python NÃO dispara — não há event loop nessa thread. Solução: sinais `pyqtSignal` num `QObject` criado na thread principal; Qt entrega via `QueuedConnection` automático. Sinais: `log_received(str)`, `progress_changed(float)`, `completed(str)`, `cancelled()`, `failed(str)`.
- **`_build_presenter()`:** delega ao `composition_root.build_processing_presenter()`. Reconstrói a cada operação para refletir mudanças nas configurações.
- **`_worker()` (Fase 1) e `_worker_phase2()` (Fase 2):** delegam ao presenter; convertem `OperacaoCancelada` em `("cancelled", None)`, exceções genéricas em `("error", str(e))`.
- **`_worker_preflight(date_str, video_url=None)`:** chama `baixar_audio.check_internet()`, `check_disk_space()`, `load_history()` diretamente (utilidades, não use cases). Com `video_url` preenchido (modo link) pula a checagem de histórico — não há data ainda — e dispara `_worker_link`.
- **Card de origem (data ⇄ link):** `mode_date_radio` / `mode_link_radio` num `QButtonGroup`, com as duas entradas num `QStackedWidget` (`_input_stack`: índice 0 = data + calendário, 1 = `link_entry`). `_on_input_mode_changed()` troca a página e o subtítulo da tela (`_SUB_BY_DATE` / `_SUB_BY_LINK`). Os botões Processar/Cancelar ficam FORA do stack — são compartilhados pelos dois modos.
- **`_start()`** apenas despacha para `_start_by_date()` ou `_start_by_link()`; a preparação comum (checagem de auth + reset da UI + `_running=True`) vive em **`_prepare_run() -> bool`**, que retorna `False` sem tocar na UI quando o Drive não está autorizado.
- **`_start_by_link()`:** valida com `extract_video_id` antes de qualquer thread; erro de link mostra exemplos dos formatos aceitos.
- **`_worker_link(url)`:** delega a `Presenter.fetch_video`, deriva `date_str` de `_upload_date_to_br(video["upload_date"])` e enfileira `("check_chapters", (date_str, [video]))` — reaproveitando todo o fluxo a partir da detecção de capítulos. Mesmas conversões de exceção dos outros workers.
- **`_on_done()`:** salva histórico (`baixar_audio.save_history`) + notificação via `self._notifier.notify(...)` (instância de `PlyerNotifier`). Se `_spotify_pending` for não-None, zera o campo e chama `_agendar_spotify_predialog(pending)`.

- **`_agendar_spotify_predialog(pending)` / `_abrir_spotify_predialog()`:** agendam a abertura do diálogo de pré-publicação para daqui a `_SPOTIFY_PREDIALOG_MS` (800 ms — deixa a notificação de conclusão aparecer antes de um modal roubar o foco). Usa **um timer próprio, filho do `App`** (`_spotify_predialog_timer`, single-shot, criado no `__init__`) em vez de `QTimer.singleShot`, porque um singleShot solto **não pode ser cancelado**: se o usuário fechasse o app dentro dos 800 ms, o timer órfão abria um modal sobre uma janela morta. O `closeEvent` para o timer e limpa `_spotify_predialog_pending`. Um segundo agendamento **substitui** o anterior (nunca enfileira dois diálogos). Ver também a nota sobre `_sem_timers_orfaos` na seção de testes — esse mesmo timer órfão travava a suíte inteira.
- **Spotify — gate de duas condições:** **`_spotify_publish_ready() -> (bool, motivo)`** é o portão único: exige Show ID configurado **e** `self._spotify_session.is_logged_in()`. Consultado em três lugares: o botão do Spotify no card da tela Início (existe se há Show ID, mas fica `setEnabled(False)` com o motivo no tooltip), `_spotify_from_local` (aviso e não abre nada) e `_worker_phase2` (não popula `_spotify_pending` e **registra no log** por que não ofereceu — antes esse desvio era silencioso). O motivo volta sem ponto final e sem dizer onde resolver; quem exibe fecha a frase, porque dentro da própria aba de Spotify mandar "ir em Configurações → Spotify" seria absurdo (`_SPOTIFY_ONDE` é o complemento para os outros contextos).
- **Spotify — conta:** `_refresh_spotify_account()` atualiza status/botão/aviso (chamado no build da aba, em `_open_settings` e após `_cfg_save`, login ou logout). `_spotify_toggle_login()` abre `_SpotifyLoginWindow` ou, se logado, pede confirmação e chama `session.logout()`. **`_cfg_save` preserva `logged_in`**: ele reescreve o dict `spotify` inteiro, e sem essa preservação salvar qualquer configuração deslogaria o usuário.
- **`_SpotifyLoginWindow(QMainWindow)`:** WebView com `session.profile()` (o perfil persistente) na `session.login_url()` — a tela de credenciais, **não** a área autenticada (ver a seção de `session.py`: entrar por lá deixa a janela carregando para sempre). A detecção exige a **transição** `logged_out → logged_in`: `_on_load_finished` apenas reinicia o timer `_assentar_timer` (2500 ms), e `_on_settled` julga a URL já assentada — tela de credenciais marca `_viu_login = True` (e corrige o flag para deslogado), e uma URL interna do Creators **depois disso** conclui o login. Por que tão indireto: a página fica parada numa URL interna enquanto o banner de consentimento de cookies não é resolvido (medido: 20 s), então "estar numa URL interna" não prova sessão. Botão **"Concluí o login"** (`_confirmar_manual`) é a saída para quem já estava logado (nunca vê a tela de credenciais) e para o caso de a Spotify ignorar o `continue`; se clicado à toa, o flag fica errado só até a próxima publicação, que o corrige.
- **`_SpotifyPublishWindow(QMainWindow)`:** WebView na `session.wizard_url(show_id)` (= `https://creators.spotify.com/pod/show/{show_id}/episode/wizard` — o domínio `podcasters` é o antigo). Recebe `session` e passa `session.profile()` para a página, o que evita cair na tela de login. Em `_on_load_finished`: se a página recebida é a de credenciais, **não injeta** (o primeiro input visível ali é o campo de e-mail e receberia o título do episódio) e corrige o flag com `mark_logged_in(False)` — só nessa direção, porque este callback também roda antes de um eventual desvio. Caso contrário injeta `_SPOTIFY_FILL_JS` com as variáveis montadas por **`_build_setup_js(title, description)`**.
- **`_SPOTIFY_FILL_JS` é um observador, não algumas tentativas.** O wizard é uma **SPA**: sair de "Upload" para "Details" não recarrega a página, então `loadFinished` não dispara de novo — e os campos de título/descrição **só existem no segundo passo**. A versão anterior tentava 10 vezes em 6 s, ainda na tela de Upload, desistia, e o episódio subia sem texto (relato de campo: arquivo entrou, título e descrição não). Agora um `MutationObserver` (com debounce de 300 ms) + um timer de 1 s de rede de segurança esperam os campos aparecerem, por até 5 min. Regras: cada campo é preenchido **uma vez** e **só se estiver vazio** (nunca sobrescreve o que o usuário digitou); tudo é registrado via `console.log('[IPMadalena] ...')`, que cai no log do app como linha `js:`.
- **`_SpotifyPage.javaScriptConsoleMessage` é a ponte do log.** **Não confie no encaminhamento padrão do Qt** — medido, ele não imprimiu nem `console.log` nem `console.error`. Um relato de campo chegou sem nenhuma linha `[IPMadalena]` apesar de o script ter rodado (o título tinha sido preenchido), e foi isso que atrasou o diagnóstico. A página agora intercepta as mensagens prefixadas com `[IPMadalena]` e as manda para `_file_log`; o resto (TikTok Pixel, GraphQL do Creators, etc.) segue o caminho padrão.
- **Busca em profundidade + diagnóstico:** `acha(seletor)` tenta o `querySelectorAll` simples e, só se não achar nada, varre shadow DOM e iframes de mesma origem. O seletor de descrição é `[contenteditable]` (sem exigir `="true"`, que o atributo aceita vazio e pode ser herdado) validado por `isContentEditable`; "vazio" ignora espaços, `<br>` e caracteres de largura zero que os editores deixam no campo. Quando o título entra mas a descrição não, após 6 s (`window.__ipmDiagnosticoMs`, reduzido nos testes) o script **relata no log** quantos campos existem e por que cada um foi descartado — sem isso, cada falha vira adivinhação.
- **Dois formatos de campo de descrição:** `textarea` (quando o toggle HTML está ligado) → setter nativo + eventos `input`/`change`; **editor rico** (`[contenteditable="true"]`, o padrão, com barra B/I/U) → `focus()` + `document.execCommand('insertText')`, que gera os eventos que editores tipo Draft.js/ProseMirror esperam — atribuir `textContent` sozinho não basta. No editor rico o texto chega completo, mas o número de linhas em branco entre parágrafos pode variar (o editor cria blocos); por isso o teste compara com as quebras normalizadas.
- **Título:** procura um `input[type=text]` visível e vazio cujo placeholder/aria-label/name/id case com `name|nome|title|título`; sem pista, só arrisca quando há **exatamente um** candidato — chutar entre vários encheria o campo errado.
- **`_build_setup_js` usa `json.dumps`, não escape manual.** O escape anterior tratava só `\` e `'` — e a descrição do YouTube é multi-linha (as reais têm ~25 linhas e emoji). Uma quebra de linha crua dentro de `'...'` invalida o script, ele falha **em silêncio**, e aí NEM o título é preenchido, porque o preenchedor só age se a variável existir. Medido numa página real: com descrição multi-linha as duas chegavam `undefined`; com `json.dumps`, input e textarea são preenchidos com as 25 linhas íntegras. O `ensure_ascii` padrão ainda escapa U+2028/U+2029, válidos em JSON mas quebrados como literal de string em JS antigo.
- **`App._spotify_extras(audio_path) -> (descricao, capa)`:** localiza os artefatos que o downloader gravou **na subpasta** (`descricao.txt`, `capa.jpg`), com fallback para o formato antigo (`<base>.txt`, `<base>.jpg`) e para leitura em cp1252 quando o arquivo não é UTF-8 (melhor descrição com caractere torto do que campo vazio). Usado por `_spotify_from_local` — que antes passava `description=""` fixo e procurava a capa só pelo nome do áudio, então publicar pela tela Início abria sempre sem descrição e sem miniatura — e como fallback em `_show_spotify_predialog`.
- **`_worker_phase2` → `_spotify_pending`:** dict com `show_id`, `video_id`, `title`, `description`, `date_str`, `tags`, `cover_image_path`. Descrição e capa vêm de `descricao.txt` e `capa.jpg` da subpasta do segmento, derivada com **`build_output_names`** (não `sanitize_folder_name` — ver a seção de `ytdlp_source`). `_show_spotify_predialog` localiza o MP3 mais recente em `DOWNLOAD_DIR` (`*.mp3` e `*/*.mp3`) e abre `_SpotifyPrePublishDialog`: modal com título, descrição e tags editáveis; ao confirmar, guarda a janela em `parent_app._spotify_window` (evita GC) e abre `_SpotifyPublishWindow`.
- **`_spotify_top_bar(esquerda, direita) -> QWidget`:** barra das duas janelas do Spotify, com **altura fixa** (`_SPOTIFY_BAR_H = 40`). Não use um `QHBoxLayout` solto aqui: num `QVBoxLayout`, a altura máxima de uma linha aninhada depende dos itens dela e, medido, **muda conforme a ordem** — com o botão (altura fixa) à esquerda e o rótulo (flexível) à direita, a barra da janela de publicação ficava sem limite e comia 503 px de uma janela de 1000 px; com a ordem invertida (janela de login) ficava nos 37 px esperados, ou seja, funcionava por acidente. Os chamadores ainda fazem `layout.addWidget(self._view, 1)` e `layout.setSpacing(0)`, para a sobra ir toda para a página e não sobrar faixa escura entre barra e conteúdo.
- **`_SpotifyPage._make_page(view, audio_path, cover_path, profile)`:** classe interna lazy; sobrescreve `chooseFiles()` para devolver o arquivo certo no lugar do seletor do Windows. O `profile` é opcional: sem ele a página cai no perfil padrão do Qt (off-the-record) e o login se perde.
- **`_spotify_tipo_pedido(accepted)`:** traduz a lista de tipos aceitos em `imagem` / `audio` / `indefinido`. **O `accept` de um `<input>` pode ser MIME (`audio/*`) OU extensão (`.mp3,.m4a,...`), e o QtWebEngine repassa cru, sem normalizar.** O formulário do Spotify usa extensões — medido, chega `['.mp3', '.m4a', '.wav', '.mpg', '.mp4', '.mov']`. A detecção antiga procurava a palavra "audio" nos MIMEs, não casava, e o `chooseFiles` caía no `super()`, abrindo o Explorer: o arquivo não era preenchido sozinho. Regras: imagem é testada primeiro (o passo da capa aceita só imagem, o do episódio aceita áudio **e** vídeo); `indefinido` (accept ausente) cai no áudio, que é o passo obrigatório do wizard. `chooseFiles` registra no log o que entregou — antes o desvio era invisível.
- **Limite do preenchimento automático:** o arquivo só entra quando o usuário clica em "Select a file"; o navegador exige gesto do usuário para abrir o seletor (verificado: `input.click()` via `runJavaScript` não dispara `chooseFiles`). Preencher sem clique algum exigiria injetar os bytes na página (base64 → `File` → `DataTransfer` → evento `drop`) — com MP3 de ~52 MB isso vira uma string JS de ~70 MB, além de depender do handler de drop interno do site.
- **Nota:** `QApplication.setAttribute(AA_ShareOpenGLContexts)` deve ser chamado antes de `QApplication(sys.argv)` para que o `QWebEngineView` funcione no processo principal.
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

Cultos ao vivo podem ser publicados no YouTube com a data do dia seguinte ao evento (o `upload_date` é UTC). Por isso TODAS as fases da busca por data filtram explicitamente por `upload_date ∈ {data_alvo, data_alvo + 1 dia}` — tanto a confirmação da busca rápida quanto a varredura completa (que usa `--dateafter (data - 1 dia)` justamente para o yt-dlp não rejeitar esses vídeos; sem o filtro explícito, todos os vídeos a partir da data seriam retornados).

---

# Testes automatizados

```
tests/
├── conftest.py                ← sys.path + fixture shared_app (sessão)
├── test_domain.py             ← 105 testes puros do domínio
├── test_ytdlp_source.py       ← 160 testes da infra YouTube (subprocess mockado)
├── test_ffmpeg_editor.py      ← 101 testes do FfmpegAudioEditor (subprocess mockado)
├── test_gdrive_storage.py     ← 53 testes do adaptador Drive (HTTP/Drive API mockados)
├── test_zip_archiver.py       ← 17 testes do ZipArchiver (I/O real em tmp_path)
├── test_spotify_session.py    ← 60 testes da SpotifyWebSession (sem Qt e sem rede)
├── test_persistence.py        ← 33 testes dos repositórios JSON (I/O real em tmp_path)
├── test_plyer_notifier.py     ← 10 testes do PlyerNotifier (plyer mockado)
├── test_use_cases.py          ← 57 testes dos use cases (ports mockados)
├── test_presenter.py          ← 58 testes do ProcessingPresenter (use cases mockados)
├── test_audio_test_presenter.py ← 17 testes do AudioTestPresenter
├── test_composition_root.py   ← 32 testes do composition root (DI/wiring)
├── test_baixar_audio.py       ← 38 testes de utilidades + auth wrappers + update_ytdlp
├── test_app.py                ← 397 testes de integração da GUI
├── test_github_updater.py     ← 22 testes do módulo de auto-update (HTTP mockado)
├── test_player_window.py      ← 34 testes do PlayerWindow
└── test_player_window_qt.py   ← 29 testes do PlayerWindowQt
```

**Total: 1223 testes** (~40 s num único processo; `test_app.py` e `test_player_window_qt.py`, que sobem QtWebEngine, respondem pela maior parte).

> O `_reset_app_state` (autouse) devolve a tela Processar ao modo "busca por
> data" e limpa o `link_entry` antes de cada teste — sem isso, um teste que
> muda o modo de entrada contaminaria os seguintes (o `App` é de escopo sessão).

> **`_sem_timers_orfaos` (autouse, `conftest.py`) — por que existe.** O loop de
> eventos do Qt **não roda** durante os testes (ninguém chama `app.exec()`),
> então um `QTimer` armado por um teste fica pendente. Quando um teste posterior
> cria janela Tcl/Tk, o `customtkinter` chama `self.update()` internamente (ao
> ajustar a cor da barra de título) e o Tcl **pompa a fila de mensagens do
> Windows** — e com ela os timers do Qt. O callback atrasado dispara ali dentro,
> fora do teste que o criou. Foi assim que a suíte inteira travava para sempre
> em `test_player_window.py`: um teste de `_on_done` deixava pendente o timer do
> diálogo de pré-publicação do Spotify, que abria um modal (`exec()`) dentro do
> `update()` do Tk, sem ninguém para fechá-lo. A fixture desarma, ao fim de cada
> teste, os timers de **disparo único** que ficaram ativos nos widgets de topo;
> os repetitivos (ex.: `_queue_timer`) são estado normal e continuam rodando.
> Por isso `_spotify_predialog_timer` é filho do `App` e single-shot — é o que o
> torna visível a `findChildren` e, portanto, à rede de segurança.

> **Watchdog (`pytest.ini`).** `faulthandler_timeout = 60` +
> `faulthandler_exit_on_timeout` fazem o pytest dumpar a pilha de todas as
> threads e encerrar quando um teste passa de 60 s. É o que faltava no episódio
> acima: a suíte parava em ~65 % **sem diagnóstico nenhum**. O teste mais lento
> hoje leva ~8 s, então 60 s é folga larga — quem estourar está travado, não
> lento. Para descobrir onde travou, a pilha vai para o stderr; ao rodar em
> shell não-interativo, redirecione o stderr para arquivo (senão a saída
> bufferizada se perde quando o processo morre).

> **Spotify nos testes:** o helper `_spotify_logado(app, bool)` (context manager
> em `test_app.py`) finge o estado de login. Como a publicação exige DUAS
> condições, um teste que só configura o `show_id` não passa mais pelo gate.
> As janelas do Spotify NÃO são instanciadas nos testes — construí-las abriria
> um `QWebEngineView` e faria requisição de rede; a lógica é exercitada
> chamando os métodos com um stub que carrega só os atributos que eles tocam
> (`TestSpotifyLoginWindowLogic`, `TestSpotifyPublishWindowGate`).

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

**IMPORTANTE 2 — não quebrar `if exist` com `^`.** O caret escapa o fim de linha e o `cmd` passa a ler os espaços da linha seguinte como comando (`' ' não é reconhecido...`), deixando a variável vazia. Era assim que a detecção do Inno Setup estava escrita: o passo 4 pulava **sempre**, alegando que o Inno Setup não estava instalado (corrigido em 13/08/2026 — cada `if exist ... set ...` numa única linha).

**Rodando o `.bat` em shell não-interativo:** ele termina com `pause` (e usa `pause & exit /b` nos erros). Redirecione o stdin de `nul`, senão a execução fica pendurada:
```powershell
cmd /c '"<raiz>\build_installer.bat" < nul'
```

**Comandos manuais (se o `.bat` falhar) — caminhos desta máquina:**
```powershell
& "C:\Users\rasantos\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller build_app.spec --noconfirm --clean
& "C:\Users\rasantos\AppData\Local\Programs\Inno Setup 6\ISCC.exe" "C:\Users\rasantos\PythonProjects\youtube-to-drive-ipmadalena\installer.iss"
```
> O PyInstaller leva ~5 min e o Inno Setup ~6 min (o instalador tem ~239 MB). Rode em background e acompanhe a saída em arquivo.

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

# Processo de criação de novo release

> **Trigger:** quando o usuário informar "Gere um novo release" (com ou sem número de versão), executar este processo do início ao fim.

## Passo 1 — Confirmar a nova versão

Se o usuário não especificou a versão, perguntar: `"Qual será o número da nova versão? (ex: v3.3.0)"`.

A versão segue **semver**: `vMAJOR.MINOR.PATCH`
- `PATCH` → bug fixes, ajustes menores
- `MINOR` → nova funcionalidade sem quebrar compatibilidade
- `MAJOR` → mudança incompatível ou redesign significativo

## Passo 2 — Garantir testes 100% verdes

```bash
python -m pytest tests/ -q
```

Não prosseguir se houver falhas. Corrigir antes de continuar.

## Passo 3 — Atualizar a versão em `app.py` e no `installer.iss`

Localizar e atualizar as duas linhas:

```python
APP_VERSION = "vX.Y.Z"   # app.py — sidebar, rodapé e auto-update
```

```
#define AppVersion   "X.Y.Z"   ; installer.iss — sem o "v"
```

## Passo 4 — Atualizar documentação

- **`CLAUDE.md`** — atualizar qualquer referência à versão anterior (ex: contagem de testes, se mudou)
- **`README.md`** — idem

## Passo 5 — Commit do release

```bash
git add app.py CLAUDE.md README.md
git commit -m "chore: bump version to vX.Y.Z"
git push
```

## Passo 6 — Criar a tag Git e push

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

## Passo 7 — Gerar o instalador

```bash
build_installer.bat
```

Em shell não-interativo, redirecionar o stdin (o bat termina com `pause`):

```powershell
cmd /c '"C:\Users\rasantos\PythonProjects\youtube-to-drive-ipmadalena\build_installer.bat" < nul'
```

Caso o `.bat` falhe, usar os comandos manuais (ver a seção `build_installer.bat` para os caminhos e tempos esperados).

O instalador gerado estará em `dist\IPMadalena_Setup.exe`. **Conferir a versão antes de publicar** — o `dist/` guarda o build anterior e é fácil subir o exe errado:

```powershell
(Get-Item "dist\IPMadalena_Setup.exe").VersionInfo.ProductVersion   # deve ser X.Y.Z
```

## Passo 8 — Criar o release no GitHub

```bash
gh release create vX.Y.Z dist/IPMadalena_Setup.exe \
  --title "IPMadalena vX.Y.Z" \
  --notes "$(cat <<'EOF'
## O que há de novo

- <descrever as principais mudanças desta versão>

## Download

Baixe o instalador `IPMadalena_Setup.exe` abaixo e execute-o para instalar ou atualizar.
EOF
)"
```

O asset `IPMadalena_Setup.exe` fica anexado ao release e é o arquivo que o auto-update do app baixa automaticamente.

> **O texto do `--notes` é lido pelo usuário final.** O corpo do release é exibido, renderizado em
> Markdown, dentro do aviso de nova versão que abre na inicialização do app
> (`_UpdateAvailableDialog`). Escreva "O que há de novo" pensando em quem vai decidir se atualiza —
> nada de "vários ajustes". Um release publicado sem descrição faz o aviso aparecer só com o número
> da versão.

## Checklist resumido

| Etapa | Comando / Ação |
|---|---|
| ✅ Testes 100% | `python -m pytest tests/ -q` |
| ✅ Bumpar versão | `APP_VERSION` em `app.py` **e** `AppVersion` em `installer.iss` |
| ✅ Atualizar docs | `CLAUDE.md`, `README.md` |
| ✅ Commit + push | `git commit` → `git push` |
| ✅ Tag + push | `git tag vX.Y.Z` → `git push origin vX.Y.Z` |
| ✅ Gerar instalador | `build_installer.bat` → `dist/IPMadalena_Setup.exe` |
| ✅ Release no GitHub | `gh release create vX.Y.Z dist/IPMadalena_Setup.exe ...` |

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
- Busca por data lenta (~19 s até para a data mais recente; minutos para datas antigas) → a extração completa por vídeo + enumeração total da aba dominavam o tempo. Resolvido com busca em duas fases (flat playlist com `youtubetab:approximate_date` → confirmação só dos candidatos) e fallback para a varredura original. Medições e janelas de tolerância documentadas em `ytdlp_source.py`.
- `build_installer.bat` sempre pulava o passo 4 ("Inno Setup nao encontrado", mesmo instalado) → os `if exist` da detecção estavam quebrados em duas linhas com `^`; o caret escapa o fim de linha e o `cmd` lê os espaços da linha seguinte como comando, deixando `ISCC` vazio. Corrigido pondo cada teste numa única linha. Era por isso que o release exigia rodar o `ISCC.exe` à mão.
- Suíte de testes travando para sempre em ~65 % (primeira janela `CTkToplevel` de `test_player_window.py`) → **não** era incompatibilidade Qt × tkinter. Um teste de `_on_done` armava o `QTimer.singleShot(800, …)` real do diálogo de pré-publicação do Spotify: a lambda resolve `self._show_spotify_predialog` **na hora de disparar**, quando o `patch.object` do teste já foi desfeito. O timer órfão sobrevivia ao teste e disparava dentro do `update()` do Tcl/Tk (que pompa a fila de mensagens do Windows), abrindo um modal `exec()` que nunca retornava. Corrigido em três camadas: (1) `_agendar_spotify_predialog` usa timer próprio, filho do `App`, cancelado no `closeEvent` — o que também conserta o caso real de o diálogo abrir depois de o app fechar; (2) o teste passou a disparar o callback à mão em vez de deixar o timer armado; (3) rede de segurança `_sem_timers_orfaos` + watchdog do `pytest.ini`. Diagnóstico só foi possível com `faulthandler.dump_traceback_later(..., exit=True)` escrevendo num arquivo dedicado.
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
- `YtDlpAudioDownloader.download()` retornava arquivos errados (glob promíscuo) → fluxo MP4-first com subpasta por segmento; caminho do MP4 capturado de `[Merger]` > `[download] Destination: *.mp4` > glob dentro da subpasta; preserva ordem dos segments e `video_id` do Segment original.
- Barra de upload ciclava 0→100 % por arquivo quando subpasta continha MP3 + capa.jpg + descricao.txt → `_norm_progress` em `GoogleDriveStorage.upload()` distribui o intervalo 0–100 igualmente entre todos os arquivos do lote: `int((_i - 1 + pct / 100) / _n * 100)`.
- `ERROR: Cannot write video description file ...` + `yt-dlp encerrou com código 1` em títulos longos → caminho passava dos 260 chars do Windows (`MAX_PATH`); o template `%(title)s` repetia o título dentro da subpasta já nomeada com ele. Resolvido com `build_output_names()` (orçamento de caminho). Alternativa de sistema, **não usada**: `LongPathsEnabled=1` no registro — depende de cada executável declarar `longPathAware` no manifesto, e o yt-dlp.exe empacotado não garante isso.
- Texto de labels (hints, títulos de card) e `QCheckBox` apareciam com fundo mais escuro que o card → raiz: `QWidget { background-color: #1e1e1e; }` no QSS global forçava `autoFillBackground=True` em **todos** os widgets. Dentro de cards com fundo `#222222`, esses widgets pintavam `#1e1e1e` por cima. Solução: removido `background-color` da regra `QMainWindow, QWidget { … }` (mantido só `color` e `font`); adicionado `QMainWindow { background-color: … }` isoladamente; `QLabel { color: … }` sem regra de background. QPalette dark/light setada via `_build_palette(dark)` no startup e em `_toggle_theme` para que controles Fusion-style continuem com cores corretas. Corrigido também `_on_upload_toggle`: quando `checked=True`, usar `card.setGraphicsEffect(None)` em vez de opacity=1.0 — mesmo opacity=1.0 ativa rendering off-screen que causava artefatos de compositing em filhos com background transparente.
