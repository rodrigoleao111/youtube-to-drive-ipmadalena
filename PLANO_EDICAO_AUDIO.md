# Plano de Integração — Edição de Áudio (v3.0.0)

Documento que detalha a próxima grande melhoria do IPMadalena: produzir, ao final do fluxo de seleção de trecho, um arquivo MP3 **pronto para ser publicado como podcast** — com vinhetas de entrada/saída, fade in/out, equalização padrão e redução de ruído.

> Status: **planejado**, ainda não iniciado. Aprovado pelo usuário em 01/05/2026.

---

## Objetivo final

Após o usuário marcar o trecho de um vídeo, o pipeline deve:

```
Trecho baixado (.mp3 cru)
    ↓ redução de ruído  (afftdn)
    ↓ equalização       (5 bandas paramétricas)
    ↓ fade in/out       (afade)
    ↓ concat com vinhetas de entrada/saída
Arquivo final (.mp3) substitui o original em downloads/  →  Upload para o Drive
```

Tudo isso **configurável** pelo usuário em uma nova subpágina da tela de configurações.

---

## Decisões já tomadas

1. **Stack técnico:** ffmpeg para tudo (já empacotado). Sem dependência nova pesada.
2. **Onde o áudio editado é salvo:** **substitui** o original em `downloads/`. O Drive recebe o arquivo final.
3. **Vinhetas:** o usuário seleciona um arquivo de áudio do disco; o app **copia** para `assets/vinhetas/` (mesma pasta do app, sobrevive a renomeações). Sobreposição entre vinheta e áudio configurável em segundos.
4. **Preview em si das vinhetas:** botão `▶ Tocar` ao lado de cada uma, usando `QMediaPlayer` (`PyQt6.QtMultimedia`).
5. **Editor de EQ:** **5 sliders fixos** em frequências pré-definidas (estilo Hi-Fi):
   - 80 Hz · 250 Hz · 1 kHz · 4 kHz · 10 kHz
   - Faixa de cada slider: **-12 dB a +12 dB**
6. **Preset padrão "Voz Masculina"** (clareza em pregação):
   ```
    80 Hz: -3 dB   (corta rumble e boom)
   250 Hz: -2 dB   (reduz a "lama" típica do registro masculino)
     1 kHz:  0 dB   (referência neutra)
     4 kHz: +3 dB   (presença/inteligibilidade dos consoantes)
    10 kHz: +1 dB   (leve "ar")
   ```
7. **Sem preview do pipeline completo** — só o play das vinhetas. Adiciona depois se for útil.
8. **UI da tela de configurações** vira sidebar com **2 subpáginas**: "Configurações Gerais" (atual) + "Configurações de Áudio" (nova).

---

## Regras de implementação (aplicáveis a todos os PRs)

1. **Log da GUI por etapa do pipeline** — cada filtro aplicado emite uma linha no log box do app via `on_log`:
   - `Aplicando redução de ruído...`
   - `Aplicando equalização...`
   - `Aplicando fade in/out...`
   - `Concatenando vinhetas...`
   Não basta uma linha "Editando áudio" — o usuário precisa enxergar progresso em arquivos longos (1h+).

2. **Mensagens de debug no terminal Python** — `print("[DEBUG audio_edit] ...", file=sys.stderr)` em pontos-chave do `FfmpegAudioEditor` e do `EditAudioUseCase`. Útil quando o app é rodado pelo launcher do Python no desenvolvimento. Pode virar `logging.debug` num polish PR depois.

3. **Cancelamento** — todos os subprocessos ffmpeg respondem a `cancel_event` via o mesmo `start_process()` / `check_cancel()` já usados pelo yt-dlp.

4. **Arquitetura preservada** — Clean Architecture do projeto continua intacta:
   - Entidades imutáveis em `domain/`
   - Protocols em `domain/ports.py`
   - Implementação ffmpeg em `infrastructure/audio/`
   - Use case em `application/use_cases.py`
   - Wiring em `composition_root.py`

---

## Cronologia (7 PRs)

| PR | Título | Visível ao usuário? | Risco |
|----|--------|---------------------|-------|
| 1 | Domínio + persistência | Não | Baixo |
| 2 | Adaptador ffmpeg (`FfmpegAudioEditor`) | Não | Médio |
| 3 | Use case + integração no pipeline | Não | Médio |
| 4 | Refatoração da `SettingsWindow` em duas subpáginas | Sim (estrutural) | Baixo |
| 5 | UI da página "Configurações de Áudio" | Sim | Médio |
| 6 | Gerenciamento dos assets de vinheta | Sim | Baixo |
| 7 | Teste de configuração de áudio (preview com arquivo de exemplo) | Sim | Médio |

