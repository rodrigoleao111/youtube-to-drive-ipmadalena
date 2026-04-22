# IPMadalena — YouTube to Drive

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
├── app.py                   ← interface gráfica (customtkinter)
├── baixar_audio.py          ← módulo principal (lógica + CLI)
├── historico.json           ← datas já processadas (gerado em runtime)
├── credentials/
│   ├── client_secret.json   ← credenciais OAuth do Google
│   └── token.pkl            ← token salvo (gerado na 1ª execução)
├── downloads/               ← pasta temporária, limpa após upload
├── logs/DD-MM-YYYY.log      ← log diário (gerado em runtime)
└── ffmpeg/bin/ffmpeg.exe    ← conversor local de áudio
```

## Dependências Python

```
yt-dlp
google-api-python-client
google-auth-oauthlib
customtkinter
tkcalendar
plyer
```

## Detalhes técnicos — baixar_audio.py

- **Python:** `C:\Users\rasantos\AppData\Local\Programs\Python\Python312\python.exe`
- **yt-dlp:** usa `--dateafter` + `--break-on-reject` para parar a varredura ao passar da data alvo (o canal tem ~1300 vídeos — sem isso varre tudo); `--socket-timeout 30` em todos os comandos
- **Listagem:** `--simulate --print "%(id)s|||%(title)s|||%(upload_date)s"` — varre sem baixar; após coletar, filtra por `upload_date == data_alvo` ou `upload_date == data_alvo + 1 dia` (lives publicadas com data posterior ao culto)
- **Download:** URLs individuais por ID (`https://www.youtube.com/watch?v=<id>`); player_client `ios,android,web` — `tv_embedded` foi descontinuado pelo YouTube e não deve ser usado
- **Encoding do subprocess:** `_start_process()` injeta `PYTHONUTF8=1` e `PYTHONIOENCODING=utf-8` no ambiente do subprocesso para garantir que o yt-dlp escreva UTF-8 no stdout (o padrão Windows é cp1252, o que corromperia acentos)
- **ffmpeg** instalado localmente em `ffmpeg/bin/`, referenciado via `--ffmpeg-location`
- **Google Drive API v3** com OAuth2; token salvo em `credentials/token.pkl`
- **Token corrompido:** `get_drive_service()` captura exceção no `pickle.load()`, remove o arquivo e força reautenticação; idem para falha no refresh
- **Pasta raiz no Drive:** `1KfsI5zCDL4HZ2pdAWPFfAD3TugplzBez`
- **Subpasta do mês:** localizada por nome fuzzy (aceita `Abril-2026`, `Abril 2026`, `Abr/2026`); se não encontrar, cria automaticamente
- **Upload:** `AuthorizedSession` (google-auth / requests) + streaming via `_ProgressFile`; verificação de duplicatas antes de enviar
- **`_ProgressFile`:** wrapper de arquivo com três responsabilidades separadas:
  - Cancelamento verificado a cada `read()` (~65 KB) → resposta < 100 ms
  - Label de stats na GUI atualizado a cada 1 MB (taxa instantânea do último chunk)
  - Log de texto apenas nos marcos 25 %, 50 % e 75 % (taxa média acumulada) + linha final com taxa média total
  - Expõe `average_rate_mbps()` para o log de conclusão em `upload_to_drive()`
- **Histórico:** `historico.json` — `{date_str: {processado_em, videos: [...]}}` — gerenciado por `load_history()` / `save_history()`
- **Utilitários de robustez:** `check_internet()`, `check_disk_space(min_mb=500)`, `cleanup_downloads()`, `update_ytdlp()`

## Detalhes técnicos — app.py

- **Framework:** `customtkinter` (dark mode) + `tkcalendar` para popup de calendário
- **Thread safety:** `queue.Queue` para comunicação worker→GUI; polling com `self.after(100, _process_queue)`
- **Cancelamento:** `threading.Event` passado a todas as fases; watchdog daemon termina o subprocess; `_check_cancel()` no loop de leitura do stdout
- **Barras de progresso:** `progress_color=fg_color` para ocultar sem remover do layout; restauradas ao iniciar
  - Upload: barra larga (progresso byte a byte via streaming)
  - Etapas: barra estreita (148px), avança por status keywords via `SUBTASK_PROGRESS`
