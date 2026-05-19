"""
Testes para infrastructure/audio/ffmpeg_editor.py.

Mocks no `subprocess.Popen` (via `start_process`) e em `_probe_duration`.
Não roda ffmpeg de verdade.
"""

from __future__ import annotations

import os
import threading
from unittest.mock import MagicMock, patch

import pytest

from domain.entities import AudioEditConfig, AudioFile, EqBand
from domain.exceptions import OperacaoCancelada

from infrastructure.audio.ffmpeg_editor import FfmpegAudioEditor


# ---------------------------------------------------------------------------
# Fixtures e helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def audio_file(tmp_path):
    """AudioFile com um arquivo placeholder (existe no disco)."""
    p = tmp_path / "trecho.mp3"
    p.write_bytes(b"fake mp3 data")
    return AudioFile(path=str(p), title="Culto", video_id="abc123")


def _make_proc_mock(stdout_lines=None, returncode=0):
    """
    Cria um mock de subprocess que parece um Popen vivo:
      - stdout iterável com as linhas fornecidas
      - wait() retorna o código fornecido
    """
    proc = MagicMock()
    proc.stdout = iter(stdout_lines or [])
    proc.wait = MagicMock(return_value=returncode)
    proc.poll = MagicMock(return_value=returncode)
    proc.terminate = MagicMock()
    return proc


# ===========================================================================
# Fast path: sem filtros habilitados
# ===========================================================================

class TestNoOpFastPath:
    def test_retorna_audio_inalterado_quando_nada_habilitado(self, audio_file):
        editor = FfmpegAudioEditor()
        with patch("infrastructure.audio.ffmpeg_editor.start_process") as sp:
            result = editor.process(audio_file, AudioEditConfig())
        assert result == audio_file
        sp.assert_not_called()

    def test_emite_log_de_pulado(self, audio_file):
        editor = FfmpegAudioEditor()
        log = MagicMock()
        with patch("infrastructure.audio.ffmpeg_editor.start_process"):
            editor.process(audio_file, AudioEditConfig(), on_log=log)
        msgs = " ".join(c.args[0] for c in log.call_args_list)
        assert "pulando" in msgs.lower() or "no-op" in msgs.lower() or "nenhum filtro" in msgs.lower()

    def test_progresso_chega_em_1_no_no_op(self, audio_file):
        editor = FfmpegAudioEditor()
        progress = MagicMock()
        with patch("infrastructure.audio.ffmpeg_editor.start_process"):
            editor.process(audio_file, AudioEditConfig(), on_progress=progress)
        assert progress.call_args_list[-1].args[0] == 1.0


# ===========================================================================
# Construção do filter_complex
# ===========================================================================