PRs 1–3 são **invisíveis** ao usuário (mudam o domínio, infra e pipeline mas não há UI ainda). Mergeáveis sem medo.
PR 4 isola o risco da reestruturação da tela atual em uma mudança puramente estrutural (zero comportamento novo).
PR 5 é onde tudo aparece para o usuário.
PR 6 fecha o ciclo (vinhetas funcionais ponta a ponta).
PR 7 adiciona o card de teste — usuário consegue conferir o resultado antes de salvar e antes de processar um culto inteiro.

---

## PR 1 — Domínio + persistência

**Objetivo:** ter a configuração persistível no `config.json`, sem nenhum efeito no fluxo existente.

| Arquivo | Mudança |
|---|---|
| `domain/entities.py` | + `EqBand(freq_hz: int, gain_db: float)` (frozen). + `AudioEditConfig` (frozen): `intro_path`, `outro_path`, `intro_overlap_secs`, `outro_overlap_secs`, `fade_in_enabled`, `fade_in_secs`, `fade_out_enabled`, `fade_out_secs`, `eq_enabled`, `eq_bands: tuple[EqBand, ...]`, `noise_reduction_enabled`, `noise_reduction_intensity` (`"baixa"\|"media"\|"alta"`). |
| `domain/audio_presets.py` (novo) | Constantes: `EQ_FREQS = (80, 250, 1000, 4000, 10000)` e `EQ_PRESET_VOZ_MASCULINA`. |
| `domain/ports.py` | + `IAudioEditor` (Protocol): `process(audio: AudioFile, config: AudioEditConfig, *, on_log, on_progress, cancel_event) -> AudioFile`. |
| `infrastructure/persistence/json_repositories.py` | `JsonConfigRepository` ganha chave `"audio_edit"`. `load()` aplica defaults seguros (tudo desligado, exceto preset salvo). Backwards compatibility: `config.json` sem a chave funciona. |

**Testes:**
- `tests/test_domain.py` — validação dos campos, frozen, defaults do preset.
- `tests/test_persistence.py` — round-trip de `audio_edit` no `config.json`; defaults aplicados em arquivo legado sem a chave.

---

## PR 2 — Adaptador ffmpeg (`FfmpegAudioEditor`)

**Objetivo:** implementar `IAudioEditor` aceitando `AudioEditConfig` e devolvendo `AudioFile` editado, substituindo o original em `downloads/`.

| Arquivo | Mudança |
|---|---|
| `infrastructure/audio/__init__.py` | novo |
| `infrastructure/audio/ffmpeg_editor.py` | `FfmpegAudioEditor` — monta filter graph: `afftdn=nr={10\|17\|25}` (baixa/média/alta) → `equalizer=f=80:t=q:w=1:g=-3 → equalizer=...×5` → `afade=t=in:st=0:d=N` → `afade=t=out:st=END-N:d=N`. Concat de intro/outro como filter graph separado quando há paths. Saída em `.mp3.tmp` → `os.replace()` para o caminho original (atômico). |

**Pipeline ffmpeg:**

```
ffmpeg -i input.mp3 \
       [-i intro.mp3 -i outro.mp3] \
       -filter_complex "
           [0:a] afftdn=nr=17,
                 equalizer=f=80:t=q:w=1.0:g=-3,
                 equalizer=f=250:t=q:w=1.0:g=-2,
                 equalizer=f=1000:t=q:w=1.0:g=0,
                 equalizer=f=4000:t=q:w=1.0:g=3,
                 equalizer=f=10000:t=q:w=1.0:g=1,
                 afade=t=in:st=0:d=2,
                 afade=t=out:st=DURATION-3:d=3 [main];
           [1:a] aresample=44100 [intro];
           [2:a] aresample=44100 [outro];
           [intro][main][outro] concat=n=3:v=0:a=1 [out]
       " \
       -map "[out]" -c:a libmp3lame -q:a 2 \
       -progress pipe:1 \
       output.mp3.tmp
```

**Pontos cuidadosos:**
- `aresample=44100` no concat força sample rate único (vinheta 44.1k + áudio 48k é bug comum).
- `afftdn` é o filtro mais lento → progresso reportado por linha `out_time_us=` que ffmpeg emite com `-progress pipe:1`.
- Cancelamento via `check_cancel()` no loop de stdout, igual ao yt-dlp.
- `BASE_DIR` para localizar o ffmpeg empacotado (mesma lógica do `infrastructure/youtube/_utils.py`).