- **Instância única:** porta TCP 47892 reservada via `_acquire_single_instance()`; segunda instância exibe alerta e encerra
- **Log em arquivo:** `logs/DD-MM-YYYY.log` via `logging.basicConfig`; todo log/status/erro é gravado
- **Fluxo de execução:**
  1. `_worker_preflight` — verifica internet, disco, limpa resíduos, consulta histórico
  2. Popup de aviso se data já foi processada (pode continuar mesmo assim)
  3. `_worker` — `list_videos()` (fase 1, sem download)
  4. Popup de seleção de vídeos (checkboxes, todos marcados por padrão)
  5. `_worker_phase2` — `download_selected()` + `upload_files()`
  6. `_on_done()` — salva histórico + notificação desktop via `plyer`
- **Auto-update yt-dlp:** thread daemon roda `update_ytdlp()` ao iniciar o app

## Comportamento especial — transmissões ao vivo

Cultos ao vivo podem ser publicados no YouTube com a data do dia seguinte ao evento. O script usa `--dateafter (data - 1 dia)` para garantir que o yt-dlp não rejeite esses vídeos, e depois filtra explicitamente por `upload_date ∈ {data_alvo, data_alvo + 1 dia}` — sem esse filtro, todos os vídeos a partir da data seriam retornados.

## Testes automatizados

```
tests/
├── conftest.py              ← adiciona raiz do projeto ao sys.path
├── test_baixar_audio.py     ← 30 testes unitários do módulo principal
└── test_app.py              ← 36 testes de integração da GUI
```

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
- `get_drive_service` com token corrompido (verifica log + reauth forçado)
- `--socket-timeout 30`, `--dateafter`, `--break-on-reject` nos comandos yt-dlp
- Instância única (mock de socket)
- Processamento de todos os tipos de mensagem da fila (`log`, `status`, `progress`, `done`, `cancelled`, `error`, `preflight_error`, `history_warning`)
- `_worker_preflight`: sem internet, disco insuficiente, data já processada, tudo OK
- `_on_done`: salva histórico, notificação desktop (mock plyer), estado idle
- Cancelamento: sinaliza evento, desabilita botão, oculta barras
- Validação de data: vazia, formato errado, formato correto
- Log em arquivo: criado na pasta `logs/`, nome com data de hoje, entrada de início

**O que NÃO é testado automaticamente** (requer execução manual):
- Fluxo real com YouTube (rede + canal ativo)
- Popup de seleção de vídeos (interação humana)
- Upload real para o Drive (credenciais ativas)
- Notificação desktop visível na bandeja

**Notas de implementação:**
- Mocks via `unittest.mock` (biblioteca padrão, sem dependências extras)
- App GUI testado instanciando `App()` real com `withdraw()` — requer display (Windows OK)
- `patch('plyer.notification.notify')` direto — evita `patch.dict(sys.modules)` que corrompe o estado Tcl entre testes
- `MagicMock` não é serializável via pickle → usar `patch('pickle.dump')` nos testes de token

---

## Versionamento

- **Repositório:** [https://github.com/rodrigoleao111/youtube-to-drive-ipmadalena](https://github.com/rodrigoleao111/youtube-to-drive-ipmadalena)
- **Visibilidade:** público
- **Branch principal:** `main`
- **Git config:** `user.name = Rodrigo Augusto Leão dos Santos` / `user.email = rodrigoleao1995@gmail.com`

**Arquivos ignorados via `.gitignore`** (não commitar):
- `credentials/client_secret.json` e `credentials/token.pkl` — credenciais OAuth sensíveis
- `downloads/` — pasta temporária de áudios
- `logs/` — logs locais de execução
- `historico.json` — estado local de datas processadas
- `ffmpeg/` — binário grande; instalar localmente conforme `CONFIGURACAO.md`

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