class TestBuildFilterComplex:
    def _editor(self):
        return FfmpegAudioEditor()

    def test_so_denoise_emite_afftdn(self):
        cfg = AudioEditConfig(noise_reduction_enabled=True,
                              noise_reduction_intensity="media")
        fc, out = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "afftdn=nr=17" in fc
        assert out == "[out]"

    def test_intensidade_baixa_usa_nr_10(self):
        cfg = AudioEditConfig(noise_reduction_enabled=True,
                              noise_reduction_intensity="baixa")
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "afftdn=nr=10" in fc

    def test_intensidade_alta_usa_nr_25(self):
        cfg = AudioEditConfig(noise_reduction_enabled=True,
                              noise_reduction_intensity="alta")
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "afftdn=nr=25" in fc

    def test_eq_emite_5_bandas_com_freqs_corretas(self):
        cfg = AudioEditConfig(eq_enabled=True)
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        for f in (80, 250, 1000, 4000, 10000):
            assert f"equalizer=f={f}:" in fc

    def test_fade_in_e_fade_out_calculam_st_corretamente(self):
        cfg = AudioEditConfig(
            fade_in_enabled=True, fade_in_secs=2.0,
            fade_out_enabled=True, fade_out_secs=3.0,
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=120.0)
        assert "afade=t=in:st=0:d=2.0" in fc
        # fade out começa em (input_dur - fade_out_secs) = 120 - 3 = 117
        assert "afade=t=out:st=117.0:d=3.0" in fc

    def test_ordem_dos_filtros_e_denoise_eq_fade(self):
        cfg = AudioEditConfig(
            noise_reduction_enabled=True,
            eq_enabled=True,
            fade_in_enabled=True,
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        i_denoise = fc.index("afftdn")
        i_eq      = fc.index("equalizer")
        i_fade    = fc.index("afade")
        assert i_denoise < i_eq < i_fade

    def test_aresample_44100_sempre_presente(self):
        cfg = AudioEditConfig(eq_enabled=True)
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "aresample=44100" in fc

    def test_sem_vinheta_filter_graph_e_linear(self):
        cfg = AudioEditConfig(eq_enabled=True)
        fc, out = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert fc.startswith("[0:a]")
        assert fc.endswith("[out]")
        assert ";" not in fc  # uma única chain

    def test_intro_e_outro_montam_concat_3_streams(self):
        cfg = AudioEditConfig(
            intro_path="/tmp/i.mp3",
            outro_path="/tmp/o.mp3",
        )
        fc, out = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[1:a]aresample=44100[intro]" in fc
        assert "[2:a]aresample=44100[outro]" in fc
        assert "[intro][main]concat=n=2:v=0:a=1[a1]" in fc
        assert "[a1][outro]concat=n=2:v=0:a=1[out]" in fc

    def test_so_intro_indices_corretos(self):
        cfg = AudioEditConfig(intro_path="/tmp/i.mp3")
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[1:a]aresample=44100[intro]" in fc
        assert "[intro][main]concat=n=2:v=0:a=1[out]" in fc

    def test_so_outro_indice_e_1(self):
        # Sem intro, outro vira input [1:a] (não [2:a])
        cfg = AudioEditConfig(outro_path="/tmp/o.mp3")
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[1:a]aresample=44100[outro]" in fc
        assert "[main][outro]concat=n=2:v=0:a=1[out]" in fc

    def test_intro_overlap_usa_acrossfade(self):
        cfg = AudioEditConfig(
            intro_path="/tmp/i.mp3",
            intro_overlap_secs=1.5,
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[intro][main]acrossfade=d=1.5[out]" in fc

    def test_outro_overlap_usa_acrossfade(self):
        cfg = AudioEditConfig(
            outro_path="/tmp/o.mp3",
            outro_overlap_secs=2.0,
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[main][outro]acrossfade=d=2.0[out]" in fc


# ===========================================================================
# Construção do comando ffmpeg
# ===========================================================================

class TestBuildCmd:
    def test_inputs_sem_vinheta(self, audio_file):
        editor = FfmpegAudioEditor()
        cfg = AudioEditConfig(eq_enabled=True)
        cmd = editor._build_cmd(audio_file, cfg, input_dur=60.0,
                                tmp_path=audio_file.path + ".tmp")
        # exatamente 1 input
        assert cmd.count("-i") == 1
        assert audio_file.path in cmd

    def test_inputs_com_intro_e_outro(self, audio_file):
        editor = FfmpegAudioEditor()
        cfg = AudioEditConfig(
            intro_path="/tmp/intro.mp3",
            outro_path="/tmp/outro.mp3",
        )
        cmd = editor._build_cmd(audio_file, cfg, input_dur=60.0,
                                tmp_path=audio_file.path + ".tmp")
        assert cmd.count("-i") == 3
        # ordem: principal, intro, outro
        i_main  = cmd.index(audio_file.path)
        i_intro = cmd.index("/tmp/intro.mp3")
        i_outro = cmd.index("/tmp/outro.mp3")
        assert i_main < i_intro < i_outro

    def test_codec_libmp3lame_q2(self, audio_file):
        editor = FfmpegAudioEditor()
        cfg = AudioEditConfig(eq_enabled=True)
        cmd = editor._build_cmd(audio_file, cfg, input_dur=60.0,
                                tmp_path="/tmp/x.mp3.tmp")
        assert "libmp3lame" in cmd
        assert "-c:a" in cmd
        assert "-q:a" in cmd

    def test_progress_pipe_e_nostats(self, audio_file):
        editor = FfmpegAudioEditor()
        cfg = AudioEditConfig(eq_enabled=True)
        cmd = editor._build_cmd(audio_file, cfg, input_dur=60.0,
                                tmp_path="/tmp/x.mp3.tmp")
        assert "-progress" in cmd
        i = cmd.index("-progress")
        assert cmd[i + 1] == "pipe:1"
        assert "-nostats" in cmd

    def test_output_e_o_caminho_tmp(self, audio_file):
        editor = FfmpegAudioEditor()
        cfg = AudioEditConfig(eq_enabled=True)
        cmd = editor._build_cmd(audio_file, cfg, input_dur=60.0,
                                tmp_path="/tmp/out.mp3.tmp")
        assert cmd[-1] == "/tmp/out.mp3.tmp"


# ===========================================================================
# Parsing de progresso
# ===========================================================================

class TestParseProgress:
    def _editor(self):
        return FfmpegAudioEditor()

    def test_out_time_us_e_normalizado_corretamente(self):
        progress = MagicMock()
        # total_dur = 60s = 60_000_000 us. out_time = 30_000_000 → 0.5
        self._editor()._parse_progress_line(
            "out_time_us=30000000", total_dur=60.0, on_progress=progress)
        progress.assert_called_once()
        assert progress.call_args.args[0] == pytest.approx(0.5, abs=0.01)

    def test_progress_eh_clampado_em_099(self):
        progress = MagicMock()
        # out_time_us muito maior que total_dur → 0.99 (não 1.0, deixado p/ o final)
        self._editor()._parse_progress_line(
            "out_time_us=99999999999", total_dur=60.0, on_progress=progress)
        assert progress.call_args.args[0] == pytest.approx(0.99, abs=0.01)

    def test_linhas_irrelevantes_sao_ignoradas(self):
        progress = MagicMock()
        for line in ("progress=continue", "total_size=12345", "frame=0",
                     "speed=1.5x", ""):
            self._editor()._parse_progress_line(
                line, total_dur=60.0, on_progress=progress)
        progress.assert_not_called()

    def test_total_dur_zero_nao_quebra(self):
        progress = MagicMock()
        # Não deve lançar ZeroDivisionError
        self._editor()._parse_progress_line(
            "out_time_us=1000000", total_dur=0.0, on_progress=progress)
        progress.assert_not_called()


# ===========================================================================
# Process — fluxo completo (subprocess mockado)
# ===========================================================================

class TestProcessFluxo:
    def test_substitui_o_arquivo_original_via_os_replace(self, audio_file):
        editor = FfmpegAudioEditor()
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)

        cfg = AudioEditConfig(eq_enabled=True)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0), \
             patch("os.replace") as mock_replace:
            editor.process(audio_file, cfg)

        mock_replace.assert_called_once_with(
            audio_file.path + ".tmp", audio_file.path
        )

    def test_progresso_e_emitido_durante_o_loop(self, audio_file):
        editor = FfmpegAudioEditor()
        progress = MagicMock()
        proc = _make_proc_mock(
            stdout_lines=[
                "out_time_us=15000000\n",   # 25%
                "out_time_us=30000000\n",   # 50%
                "out_time_us=45000000\n",   # 75%
                "progress=end\n",
            ],
            returncode=0,
        )

        cfg = AudioEditConfig(eq_enabled=True)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0), \
             patch("os.replace"):
            editor.process(audio_file, cfg, on_progress=progress)

        valores = [c.args[0] for c in progress.call_args_list]
        # 3 progressos parciais + 1 final = pelo menos 4 calls
        assert len(valores) >= 4
        assert valores[-1] == 1.0
        # valores intermediários crescentes
        assert any(0.2 <= v <= 0.3 for v in valores)
        assert any(0.45 <= v <= 0.55 for v in valores)
        assert any(0.7 <= v <= 0.8 for v in valores)

    def test_returncode_nao_zero_levanta_runtime_error(self, audio_file):
        editor = FfmpegAudioEditor()
        proc = _make_proc_mock(stdout_lines=[], returncode=1)

        cfg = AudioEditConfig(eq_enabled=True)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0), \
             patch("os.replace"):
            with pytest.raises(RuntimeError):
                editor.process(audio_file, cfg)

    def test_erro_inclui_ultimas_linhas_do_ffmpeg(self, audio_file):
        """
        Quando ffmpeg falha (rc != 0), a mensagem do RuntimeError deve incluir
        as últimas linhas do stdout (que tem stderr redirecionado) — sem isso
        o usuário relata 'deu erro' e não temos como debugar.
        """
        editor = FfmpegAudioEditor()
        proc = _make_proc_mock(
            stdout_lines=[
                "frame=    0 fps=0.0 q=-0.0 size=       0kB time=00:00:00.00\n",
                "[mp3 @ 0x12345] Header missing\n",
                "Error opening filters!\n",
            ],
            returncode=1,
        )

        cfg = AudioEditConfig(eq_enabled=True)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0), \
             patch("os.replace"):
            with pytest.raises(RuntimeError) as exc_info:
                editor.process(audio_file, cfg)

        msg = str(exc_info.value)
        assert "Header missing" in msg
        assert "Error opening filters" in msg

    def test_erro_limita_em_20_ultimas_linhas(self, audio_file):
        """O accumulator é deque(maxlen=20) — só deve guardar as 20 finais."""
        editor = FfmpegAudioEditor()
        # 30 linhas de "ruído" + 1 final identificável
        stdout_lines = [f"linha_irrelevante_{i}\n" for i in range(30)]
        stdout_lines.append("ESSA_LINHA_DEVE_APARECER\n")

        proc = _make_proc_mock(stdout_lines=stdout_lines, returncode=1)
        cfg = AudioEditConfig(eq_enabled=True)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0), \
             patch("os.replace"):
            with pytest.raises(RuntimeError) as exc_info:
                editor.process(audio_file, cfg)

        msg = str(exc_info.value)
        assert "ESSA_LINHA_DEVE_APARECER" in msg
        # Linhas mais antigas que as 20 finais NÃO aparecem
        assert "linha_irrelevante_0" not in msg
        assert "linha_irrelevante_5" not in msg

    def test_logs_emitidos_um_por_etapa_habilitada(self, audio_file):
        editor = FfmpegAudioEditor()
        log = MagicMock()
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)

        cfg = AudioEditConfig(
            noise_reduction_enabled=True,
            eq_enabled=True,
            fade_in_enabled=True,
            intro_path="/tmp/intro.mp3",
        )
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0), \
             patch("os.replace"):
            editor.process(audio_file, cfg, on_log=log)

        msgs = " ".join(c.args[0] for c in log.call_args_list).lower()
        assert "redução de ruído" in msgs
        assert "equalização" in msgs
        assert "fade" in msgs
        assert "vinheta" in msgs
        assert "concluído" in msgs

    def test_cancelamento_levanta_operacao_cancelada(self, audio_file):
        editor = FfmpegAudioEditor()
        cancel_event = threading.Event()
        cancel_event.set()  # já cancelado antes de começar

        cfg = AudioEditConfig(eq_enabled=True)
        with patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0):
            with pytest.raises(OperacaoCancelada):
                editor.process(audio_file, cfg, cancel_event=cancel_event)

    def test_cancelamento_durante_stdout_loop(self, audio_file):
        editor = FfmpegAudioEditor()
        cancel_event = threading.Event()

        # Generator que sinaliza o cancelamento depois da primeira linha
        def stdout_gen():
            yield "out_time_us=10000000\n"
            cancel_event.set()
            yield "out_time_us=20000000\n"  # esta deve disparar OperacaoCancelada

        proc = MagicMock()
        proc.stdout = stdout_gen()
        proc.wait = MagicMock(return_value=0)
        proc.poll = MagicMock(return_value=None)
        proc.terminate = MagicMock()

        cfg = AudioEditConfig(eq_enabled=True)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0), \
             patch("os.replace") as mock_replace:
            with pytest.raises(OperacaoCancelada):
                editor.process(audio_file, cfg, cancel_event=cancel_event)

        # Não deve substituir o arquivo se foi cancelado
        mock_replace.assert_not_called()

    def test_tmp_e_removido_em_caso_de_falha(self, audio_file, tmp_path):
        editor = FfmpegAudioEditor()
        # cria um .tmp para simular o estado pós-falha
        tmp_file = tmp_path / "trecho.mp3.tmp"
        tmp_file.write_bytes(b"partial")

        proc = _make_proc_mock(stdout_lines=[], returncode=1)
        cfg = AudioEditConfig(eq_enabled=True)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0), \
             patch("os.replace"):
            with pytest.raises(RuntimeError):
                editor.process(audio_file, cfg)

        assert not tmp_file.exists()