**Logs (regra 1):** uma linha por etapa, emitidas via `on_log` antes do início de cada bloco lógico:
- `[Edição] Aplicando redução de ruído (intensidade: média)...`
- `[Edição] Aplicando equalização (5 bandas)...`
- `[Edição] Aplicando fade in (2.0 s) e fade out (3.0 s)...`
- `[Edição] Concatenando vinhetas (intro: 1.5 s, outro: 2.0 s)...`
- `[Edição] Concluído.`

**Debug (regra 2):** `print("[DEBUG audio_edit] ffmpeg cmd: ...", file=sys.stderr)` antes do Popen; `print` do filter graph montado; `print` quando `os.replace` finaliza.

**Testes:**
- `tests/test_ffmpeg_editor.py` — Mock `subprocess.Popen`, capturar a string `-filter_complex` e validar:
  - Ordem dos filtros: denoise → EQ → fade → concat
  - 5 bandas de EQ com freqs corretas
  - `aresample=44100` presente quando há vinhetas
  - No-op rápido (sem chamar Popen) quando todos os toggles estão desligados
  - Parsing correto do progresso (`out_time_us` → 0.0–1.0)
  - Cancelamento mata o subprocess corretamente

---

## PR 3 — Use case + integração no pipeline

**Objetivo:** áudio editado entra no fluxo entre download e upload, **lendo a config do `IConfigRepository`**.

| Arquivo | Mudança |
|---|---|
| `application/use_cases.py` | + `EditAudioUseCase(editor: IAudioEditor, config_repo: IConfigRepository)`. Lê config; se nada está habilitado, retorna o `AudioFile` sem chamar o editor (no-op rápido, log "edição desabilitada — pulando"). |
| `presentation/processing_presenter.py` | `process_segments` ganha um passo entre download e upload. Novo callback `on_edit_progress`. |
| `composition_root.py` | Wira `FfmpegAudioEditor` + `EditAudioUseCase`. |
| `app.py` | Aproveita a barra de **Conversão** existente (que hoje só anima até 90%) para representar progresso real da edição quando habilitada — sem nova barra. |

**Testes:**
- `tests/test_use_cases.py` — `EditAudioUseCase` chama `editor.process()` com o config certo; pula edição quando tudo está desligado.
- `tests/test_presenter.py` — `process_segments` invoca o use case de edição entre download e upload.
- `tests/test_composition_root.py` — `build_processing_presenter()` retorna um presenter com o use case de edição configurado.

---

## PR 4 — Refatoração da `SettingsWindow` em duas subpáginas

**Objetivo:** **só estrutural** — quebra a tela de configurações em sidebar com 2 itens; aba de áudio fica placeholder vazio. **Zero mudança de comportamento.**

| Arquivo | Mudança |
|---|---|
| `app.py` (`SettingsWindow`) | Layout vira `QHBoxLayout`: sidebar fina à esquerda com 2 botões `nav_btn` (mesmo estilo da sidebar da janela principal), `QStackedWidget` à direita. Página "Configurações Gerais" = todo o conteúdo atual. Página "Configurações de Áudio" = `QLabel("Em breve")` (substituído no PR 5). |

**Testes:**
- `tests/test_app.py` — verifica que ambos os itens da sidebar existem e que clicar troca o `currentIndex` do stack.

---

## PR 5 — UI da página "Configurações de Áudio"

**Objetivo:** os controles funcionais.

**Layout** da página, dividido em 4 seções (cards):

```
┌── Vinhetas ─────────────────────────────────────┐
│ Vinheta de entrada                              │
│  [▸ Selecionar arquivo]  intro.mp3  [▶][🗑]    │
│  Sobreposição com áudio: [== 0.0 ==] s          │
│                                                  │
│ Vinheta de saída                                │
│  [▸ Selecionar arquivo]  outro.mp3  [▶][🗑]    │
│  Sobreposição com áudio: [== 0.0 ==] s          │
└─────────────────────────────────────────────────┘

┌── Fade ─────────────────────────────────────────┐
│ ☑ Fade in   Duração: [== 2.0 ==] s              │
│ ☑ Fade out  Duração: [== 3.0 ==] s              │
└─────────────────────────────────────────────────┘

┌── Equalização ──────────────────────────────────┐
│ ☑ Aplicar EQ                                    │
│ Preset: [Voz Masculina ▾ | Personalizado]       │
│                                                  │
│  +12┌─┐  ┌─┐  ┌─┐  ┌─┐  ┌─┐                    │
│     │ │  │ │  │●│  │ │  │ │                    │
│     │ │  │ │  │ │  │●│  │ │                    │
│     │●│  │●│  │ │  │ │  │●│   ← sliders        │
│     │ │  │ │  │ │  │ │  │ │                    │
│  -12└─┘  └─┘  └─┘  └─┘  └─┘                    │
│      80   250   1k   4k   10k Hz                │
│      -3   -2     0   +3   +1  dB (label)        │
│                                                  │
│  [Restaurar padrão Voz Masculina]               │
└─────────────────────────────────────────────────┘

┌── Redução de ruído ─────────────────────────────┐
│ ☑ Ativar                                        │
│ Intensidade: ○ Baixa  ● Média  ○ Alta           │
└─────────────────────────────────────────────────┘

[Cancelar]                              [Salvar]
```

