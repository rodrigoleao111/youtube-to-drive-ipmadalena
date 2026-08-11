"""
FfmpegAudioEditor — implementação do contrato `IAudioEditor` (domain.ports).

Aplica filtros de pós-processamento em um arquivo MP3 baixado, gerando o
arquivo final pronto para upload. Pipeline:

    redução de ruído (afftdn) → equalização (5 bandas) → fade in/out (afade)
    → concatenação com vinhetas (concat ou acrossfade)

Quando `config.has_any_filter_enabled` é False, o editor retorna o AudioFile
de entrada sem chamar ffmpeg (no-op rápido).

Substitui o arquivo no caminho original via `os.replace` atômico.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from collections import deque
from dataclasses import replace
from typing import Callable, List, Optional, Tuple

from domain.entities import AudioEditConfig, AudioFile
from domain.exceptions import OperacaoCancelada

from infrastructure.audio._utils import ffmpeg_exe, ffprobe_exe, start_process


def _noop(*_a, **_kw):
    pass


# Logger nomeado — vai para `logs/DD-MM-YYYY.log` via configuração do app.
# Útil para diagnosticar falhas de edição em produção (frozen .exe não tem stderr visível).
_log = logging.getLogger("audio_edit")


# ---------------------------------------------------------------------------
# Mapeamentos
# ---------------------------------------------------------------------------

# Intensidade de redução de ruído → parâmetro `nr` do filtro afftdn (em dB).
# Valores escolhidos empiricamente (ffmpeg afftdn aceita 0.01 a 97).
_NOISE_NR_BY_INTENSITY = {
    "baixa": 10,
    "media": 17,
    "alta":  25,
}

# Sample rate alvo para normalização entre vinhetas e áudio principal.
# Evita o bug clássico de concat com sample rates divergentes (44.1k vs 48k).
_TARGET_SAMPLE_RATE = 44100


# ---------------------------------------------------------------------------
# Adaptador
# ---------------------------------------------------------------------------

class FfmpegAudioEditor:
    """
    Implementa `IAudioEditor` via subprocess do ffmpeg.

    Stateless — todo o estado vem do `AudioEditConfig` recebido em `process()`.
    """

    # Regex para extrair `out_time_us=...` do output `-progress pipe:1` do ffmpeg.
    _RE_OUT_TIME_US = re.compile(r"^out_time_us=(\d+)\s*$")

    # Regex para extrair "Duration: HH:MM:SS.SS" da saída do ffprobe (fallback).
    _RE_DURATION = re.compile(
        r"Duration:\s*(\d+):(\d+):(\d+\.\d+)"
    )

    # -----------------------------------------------------------------------
    # API pública (Protocol IAudioEditor)
    # -----------------------------------------------------------------------

    def process(
        self,
        audio: AudioFile,
        config: AudioEditConfig,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> AudioFile:
        """Aplica o pipeline configurado e devolve o `AudioFile` resultante."""
        log      = on_log      if callable(on_log)      else _noop
        progress = on_progress if callable(on_progress) else _noop

        # ---------- Descarta assets ausentes (vinhetas / música) ----------
        # Feito ANTES do fast path: se a única etapa habilitada era uma vinheta
        # que sumiu do disco, o pipeline inteiro vira no-op em vez de quebrar o
        # ffmpeg com um input inexistente.
        config = self._drop_missing_assets(config, log)

        # ---------- Fast path: nada a fazer ----------
        if not config.has_any_filter_enabled:
            log("[Edição] Nenhum filtro habilitado — pulando edição.")
            _log.info("no-op: filtros desabilitados")
            progress(1.0)
            return audio

        self._check_cancel(cancel_event)

        # ---------- Probe duration (necessário p/ fade out e progresso) ----------
        input_dur = self._probe_duration(audio.path)
        intro_dur = self._probe_duration(config.intro_path) if config.intro_path else 0.0
        outro_dur = self._probe_duration(config.outro_path) if config.outro_path else 0.0

        # A duração só é confiável se TODAS as peças foram medidas: uma vinheta
        # não medida deslocaria o fim do episódio e desalinharia o fade out da
        # música de fundo.
        duration_known = input_dur > 0 and not (
            (config.intro_path and intro_dur <= 0)
            or (config.outro_path and outro_dur <= 0)
        )

        # A sobreposição não pode passar da peça mais curta do cruzamento.
        config = self._clamp_overlaps(config, input_dur, intro_dur, outro_dur, log)

        # acrossfade encurta a saída: as sobreposições não são tempo somado.
        overlap = 0.0
        if config.intro_path:
            overlap += max(0.0, config.intro_overlap_secs)
        if config.outro_path:
            overlap += max(0.0, config.outro_overlap_secs)

        total_dur = (
            max(0.0, input_dur + intro_dur + outro_dur - overlap)
            if duration_known else 0.0
        )

        _log.info(
            "duracoes: input=%.2fs intro=%.2fs outro=%.2fs overlap=%.2fs "
            "total=%.2fs (conhecida=%s)",
            input_dur, intro_dur, outro_dur, overlap, total_dur, duration_known,
        )

        if not duration_known:
            # Sem duração não dá para ancorar nada no FIM do áudio. Seguimos
            # com o resto do pipeline, mas avisando: silenciar o episódio (fade
            # out em st=0) ou cortar a música seria pior que não aplicá-los.
            log("[Edição] Não foi possível medir a duração do áudio "
                "(ffprobe/ffmpeg indisponível) — fade out e fade out da "
                "música de fundo serão ignorados nesta execução.")
            _log.warning("duracao desconhecida para %s", audio.path)

        # bg_active=True → integra BG na mesma passagem ffmpeg (sem 2ª chamada).
        bg_active = config.bg_music_enabled and bool(config.bg_music_path)

        # Duração total da saída (maior quando BG music adiciona intro musical)
        output_dur = (
            total_dur + (config.bg_music_delay if bg_active else 0.0)
            if duration_known else 0.0
        )

        # Duração da própria faixa de música: define até onde ela toca quando o
        # loop está desligado — e, portanto, onde o fade out precisa começar.
        bg_dur = self._probe_duration(config.bg_music_path) if bg_active else 0.0
        bg_end = self._bg_end(config, output_dur, bg_dur)

        # ---------- Logs por etapa do pipeline ----------
        if config.noise_reduction_enabled:
            log(f"[Edição] Aplicando redução de ruído "
                f"(intensidade: {config.noise_reduction_intensity})...")
        if config.eq_enabled:
            log(f"[Edição] Aplicando equalização ({len(config.eq_bands)} bandas)...")
        if config.fade_in_enabled or config.fade_out_enabled:
            partes = []
            if config.fade_in_enabled:
                partes.append(f"fade in {config.fade_in_secs:.1f}s")
            if config.fade_out_enabled:
                partes.append(f"fade out {config.fade_out_secs:.1f}s")
            log(f"[Edição] Aplicando {' e '.join(partes)}...")
        if config.intro_path or config.outro_path:
            partes = []
            if config.intro_path:
                partes.append(f"intro: {os.path.basename(config.intro_path)}")
            if config.outro_path:
                partes.append(f"outro: {os.path.basename(config.outro_path)}")
            log(f"[Edição] Concatenando vinhetas ({', '.join(partes)})...")
        if config.volume_norm_enabled:
            log(f"[Edição] Nivelando volume ({config.volume_norm_lufs:.0f} LUFS — loudnorm)...")
        if bg_active:
            # Fades EFETIVOS: o orçamento é o trecho que a música realmente
            # ocupa (bg_end), não a saída inteira.
            fade_in_ef, fade_out_ef = self._fit_bg_fades(
                config.bg_music_fade_in,
                config.bg_music_fade_out,
                bg_end,
            )
            log(
                f"[Música de fundo] Mixando "
                f"'{os.path.basename(config.bg_music_path)}' "
                f"— vol={config.bg_music_volume:.0%}  "
                f"intro={config.bg_music_delay:.1f}s  "
                f"fade‑in={fade_in_ef:.1f}s  "
                f"fade‑out={fade_out_ef:.1f}s"
            )
            if (
                not config.bg_music_loop
                and bg_dur > 0
                and output_dur > 0
                and bg_dur < output_dur
            ):
                log(
                    "[Música de fundo] A faixa tem "
                    f"{bg_dur / 60:.1f} min e o episódio {output_dur / 60:.1f} min, "
                    "com o loop desligado — a música termina em "
                    f"{bg_end / 60:.1f} min (o fade out fecha nesse ponto). "
                    "Marque 'Repetir em loop' para cobrir o episódio inteiro."
                )
            if (
                abs(fade_in_ef - config.bg_music_fade_in) > 0.05
                or abs(fade_out_ef - config.bg_music_fade_out) > 0.05
            ):
                log(
                    "[Música de fundo] Fades reduzidos para caber em "
                    f"{bg_end:.1f}s de música (pedidos: "
                    f"{config.bg_music_fade_in:.1f}s / "
                    f"{config.bg_music_fade_out:.1f}s)."
                )
            _log.info(
                "bg_music: dur=%.2fs loop=%s fim_efetivo=%.2fs "
                "fade_in=%.2fs fade_out=%.2fs",
                bg_dur, config.bg_music_loop, bg_end, fade_in_ef, fade_out_ef,
            )
            _log.info(
                "bg_music integrado: path=%s total=%.2fs delay=%.2fs output=%.2fs",
                config.bg_music_path, total_dur, config.bg_music_delay, output_dur,
            )

        # ---------- Monta comando ffmpeg (uma única passagem) ----------
        tmp_path = audio.path + ".tmp"
        cmd = self._build_cmd(
            audio, config, input_dur, tmp_path,
            total_dur, bg_enabled=bg_active, bg_dur=bg_dur,
        )
        _log.info("ffmpeg cmd: %s", " ".join(cmd))

        # ---------- Roda o subprocess parseando progresso ----------
        recent_lines: deque = deque(maxlen=20)
        process = start_process(cmd, cancel_event=cancel_event)
        try:
            for line in process.stdout:
                self._check_cancel(cancel_event)
                stripped = line.rstrip()
                if stripped:
                    recent_lines.append(stripped)
                # output_dur já considera o delay da intro musical
                self._parse_progress_line(line, output_dur, progress)

            ret = process.wait()
            self._check_cancel(cancel_event)

            if ret != 0:
                tail = "\n  ".join(recent_lines) or "(sem saída)"
                _log.error(
                    "ffmpeg falhou (rc=%s) em %s. Últimas linhas:\n  %s",
                    ret, audio.path, tail,
                )
                raise RuntimeError(
                    f"ffmpeg encerrou com código {ret} ao editar {audio.path}.\n"
                    f"Últimas linhas:\n  {tail}"
                )

            # ---------- Substitui original (atômico) ----------
            os.replace(tmp_path, audio.path)
            _log.info("arquivo substituido: %s", audio.path)

            log("[Edição] Concluído.")
            if bg_active:
                log("[Música de fundo] Concluído.")

            progress(1.0)
            return audio

        except Exception:
            # cleanup do .tmp em caso de falha (não silencia a exceção original)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                    _log.info(".tmp removido apos erro: %s", tmp_path)
            except Exception:
                pass
            raise

    # -----------------------------------------------------------------------
    # Saneamento da configuração
    # -----------------------------------------------------------------------

    def _drop_missing_assets(
        self,
        config: AudioEditConfig,
        log: Callable[[str], None],
    ) -> AudioEditConfig:
        """
        Devolve a config sem os arquivos que não existem mais no disco.

        Vinhetas e música de fundo são copiadas para ``assets/vinhetas/``, mas
        o usuário pode apagar/mover a pasta entre configurar e processar. Passar
        um input inexistente ao ffmpeg aborta a edição inteira — melhor ignorar
        a peça ausente e avisar no log, como já era feito só para a música.
        """
        updates: dict = {}

        for campo, rotulo in (
            ("intro_path", "Vinheta de entrada"),
            ("outro_path", "Vinheta de saída"),
        ):
            caminho = getattr(config, campo)
            if caminho and not os.path.isfile(caminho):
                log(f"[Edição] {rotulo} não encontrada: {caminho} — ignorando.")
                _log.warning("%s ausente: %s", rotulo, caminho)
                updates[campo] = None

        if config.bg_music_enabled and not (
            config.bg_music_path and os.path.isfile(config.bg_music_path)
        ):
            log("[Música de fundo] Arquivo não encontrado: "
                f"{config.bg_music_path} — pulando.")
            _log.warning("bg_music ausente: %s", config.bg_music_path)
            updates["bg_music_enabled"] = False

        return replace(config, **updates) if updates else config

    @staticmethod
    def _bg_end(
        config: AudioEditConfig,
        output_dur: float,
        bg_dur: float,
    ) -> float:
        """
        Instante (em segundos) em que a música de fundo realmente termina.

        Com o loop ligado a música é infinita (`-stream_loop -1`) e cobre a
        saída toda. Com o loop DESLIGADO ela acaba na própria duração — e é aí
        que o fade out precisa fechar. Ancorar no fim do episódio, como era
        feito, deixava a rampa agendada para um ponto onde já não havia música:
        a faixa cortava seca no meio do episódio e o fade out sumia.

        Retorna 0.0 quando não há como saber (nem episódio nem faixa medidos).
        """
        if config.bg_music_loop:
            return max(0.0, output_dur)

        if bg_dur <= 0:
            return max(0.0, output_dur)      # sem medida da faixa, assume o fim

        if output_dur > 0:
            return min(bg_dur, output_dur)

        # Episódio não medido, mas a faixa sim: o fim dela ainda é uma âncora
        # válida para o fade out.
        return bg_dur

    @staticmethod
    def _fit_bg_fades(
        fade_in: float,
        fade_out: float,
        output_dur: float,
    ) -> Tuple[float, float]:
        """
        Ajusta os fades da música para caberem juntos na saída.

        Devolve ``(fade_in, fade_out)`` efetivos. Quando a soma pedida não cabe
        em ``output_dur``, ambos são reduzidos pelo mesmo fator — a proporção
        escolhida pelo usuário é mantida e as rampas se encostam sem invadir
        uma à outra.

        Três comportamentos antigos que isso corrige:
          - fade out maior que o áudio era **descartado inteiro** (a música
            parava seca), enquanto o fade in era encurtado;
          - o fade in era limitado a 40 % da saída, um número arbitrário e
            silencioso;
          - com ``fade_in + fade_out > output_dur`` as rampas se sobrepunham e
            a música nunca chegava ao volume configurado.

        ``output_dur <= 0`` (duração não medida) devolve o fade in pedido e
        zera o fade out — não há fim conhecido para ancorá-lo.
        """
        fi = max(0.0, fade_in)
        fo = max(0.0, fade_out)

        if output_dur <= 0:
            return fi, 0.0

        soma = fi + fo
        if soma > output_dur and soma > 0:
            fator = output_dur / soma
            fi *= fator
            fo *= fator

        return fi, fo

    def _clamp_overlaps(
        self,
        config: AudioEditConfig,
        input_dur: float,
        intro_dur: float,
        outro_dur: float,
        log: Callable[[str], None],
    ) -> AudioEditConfig:
        """
        Limita cada sobreposição à duração da peça mais curta do cruzamento.

        `acrossfade=d=X` consome X segundos do fim do primeiro stream e do
        início do segundo. Com X maior que a vinheta, o ffmpeg não reclama —
        ele engole a vinheta inteira e ainda come o começo do sermão (uma
        vinheta de 4 s com sobreposição de 10 s devora os 6 s iniciais da
        pregação). O painel permite até 10 s, então o limite tem de vir daqui.
        """
        if input_dur <= 0:
            return config      # sem duração medida não há como limitar

        updates: dict = {}
        for campo, dur_vinheta, rotulo in (
            ("intro_overlap_secs", intro_dur, "entrada"),
            ("outro_overlap_secs", outro_dur, "saída"),
        ):
            atual = getattr(config, campo)
            caminho = config.intro_path if "intro" in campo else config.outro_path
            if not caminho or atual <= 0 or dur_vinheta <= 0:
                continue
            limite = min(dur_vinheta, input_dur)
            if atual > limite:
                log(f"[Edição] Sobreposição da vinheta de {rotulo} reduzida de "
                    f"{atual:.1f}s para {limite:.1f}s (duração da vinheta).")
                _log.warning(
                    "%s: overlap %.2fs > limite %.2fs — ajustado",
                    campo, atual, limite,
                )
                updates[campo] = limite

        return replace(config, **updates) if updates else config

    # -----------------------------------------------------------------------
    # Construção do filter graph (testado via _build_filter_complex)
    # -----------------------------------------------------------------------

    def _build_filter_complex(
        self,
        config: AudioEditConfig,
        input_dur: float,
        total_dur: float = 0.0,
        *,
        bg_enabled: bool = False,
        bg_dur: float = 0.0,
    ) -> Tuple[str, str]:
        """
        Constrói a string ``-filter_complex`` e o nome do output map.

        Parameters
        ----------
        input_dur:
            Duração do áudio principal em segundos.
        total_dur:
            Duração total do episódio após vinhetas (input + intro + outro).
            Necessário para calcular o ``atrim`` da música de fundo quando
            ``bg_enabled=True``. Se 0, usa ``input_dur`` como fallback.
        bg_enabled:
            True quando a música de fundo deve ser integrada nesta passagem.
            Determinado por ``process()`` após verificar existência do arquivo.
        bg_dur:
            Duração da faixa de música. Necessária para ancorar o fade out no
            fim REAL da música quando o loop está desligado (uma faixa mais
            curta que o episódio acaba antes do fim da saída). 0 = desconhecida.

        Returns
        -------
        (filter_complex_str, output_map)
        """
        # ── Filtros do áudio principal ──────────────────────────────────────
        main_filters: List[str] = []

        if config.noise_reduction_enabled:
            nr = _NOISE_NR_BY_INTENSITY.get(config.noise_reduction_intensity, 17)
            main_filters.append(f"afftdn=nr={nr}")

        if config.eq_enabled:
            for band in config.eq_bands:
                main_filters.append(
                    f"equalizer=f={band.freq_hz}:t=q:w=1.0:g={band.gain_db}"
                )

        if config.fade_in_enabled and config.fade_in_secs > 0:
            main_filters.append(f"afade=t=in:st=0:d={config.fade_in_secs}")
        if config.fade_out_enabled and config.fade_out_secs > 0:
            # O fade out é ancorado no FIM do áudio. Sem duração medida,
            # `st` cairia em 0 e o afade silenciaria o episódio inteiro logo
            # nos primeiros segundos — por isso a etapa é pulada.
            if input_dur > 0:
                fade_start = max(0.0, input_dur - config.fade_out_secs)
                main_filters.append(
                    f"afade=t=out:st={fade_start}:d={config.fade_out_secs}"
                )
            else:
                _log.warning("fade out ignorado: duracao do audio desconhecida")

        if config.volume_norm_enabled:
            lufs = config.volume_norm_lufs
            # linear=true pede um ganho linear único em vez da correção
            # frame-a-frame. Em passagem única (sem measured_I/LRA/TP de uma
            # análise prévia) o ffmpeg não tem como calcular esse ganho e volta
            # ao modo dinâmico silenciosamente — o alvo de LUFS é respeitado do
            # mesmo jeito. Mantido porque, com valores medidos, vira o caminho
            # rápido; não esperar ganho de tempo hoje.
            main_filters.append(
                f"loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11:linear=true:print_format=none"
            )

        main_filters.append(f"aresample={_TARGET_SAMPLE_RATE}")
        main_chain = ",".join(main_filters) if main_filters else "anull"

        has_intro = config.intro_path is not None
        has_outro = config.outro_path is not None

        # Quando BG music está integrado, o episódio sai com label [episode]
        # para depois ser mixado; caso contrário, sai diretamente como [out].
        episode_label = "[episode]" if bg_enabled else "[out]"

        # ── Sem vinhetas ────────────────────────────────────────────────────
        if not has_intro and not has_outro:
            chain_parts: List[str] = [f"[0:a]{main_chain}{episode_label}"]
            if not bg_enabled:
                return chain_parts[0], "[out]"
        else:
            # ── Com vinhetas: concat ou acrossfade ──────────────────────────
            # Index de inputs:
            #   [0:a] = áudio principal
            #   [1:a] = intro (se houver)
            #   [N:a] = outro (1 ou 2 dependendo de intro)
            idx_intro = 1 if has_intro else None
            idx_outro = (2 if has_intro else 1) if has_outro else None

            chain_parts = [f"[0:a]{main_chain}[main]"]

            def _vinheta_filters() -> List[str]:
                vf: List[str] = []
                if config.volume_norm_enabled:
                    lufs = config.volume_norm_lufs
                    vf.append(
                        f"loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11"
                        ":linear=true:print_format=none"
                    )
                vf.append(f"aresample={_TARGET_SAMPLE_RATE}")
                return vf

            if has_intro:
                chain_parts.append(
                    f"[{idx_intro}:a]{','.join(_vinheta_filters())}[intro]"
                )
            if has_outro:
                chain_parts.append(
                    f"[{idx_outro}:a]{','.join(_vinheta_filters())}[outro]"
                )

            intro_overlap = config.intro_overlap_secs if has_intro else 0.0
            outro_overlap = config.outro_overlap_secs if has_outro else 0.0

            if has_intro and has_outro:
                if intro_overlap > 0:
                    chain_parts.append(f"[intro][main]acrossfade=d={intro_overlap}[a1]")
                else:
                    chain_parts.append("[intro][main]concat=n=2:v=0:a=1[a1]")

                if outro_overlap > 0:
                    chain_parts.append(
                        f"[a1][outro]acrossfade=d={outro_overlap}{episode_label}"
                    )
                else:
                    chain_parts.append(
                        f"[a1][outro]concat=n=2:v=0:a=1{episode_label}"
                    )

            elif has_intro:
                if intro_overlap > 0:
                    chain_parts.append(
                        f"[intro][main]acrossfade=d={intro_overlap}{episode_label}"
                    )
                else:
                    chain_parts.append(
                        f"[intro][main]concat=n=2:v=0:a=1{episode_label}"
                    )
            else:  # has_outro
                if outro_overlap > 0:
                    chain_parts.append(
                        f"[main][outro]acrossfade=d={outro_overlap}{episode_label}"
                    )
                else:
                    chain_parts.append(
                        f"[main][outro]concat=n=2:v=0:a=1{episode_label}"
                    )

            if not bg_enabled:
                return ";".join(chain_parts), "[out]"

        # ── Música de fundo integrada ────────────────────────────────────────
        # Índice do input de BG: vem depois de principal + eventuais vinhetas.
        idx_bg = 1 + int(has_intro) + int(has_outro)

        ep_dur     = total_dur if total_dur > 0 else input_dur
        delay      = max(0.0, config.bg_music_delay)
        delay_ms   = int(delay * 1000)

        # Sem duração medida não dá para cortar nem ancorar o fade out da
        # música: um `atrim=end=<delay>` faria a música sumir logo após a
        # intro musical. Nesse caso a música entra inteira (em loop, se
        # configurado) e quem delimita a saída é o próprio episódio, via
        # `amix duration=first`.
        duration_known = ep_dur > 0
        output_dur = ep_dur + delay if duration_known else 0.0

        bg_parts: List[str] = []
        if duration_known:
            bg_parts += [f"atrim=end={output_dur:.3f}", "asetpts=N/SR/TB"]
        bg_parts.append(f"volume={config.bg_music_volume:.4f}")

        # Onde a música de fato acaba: fim da saída com loop ligado, fim da
        # própria faixa com loop desligado. É essa a âncora do fade out.
        bg_end = self._bg_end(config, output_dur, bg_dur)

        fade_in, fade_out = self._fit_bg_fades(
            config.bg_music_fade_in,
            config.bg_music_fade_out,
            bg_end,
        )

        if fade_in > 0:
            bg_parts.append(f"afade=t=in:st=0:d={fade_in:.2f}")

        if fade_out > 0:
            # `st` pode ser 0 quando o fade out cobre a faixa inteira — é um
            # comando válido e melhor que descartar o efeito pedido.
            fade_out_st = max(0.0, bg_end - fade_out)
            bg_parts.append(
                f"afade=t=out:st={fade_out_st:.3f}:d={fade_out:.2f}"
            )
        elif config.bg_music_fade_out > 0:
            _log.warning(
                "fade out da musica ignorado: fim da musica desconhecido"
            )

        chain_parts.append(f"[{idx_bg}:a]{','.join(bg_parts)}[bg]")

        if delay_ms > 0:
            chain_parts.append(f"[episode]adelay={delay_ms}|{delay_ms}[ep_delayed]")
            ep_for_mix = "[ep_delayed]"
        else:
            ep_for_mix = "[episode]"

        # `duration=first` com o EPISÓDIO como primeiro input: a saída sempre
        # tem exatamente o comprimento do episódio (+ intro musical), tanto com
        # a música em loop infinito (`-stream_loop -1`) quanto com uma faixa
        # curta que acaba antes. Substitui o par shortest/longest, que dependia
        # de bg e episódio terem a mesma duração medida para não cortar nem
        # esticar a saída.
        chain_parts.append(
            f"{ep_for_mix}[bg]amix=inputs=2:duration=first"
            ":dropout_transition=0:normalize=0[out]"
        )

        return ";".join(chain_parts), "[out]"

    def _build_cmd(
        self,
        audio: AudioFile,
        config: AudioEditConfig,
        input_dur: float,
        tmp_path: str,
        total_dur: float = 0.0,
        *,
        bg_enabled: bool = False,
        bg_dur: float = 0.0,
    ) -> List[str]:
        """Monta a lista de argumentos para o subprocess ffmpeg."""
        filter_complex, out_map = self._build_filter_complex(
            config, input_dur, total_dur,
            bg_enabled=bg_enabled, bg_dur=bg_dur,
        )

        cmd: List[str] = [
            ffmpeg_exe(),
            "-hide_banner",
            "-y",                    # sobrescreve o .tmp se existir
            "-i", audio.path,
        ]
        if config.intro_path:
            cmd += ["-i", config.intro_path]
        if config.outro_path:
            cmd += ["-i", config.outro_path]

        # BG music: adicionado DEPOIS das vinhetas para que o índice [N:a]
        # seja consistente com o que _build_filter_complex calculou.
        if bg_enabled and config.bg_music_path:
            if config.bg_music_loop:
                cmd += ["-stream_loop", "-1"]
            cmd += ["-i", config.bg_music_path]

        cmd += [
            "-filter_complex", filter_complex,
            "-map", out_map,
            "-c:a", "libmp3lame",
            "-q:a", "2",
            # Força o formato de saída para MP3, ignorando a extensão `.tmp`.
            # Sem isso o ffmpeg falha com "Unable to choose an output format
            # for '...mp3.tmp'" ao tentar inferir pelo sufixo.
            "-f", "mp3",
            "-progress", "pipe:1",
            "-nostats",
            tmp_path,
        ]
        return cmd

    # -----------------------------------------------------------------------
    # Probe de duração via ffprobe
    # -----------------------------------------------------------------------

    def _probe_duration(self, path: str) -> float:
        """
        Retorna a duração do arquivo em segundos. 0.0 se não conseguir medir.

        Tenta o ffprobe e, se ele não estiver disponível, cai para o próprio
        ffmpeg. O fallback não é teórico: o bundle do PyInstaller já foi
        distribuído só com `ffmpeg.exe`, e sem duração o pipeline calculava
        `afade=t=out:st=0` (silenciando o episódio) e `atrim` da música no
        tamanho da intro musical (a música sumia após alguns segundos).
        """
        dur = self._duration_via_ffprobe(path)
        if dur > 0:
            return dur

        dur = self._duration_via_ffmpeg(path)
        if dur > 0:
            _log.info(
                "duracao de %s obtida via ffmpeg (ffprobe indisponivel): %.2fs",
                path, dur,
            )
        return dur

    def _run_probe(self, cmd: List[str]) -> subprocess.CompletedProcess:
        """Executa um binário de probe capturando saída, sem abrir console."""
        extra: dict = {}
        if sys.platform == "win32":
            extra["creationflags"] = subprocess.CREATE_NO_WINDOW
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            **extra,
        )

    def _duration_via_ffprobe(self, path: str) -> float:
        """Duração via `ffprobe -show_entries format=duration`."""
        try:
            result = self._run_probe([
                ffprobe_exe(),
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                path,
            ])
            if result.returncode == 0:
                return float(result.stdout.strip() or 0.0)
        except Exception as e:
            _log.warning("ffprobe falhou em %s: %s", path, e)
        return 0.0

    def _duration_via_ffmpeg(self, path: str) -> float:
        """
        Duração pela linha ``Duration: HH:MM:SS.ss`` que o ffmpeg imprime ao
        abrir o arquivo. Sem output definido o ffmpeg sai com código != 0 —
        isso é esperado; o que interessa é o cabeçalho já impresso.
        """
        try:
            result = self._run_probe([
                ffmpeg_exe(), "-hide_banner", "-i", path,
            ])
            texto = (result.stderr or "") + (result.stdout or "")
            m = self._RE_DURATION.search(texto)
            if m:
                horas, minutos, segundos = m.groups()
                return int(horas) * 3600 + int(minutos) * 60 + float(segundos)
        except Exception as e:
            _log.warning("ffmpeg -i falhou em %s: %s", path, e)
        return 0.0

    # -----------------------------------------------------------------------
    # Parsing de progresso do ffmpeg `-progress pipe:1`
    # -----------------------------------------------------------------------

    def _parse_progress_line(
        self,
        line: str,
        total_dur: float,
        on_progress: Callable[[float], None],
    ) -> None:
        """
        Atualiza `on_progress` com o valor normalizado [0, 1] quando a linha
        contém `out_time_us=...`.

        Demais linhas (`progress=continue`, `total_size=...`, etc.) são ignoradas.
        """
        m = self._RE_OUT_TIME_US.match(line)
        if not m:
            return
        try:
            out_us = int(m.group(1))
            if total_dur > 0:
                # 1 s = 1_000_000 us → out_us / (total_dur * 1_000_000)
                p = out_us / (total_dur * 1_000_000.0)
                on_progress(min(0.99, max(0.0, p)))
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _check_cancel(self, cancel_event) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise OperacaoCancelada("Operação cancelada pelo usuário.")