# ===========================================================================
# Implementa o Protocol IAudioEditor
# ===========================================================================

class TestImplementaProtocol:
    def test_e_instance_de_iaudio_editor(self):
        from domain.ports import IAudioEditor
        assert isinstance(FfmpegAudioEditor(), IAudioEditor)


# ===========================================================================
# _build_filter_complex — Nivelamento de volume (loudnorm)
# ===========================================================================

class TestBuildFilterComplexVolumeNorm:
    def _editor(self):
        return FfmpegAudioEditor()

    def test_loudnorm_na_cadeia_principal_sem_vinhetas(self):
        cfg = AudioEditConfig(volume_norm_enabled=True, volume_norm_lufs=-16.0)
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "loudnorm=I=-16.0:TP=-1.5:LRA=11" in fc

    def test_loudnorm_lufs_customizado(self):
        cfg = AudioEditConfig(volume_norm_enabled=True, volume_norm_lufs=-20.0)
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "loudnorm=I=-20.0:TP=-1.5:LRA=11" in fc

    def test_loudnorm_antes_de_aresample_na_cadeia_principal(self):
        cfg = AudioEditConfig(volume_norm_enabled=True, volume_norm_lufs=-16.0)
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        i_loudnorm  = fc.index("loudnorm")
        i_aresample = fc.index("aresample=")
        assert i_loudnorm < i_aresample

    def test_loudnorm_ausente_quando_desabilitado(self):
        cfg = AudioEditConfig(volume_norm_enabled=False, eq_enabled=True)
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "loudnorm" not in fc

    def test_loudnorm_aplicado_na_intro(self):
        cfg = AudioEditConfig(
            volume_norm_enabled=True, volume_norm_lufs=-16.0,
            intro_path="/tmp/intro.mp3",
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[1:a]loudnorm=I=-16.0:TP=-1.5:LRA=11,aresample=44100[intro]" in fc

    def test_loudnorm_aplicado_na_outro(self):
        cfg = AudioEditConfig(
            volume_norm_enabled=True, volume_norm_lufs=-16.0,
            outro_path="/tmp/outro.mp3",
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[1:a]loudnorm=I=-16.0:TP=-1.5:LRA=11,aresample=44100[outro]" in fc

    def test_loudnorm_em_intro_e_outro_com_indices_corretos(self):
        cfg = AudioEditConfig(
            volume_norm_enabled=True, volume_norm_lufs=-16.0,
            intro_path="/tmp/i.mp3",
            outro_path="/tmp/o.mp3",
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[1:a]loudnorm=I=-16.0:TP=-1.5:LRA=11,aresample=44100[intro]" in fc
        assert "[2:a]loudnorm=I=-16.0:TP=-1.5:LRA=11,aresample=44100[outro]" in fc

    def test_sem_loudnorm_nas_vinhetas_quando_desabilitado(self):
        cfg = AudioEditConfig(
            volume_norm_enabled=False,
            intro_path="/tmp/i.mp3",
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[1:a]aresample=44100[intro]" in fc
        assert "loudnorm" not in fc