| Arquivo | Mudança |
|---|---|
| `app.py` | Página com 4 seções (cards) na ordem acima. Sliders de fade em segundos (0.0–10.0). Cada vinheta tem: caminho exibido (truncado), botão `Selecionar`, botão `▶ Tocar` (usa `QMediaPlayer` do `PyQt6.QtMultimedia`), botão `Remover`. EQ: 5 sliders verticais agrupados horizontalmente, label da freq embaixo (80/250/1k/4k/10k), valor em dB acima (-12 a +12). Combo `Preset`: ao mexer slider, muda automaticamente para "Personalizado". Botão `Restaurar padrão Voz Masculina` reverte. |

**Detalhes do botão Play das vinhetas:**
- `QMediaPlayer` + `QAudioOutput` (PyQt6.QtMultimedia).
- Toca o arquivo da vinheta carregada.
- Estado do botão alterna `▶ Tocar` ↔ `■ Parar`.
- Para se a janela é fechada ou se outro play é clicado.

**Testes:**
- `tests/test_app.py` — smoke tests: abrir a aba, validar que `_save` escreve via `IConfigRepository` com os valores certos. Mock do `QMediaPlayer`.

---

## PR 6 — Gerenciamento dos assets de vinheta

**Objetivo:** copiar a vinheta selecionada para `assets/vinhetas/intro.{ext}` (ou `outro.{ext}`); apagar o anterior; sobreviver a frozen vs script via `BASE_DIR`.

| Arquivo | Mudança |
|---|---|
| `baixar_audio.py` | + `VINHETAS_DIR = os.path.join(BASE_DIR, "assets", "vinhetas")`. |
| `app.py` | No "Selecionar arquivo": copia para `VINHETAS_DIR/intro.{ext}` (mantém extensão original — ffmpeg lê tudo), persiste o caminho final. No "Remover": apaga o arquivo. Cria `VINHETAS_DIR` se não existir. |
| `installer.iss` | + linha pra preservar `assets/vinhetas/` na desinstalação (igual a `credentials/`). |
| `.gitignore` | + `assets/vinhetas/`. |

**Testes:**
- `tests/test_app.py` — `tmp_path` monkeypatchando `VINHETAS_DIR`. Verifica copy + overwrite (substituir vinheta) + remove.

---

## PR 7 — Teste de configuração de áudio (preview com arquivo de exemplo)

**Objetivo:** o usuário seleciona um arquivo de áudio qualquer do disco, o app aplica a configuração **que está na tela** (não precisa salvar antes) e gera um arquivo de preview que o usuário pode tocar — confirmando o resultado antes de processar um culto inteiro.

**Card adicional na página de Configurações de Áudio**, antes dos botões `Cancelar`/`Salvar`:

```
┌── Teste de configuração ────────────────────────┐
│ Aplique a configuração atual em um áudio de     │
│ exemplo para conferir o resultado antes de      │
│ salvar e usar em produção.                      │
│                                                  │
│ Arquivo de exemplo:                             │
│  [▸ Selecionar arquivo]  exemplo_pregacao.mp3   │
│                                                  │
│  [▷ Gerar preview]  [▶ Tocar]  [🗑 Limpar]     │
│                                                  │
│  [██████████████░░░░░░░░░░░░░░] 64%             │
│  Status: Aplicando equalização (5 bandas)...    │
└─────────────────────────────────────────────────┘
```

