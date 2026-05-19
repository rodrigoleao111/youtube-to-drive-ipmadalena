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
        total_dur = max(0.001, input_dur + intro_dur + outro_dur)

        _log.info(
            "duracoes: input=%.2fs intro=%.2fs outro=%.2fs total=%.2fs",
            input_dur, intro_dur, outro_dur, total_dur,
        )

        # ---------- Logs por etapa do pipeline (regra 1 do plano) ----------
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

        # ---------- Monta comando ffmpeg ----------
        tmp_path = audio.path + ".tmp"
        cmd = self._build_cmd(audio, config, input_dur, tmp_path)
        _log.info("ffmpeg cmd: %s", " ".join(cmd))

        # ---------- Roda o subprocess parseando progresso ----------
        # Acumula últimas linhas do stdout (que inclui stderr — capturado em
        # start_process via stderr=STDOUT) — assim, em caso de erro, sabemos
        # POR QUE o ffmpeg falhou. Sem isso, qualquer falha vira só "código N".
        recent_lines: deque = deque(maxlen=20)
        process = start_process(cmd, cancel_event=cancel_event)
        try:
            for line in process.stdout:
                self._check_cancel(cancel_event)
                stripped = line.rstrip()
                if stripped:
                    recent_lines.append(stripped)
                self._parse_progress_line(line, total_dur, progress)

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
    # Construção do filter graph (testado via _build_filter_complex)
    # -----------------------------------------------------------------------

    def _build_filter_complex(
        self,
        config: AudioEditConfig,
        input_dur: float,
    ) -> Tuple[str, str]:
        """
        Constrói a string `-filter_complex` e o nome do output map.

        Returns
        -------
        (filter_complex_str, output_map)
            - filter_complex_str: o conteúdo do `-filter_complex`
            - output_map: o nome do label final (ex.: '[out]' ou '[main]')
        """
        # Filtros aplicados ao áudio principal (índice de input 0)
        main_filters: List[str] = []

        if config.noise_reduction_enabled:
            nr = _NOISE_NR_BY_INTENSITY.get(config.noise_reduction_intensity, 17)
            main_filters.append(f"afftdn=nr={nr}")

        if config.eq_enabled:
            for band in config.eq_bands:
                # Q=1.0 é um valor balanceado para EQ paramétrico de voz
                main_filters.append(
                    f"equalizer=f={band.freq_hz}:t=q:w=1.0:g={band.gain_db}"
                )

        if config.fade_in_enabled and config.fade_in_secs > 0:
            main_filters.append(
                f"afade=t=in:st=0:d={config.fade_in_secs}"
            )
        if config.fade_out_enabled and config.fade_out_secs > 0:
            fade_start = max(0.0, input_dur - config.fade_out_secs)
            main_filters.append(
                f"afade=t=out:st={fade_start}:d={config.fade_out_secs}"
            )

        if config.volume_norm_enabled:
            lufs = config.volume_norm_lufs
            main_filters.append(f"loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11")

        # Sample rate consistente com vinhetas (mesmo se concat não acontecer,
        # garante compatibilidade do MP3 final)
        main_filters.append(f"aresample={_TARGET_SAMPLE_RATE}")

        main_chain = ",".join(main_filters) if main_filters else "anull"

        has_intro = config.intro_path is not None
        has_outro = config.outro_path is not None

        # ---------- Sem vinhetas: filter graph linear simples ----------
        if not has_intro and not has_outro:
            fc = f"[0:a]{main_chain}[out]"
            return fc, "[out]"

        # ---------- Com vinhetas: concat ou acrossfade ----------
        # Index de inputs no comando ffmpeg:
        #   [0:a] = áudio principal
        #   [1:a] = intro (se houver)
        #   [N:a] = outro (1 ou 2 dependendo de intro)
        idx_intro = 1 if has_intro else None
        idx_outro = (2 if has_intro else 1) if has_outro else None

        chain_parts: List[str] = []
        chain_parts.append(f"[0:a]{main_chain}[main]")

        if has_intro:
            vinheta_filters = []
            if config.volume_norm_enabled:
                lufs = config.volume_norm_lufs
                vinheta_filters.append(f"loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11")
            vinheta_filters.append(f"aresample={_TARGET_SAMPLE_RATE}")
            chain_parts.append(
                f"[{idx_intro}:a]{','.join(vinheta_filters)}[intro]"
            )
        if has_outro:
            vinheta_filters = []
            if config.volume_norm_enabled:
                lufs = config.volume_norm_lufs
                vinheta_filters.append(f"loudnorm=I={lufs:.1f}:TP=-1.5:LRA=11")
            vinheta_filters.append(f"aresample={_TARGET_SAMPLE_RATE}")
            chain_parts.append(
                f"[{idx_outro}:a]{','.join(vinheta_filters)}[outro]"
            )

        # Estratégia de junção: se overlap > 0 usa acrossfade; senão concat.
        # acrossfade só funciona entre 2 streams; encadear quando há intro+outro.
        intro_overlap = config.intro_overlap_secs if has_intro else 0.0
        outro_overlap = config.outro_overlap_secs if has_outro else 0.0

        if has_intro and has_outro:
            if intro_overlap > 0:
                chain_parts.append(f"[intro][main]acrossfade=d={intro_overlap}[a1]")
            else:
                chain_parts.append("[intro][main]concat=n=2:v=0:a=1[a1]")

            if outro_overlap > 0:
                chain_parts.append(f"[a1][outro]acrossfade=d={outro_overlap}[out]")
            else:
                chain_parts.append("[a1][outro]concat=n=2:v=0:a=1[out]")

        elif has_intro:
            if intro_overlap > 0:
                chain_parts.append(f"[intro][main]acrossfade=d={intro_overlap}[out]")
            else:
                chain_parts.append("[intro][main]concat=n=2:v=0:a=1[out]")

        else:  # has_outro
            if outro_overlap > 0:
                chain_parts.append(f"[main][outro]acrossfade=d={outro_overlap}[out]")
            else:
                chain_parts.append("[main][outro]concat=n=2:v=0:a=1[out]")

        return ";".join(chain_parts), "[out]"

    def _build_cmd(
        self,
        audio: AudioFile,
        config: AudioEditConfig,
        input_dur: float,
        tmp_path: str,
    ) -> List[str]:
        """Monta a lista de argumentos para o subprocess ffmpeg."""
        filter_complex, out_map = self._build_filter_complex(config, input_dur)

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
        Retorna a duração do arquivo em segundos via ffprobe.
        Retorna 0.0 se não conseguir determinar.
        """
        try:
            cmd = [
                ffprobe_exe(),
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                path,
            ]
            extra: dict = {}
            if sys.platform == "win32":
                extra["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
                **extra,
            )
            if result.returncode == 0:
                return float(result.stdout.strip() or 0.0)
        except Exception as e:
            _log.warning("ffprobe falhou em %s: %s", path, e)
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