| Arquivo | Mudança |
|---|---|
| `app.py` | Novo card na página de áudio. Picker de arquivo via `QFileDialog` (filtros: mp3/m4a/wav/ogg). Botão `Gerar preview` constrói um `AudioEditConfig` **a partir do estado atual da UI (não do `IConfigRepository`)** — assim o usuário testa sem precisar salvar. Roda `FfmpegAudioEditor.process()` em `QThread` para não travar a UI. Output em `downloads/_test_preview.mp3`. Barra de progresso e label de status dentro do próprio card (não a barra principal do app). Botão `▶ Tocar` reutiliza o `QMediaPlayer` das vinhetas. Botão `Limpar` apaga o preview e o arquivo de exemplo selecionado. |
| `presentation/audio_test_presenter.py` (novo) | `AudioTestPresenter` — orquestra a leitura do estado da UI → constrói `AudioEditConfig` → chama o `FfmpegAudioEditor` → emite callbacks de progresso/log/conclusão. Mantém a página de UI livre de lógica de domínio. |
| `composition_root.py` | + `build_audio_test_presenter()` — recebe um `IAudioEditor` e devolve um `AudioTestPresenter`. |

**Reaproveitamento:**
- O **mesmo** `FfmpegAudioEditor` do PR 2 é usado — não há código novo de processamento.
- O `AudioFile` de entrada é construído a partir do arquivo de exemplo selecionado pelo usuário (path local + `video_id="_test_"` para satisfazer a entidade do domínio sem confundir com áudios reais).
- O `QMediaPlayer` reutiliza a mesma infra do botão Play das vinhetas (PR 5).

**Comportamento de erro:**
- Se o arquivo de exemplo não existe ou tem formato inválido → mensagem de erro inline no card, sem popup modal.
- Se a edição é cancelada (botão Cancelar enquanto `Gerar preview` roda) → preview não é gerado, status volta para idle.
- Se nenhum filtro está habilitado → o preview é simplesmente uma cópia do arquivo de exemplo (com aviso "Nenhum filtro habilitado — preview = entrada").

**Logs (regra 1):** mesmas linhas de log do pipeline real (`Aplicando redução de ruído`, `Aplicando equalização`, etc.), mas escritas no label de status do card, não no log box principal do app. Mantém a tela de configuração isolada do log de produção.

**Debug (regra 2):** `print("[DEBUG audio_edit] preview iniciado", file=sys.stderr)` no início, `print("[DEBUG audio_edit] preview concluído em N s", file=sys.stderr)` no fim.

**Onde fica o arquivo de preview:**
- `downloads/_test_preview.mp3`
- Prefixo `_test_` para nunca colidir com um vídeo real (IDs do YouTube não começam com underscore).
- `cleanup_downloads()` (já existe em `baixar_audio.py`) deve excluir arquivos com esse prefixo no preflight do processamento real, evitando que o preview vire um upload acidental.

**Testes:**
- `tests/test_audio_test_presenter.py` (novo) — mock `IAudioEditor`, valida que o presenter passa o `AudioEditConfig` montado a partir de um state in-memory.
- `tests/test_app.py` — smoke: clicar "Gerar preview" sem arquivo selecionado mostra mensagem de erro; com arquivo selecionado, chama o presenter; cancelar interrompe.
- `tests/test_composition_root.py` — `build_audio_test_presenter()` retorna o tipo correto.

---

## Riscos / pontos de atenção

1. **Sample rate mismatch** no concat de vinhetas — força `aresample=44100` no filter graph (testado explicitamente no PR 2).
2. **`afftdn` é caro** em áudios de 1h+ → progress reporting bem feito é essencial pra UX. Sem fallback síncrono.
3. **PyQt6 `QtMultimedia`** precisa estar no `hiddenimports` do `build_app.spec` — adicionado no PR 5.
4. **Tamanho do bundle:** `QtMultimedia` adiciona ~15 MB ao instalador. Aceitável.
5. **Backwards compatibility** do `config.json`: novos campos têm defaults; instalações antigas continuam funcionando sem mexer no arquivo (testado no PR 1).
6. **Codecs de vinheta exóticos** (.m4a, .wav, .ogg): aceitar todos via ffmpeg; `aresample` + `libmp3lame` na saída normaliza.

---

## Versionamento

- Branch: `main` (projeto solo, sem feature branch).
- Versão alvo: **3.0.0** (major bump — primeiro pipeline completo de produção de podcast, marco do projeto).
- `installer.iss`: `AppVersion "3.0.0"` quando o PR 6 mergear.
- README.md atualizado no fim do PR 5 (descrição da feature + screenshot da nova tela).
- CLAUDE.md atualizado no fim de cada PR conforme a arquitetura/estrutura mude.
