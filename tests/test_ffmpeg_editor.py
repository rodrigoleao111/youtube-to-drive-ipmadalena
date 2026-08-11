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

    def test_logs_emitidos_um_por_etapa_habilitada(self, audio_file, tmp_path):
        editor = FfmpegAudioEditor()
        log = MagicMock()
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)

        # A vinheta precisa EXISTIR: um caminho inválido seria descartado por
        # _drop_missing_assets e o log de concatenação nunca sairia.
        intro = tmp_path / "intro.mp3"
        intro.write_bytes(b"fake")

        cfg = AudioEditConfig(
            noise_reduction_enabled=True,
            eq_enabled=True,
            fade_in_enabled=True,
            intro_path=str(intro),
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
        assert "concatenando vinhetas" in msgs
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

    def test_loudnorm_linear_true_na_cadeia_principal(self):
        """Melhoria de performance: loudnorm deve usar linear=true."""
        cfg = AudioEditConfig(volume_norm_enabled=True, volume_norm_lufs=-16.0)
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "loudnorm=I=-16.0:TP=-1.5:LRA=11:linear=true:print_format=none" in fc

    def test_loudnorm_aplicado_na_intro(self):
        _loudnorm = "loudnorm=I=-16.0:TP=-1.5:LRA=11:linear=true:print_format=none"
        cfg = AudioEditConfig(
            volume_norm_enabled=True, volume_norm_lufs=-16.0,
            intro_path="/tmp/intro.mp3",
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert f"[1:a]{_loudnorm},aresample=44100[intro]" in fc

    def test_loudnorm_aplicado_na_outro(self):
        _loudnorm = "loudnorm=I=-16.0:TP=-1.5:LRA=11:linear=true:print_format=none"
        cfg = AudioEditConfig(
            volume_norm_enabled=True, volume_norm_lufs=-16.0,
            outro_path="/tmp/outro.mp3",
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert f"[1:a]{_loudnorm},aresample=44100[outro]" in fc

    def test_loudnorm_em_intro_e_outro_com_indices_corretos(self):
        _loudnorm = "loudnorm=I=-16.0:TP=-1.5:LRA=11:linear=true:print_format=none"
        cfg = AudioEditConfig(
            volume_norm_enabled=True, volume_norm_lufs=-16.0,
            intro_path="/tmp/i.mp3",
            outro_path="/tmp/o.mp3",
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert f"[1:a]{_loudnorm},aresample=44100[intro]" in fc
        assert f"[2:a]{_loudnorm},aresample=44100[outro]" in fc

    def test_sem_loudnorm_nas_vinhetas_quando_desabilitado(self):
        cfg = AudioEditConfig(
            volume_norm_enabled=False,
            intro_path="/tmp/i.mp3",
        )
        fc, _ = self._editor()._build_filter_complex(cfg, input_dur=60.0)
        assert "[1:a]aresample=44100[intro]" in fc
        assert "loudnorm" not in fc


# ===========================================================================
# Música de fundo integrada à passagem única
# ===========================================================================

class TestBuildFilterComplexBgMusic:
    """Trecho de música de fundo do filter graph (passagem única)."""

    _BG = "/tmp/music.mp3"

    def _editor(self):
        return FfmpegAudioEditor()

    def _cfg(self, **kw):
        defaults = dict(
            bg_music_path=self._BG,
            bg_music_enabled=True,
            bg_music_volume=0.12,
            bg_music_delay=0.0,
            bg_music_fade_in=3.0,
            bg_music_fade_out=6.0,
        )
        defaults.update(kw)
        return AudioEditConfig(**defaults)

    def _fc(self, cfg, input_dur=60.0, total_dur=60.0, bg_dur=0.0):
        fc, _ = self._editor()._build_filter_complex(
            cfg, input_dur, total_dur, bg_enabled=True, bg_dur=bg_dur
        )
        return fc

    def test_volume_aplicado_na_musica(self):
        assert "volume=0.1500" in self._fc(self._cfg(bg_music_volume=0.15))

    def test_atrim_usa_episodio_mais_intro_musical(self):
        # 60 s de episódio + 5 s de intro musical → 65 s
        assert "atrim=end=65.000" in self._fc(self._cfg(bg_music_delay=5.0))

    def test_adelay_atrasa_o_episodio_nao_a_musica(self):
        fc = self._fc(self._cfg(bg_music_delay=3.0))
        assert "[episode]adelay=3000|3000[ep_delayed]" in fc

    def test_sem_adelay_quando_delay_zero(self):
        assert "adelay" not in self._fc(self._cfg(bg_music_delay=0.0))

    def test_fade_in_e_fade_out_da_musica(self):
        fc = self._fc(self._cfg(bg_music_fade_in=4.0, bg_music_fade_out=6.0))
        assert "afade=t=in:st=0:d=4.00" in fc
        # fim em 60 s → fade out começa em 54 s
        assert "afade=t=out:st=54.000:d=6.00" in fc

    def test_amix_usa_duration_first_com_episodio_na_frente(self):
        """
        `duration=first` + episódio como primeiro input faz a saída ter sempre
        o comprimento do episódio — com a música em loop infinito ou com uma
        faixa curta que acaba antes. Regressão: shortest/longest dependia de
        bg e episódio terem a mesma duração medida.
        """
        fc = self._fc(self._cfg())
        assert "[episode][bg]amix=inputs=2:duration=first" in fc

    def test_duration_first_independe_do_loop(self):
        assert "duration=first" in self._fc(self._cfg(bg_music_loop=True))
        assert "duration=first" in self._fc(self._cfg(bg_music_loop=False))

    def test_indice_do_input_de_bg_vem_depois_das_vinhetas(self):
        fc = self._fc(self._cfg(intro_path="/tmp/i.mp3", outro_path="/tmp/o.mp3"))
        # 0=principal, 1=intro, 2=outro, 3=música
        assert "[3:a]atrim=end=" in fc

    # -- duração desconhecida (ffprobe e ffmpeg indisponíveis) --------------

    def test_sem_duracao_nao_corta_a_musica(self):
        """
        Regressão do bug 'a música sumiu após 8 s': com duração 0 o atrim caía
        em `end=<intro musical>` e a música morria logo depois da abertura.
        """
        fc = self._fc(self._cfg(bg_music_delay=8.0), input_dur=0.0, total_dur=0.0)
        assert "atrim" not in fc
        assert "volume=0.1200" in fc
        # o episódio segue sendo atrasado normalmente
        assert "adelay=8000" in fc

    def test_sem_duracao_ainda_aplica_fade_in(self):
        fc = self._fc(self._cfg(bg_music_fade_in=3.0),
                      input_dur=0.0, total_dur=0.0)
        assert "afade=t=in:st=0:d=3.00" in fc

    def test_sem_duracao_pula_fade_out_da_musica(self):
        fc = self._fc(self._cfg(bg_music_fade_out=6.0),
                      input_dur=0.0, total_dur=0.0)
        assert "afade=t=out" not in fc

    # -- fades que não cabem na saída --------------------------------------

    def test_fade_out_maior_que_o_audio_e_encurtado_nao_descartado(self):
        """
        Antes: `fade_out_st > 0` era falso e o fade out sumia do filter graph
        inteiro — a música parava seca no volume cheio.
        """
        fc = self._fc(self._cfg(bg_music_fade_in=0.0, bg_music_fade_out=6.0),
                      input_dur=4.0, total_dur=4.0)
        assert "afade=t=out:st=0.000:d=4.00" in fc

    def test_fade_in_maior_que_o_audio_usa_o_audio_inteiro(self):
        """Antes era cortado em 40 % da saída (1.6 s de 4 s), sem avisar."""
        fc = self._fc(self._cfg(bg_music_fade_in=10.0, bg_music_fade_out=0.0),
                      input_dur=4.0, total_dur=4.0)
        assert "afade=t=in:st=0:d=4.00" in fc

    def test_fades_que_nao_cabem_sao_reduzidos_proporcionalmente(self):
        # pedidos 3 + 6 = 9 s numa saída de 8 s → fator 8/9
        fc = self._fc(self._cfg(bg_music_fade_in=3.0, bg_music_fade_out=6.0),
                      input_dur=8.0, total_dur=8.0)
        assert "afade=t=in:st=0:d=2.67" in fc
        assert "afade=t=out:st=2.667:d=5.33" in fc

    def test_rampas_nao_se_sobrepoem(self):
        """
        O fade out não pode começar antes do fade in terminar — senão a música
        nunca alcança o volume configurado.
        """
        fc = self._fc(self._cfg(bg_music_fade_in=5.0, bg_music_fade_out=5.0),
                      input_dur=6.0, total_dur=6.0)
        d_in = float(fc.split("afade=t=in:st=0:d=")[1].split(",")[0].split("[")[0])
        st_out = float(fc.split("afade=t=out:st=")[1].split(":")[0])
        assert st_out >= d_in - 0.01


# ===========================================================================
# Fim efetivo da música — âncora do fade out
# ===========================================================================

class TestBgEnd:
    """
    Onde a música realmente termina dentro da saída.

    Regressão de produção (log de 31/08/2025): faixa de poucos minutos, loop
    DESLIGADO, episódio de 48 min. O fade out saía com `st=2904` — o fim do
    episódio — mas a música já tinha acabado muito antes: a faixa cortava seca
    no meio e o fade out nunca era ouvido.
    """

    def _cfg(self, loop):
        return AudioEditConfig(bg_music_path="/tmp/m.mp3", bg_music_enabled=True,
                               bg_music_loop=loop)

    def _end(self, loop, output_dur, bg_dur):
        return FfmpegAudioEditor._bg_end(self._cfg(loop), output_dur, bg_dur)

    def test_com_loop_cobre_a_saida_inteira(self):
        assert self._end(True, 2912.0, 120.0) == 2912.0

    def test_sem_loop_termina_na_duracao_da_faixa(self):
        assert self._end(False, 2912.0, 120.0) == 120.0

    def test_sem_loop_faixa_mais_longa_que_a_saida_para_na_saida(self):
        assert self._end(False, 600.0, 3600.0) == 600.0

    def test_sem_loop_e_sem_medida_da_faixa_assume_o_fim_da_saida(self):
        assert self._end(False, 600.0, 0.0) == 600.0

    def test_episodio_desconhecido_mas_faixa_medida_usa_a_faixa(self):
        """A faixa ainda é uma âncora válida sem saber a duração do episódio."""
        assert self._end(False, 0.0, 120.0) == 120.0

    def test_tudo_desconhecido_retorna_zero(self):
        assert self._end(False, 0.0, 0.0) == 0.0
        assert self._end(True, 0.0, 0.0) == 0.0


class TestFadeOutAncoradoNaMusica:

    _BG = "/tmp/music.mp3"

    def _fc(self, *, loop, bg_dur, fade_out=8.0, output=2912.0):
        cfg = AudioEditConfig(
            bg_music_path=self._BG, bg_music_enabled=True,
            bg_music_fade_in=3.0, bg_music_fade_out=fade_out,
            bg_music_loop=loop,
        )
        fc, _ = FfmpegAudioEditor()._build_filter_complex(
            cfg, output, output, bg_enabled=True, bg_dur=bg_dur
        )
        return fc

    def test_sem_loop_fade_out_fecha_no_fim_da_faixa(self):
        # faixa de 120 s → fade out de 8 s começa em 112 s
        fc = self._fc(loop=False, bg_dur=120.0)
        assert "afade=t=out:st=112.000:d=8.00" in fc

    def test_com_loop_fade_out_fecha_no_fim_do_episodio(self):
        fc = self._fc(loop=True, bg_dur=120.0)
        assert "afade=t=out:st=2904.000:d=8.00" in fc

    def test_fade_in_nao_muda_com_o_loop(self):
        for loop in (True, False):
            assert "afade=t=in:st=0:d=3.00" in self._fc(loop=loop, bg_dur=120.0)

    def test_sem_loop_fades_cabem_no_espaco_da_faixa(self):
        """
        Faixa de 8 s com fade in 3 + fade out 8 pedidos: o orçamento é a faixa
        (8 s), não o episódio inteiro.
        """
        fc = self._fc(loop=False, bg_dur=8.0, fade_out=8.0)
        assert "afade=t=in:st=0:d=2.18" in fc     # 8 * 3/11
        assert "afade=t=out:st=2.182:d=5.82" in fc

    def test_log_avisa_quando_a_faixa_acaba_antes(self, audio_file):
        cfg = AudioEditConfig(
            bg_music_path=self._BG, bg_music_enabled=True,
            bg_music_fade_out=8.0, bg_music_loop=False,
        )
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        logs = []
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration",
                          side_effect=lambda p: 120.0 if p == self._BG else 2900.0), \
             patch("os.path.isfile", return_value=True), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg, on_log=logs.append)

        msgs = " ".join(logs)
        assert "loop desligado" in msgs
        assert "Repetir em loop" in msgs

    def test_sem_aviso_quando_a_faixa_cobre_o_episodio(self, audio_file):
        cfg = AudioEditConfig(
            bg_music_path=self._BG, bg_music_enabled=True,
            bg_music_fade_out=8.0, bg_music_loop=False,
        )
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        logs = []
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=600.0), \
             patch("os.path.isfile", return_value=True), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg, on_log=logs.append)

        assert "loop desligado" not in " ".join(logs)

    def test_duracao_da_musica_e_medida_uma_vez(self, audio_file):
        cfg = AudioEditConfig(
            bg_music_path=self._BG, bg_music_enabled=True, bg_music_loop=False,
        )
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration",
                          return_value=120.0) as probe, \
             patch("os.path.isfile", return_value=True), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg)

        medidos = [c.args[0] for c in probe.call_args_list]
        assert medidos.count(self._BG) == 1


# ===========================================================================
# _fit_bg_fades — orçamento de fade da música
# ===========================================================================

class TestFitBgFades:

    def _fit(self, fi, fo, dur):
        return FfmpegAudioEditor._fit_bg_fades(fi, fo, dur)

    def test_fades_que_cabem_ficam_intactos(self):
        assert self._fit(3.0, 6.0, 60.0) == (3.0, 6.0)

    def test_soma_exata_fica_intacta(self):
        assert self._fit(4.0, 6.0, 10.0) == (4.0, 6.0)

    def test_reducao_mantem_a_proporcao_e_preenche_a_saida(self):
        fi, fo = self._fit(3.0, 6.0, 8.0)
        assert fi == pytest.approx(8 * 3 / 9)
        assert fo == pytest.approx(8 * 6 / 9)
        assert fi + fo == pytest.approx(8.0)
        # proporção preservada (fade out continua sendo o dobro do fade in)
        assert fo / fi == pytest.approx(2.0)

    def test_somente_fade_out_ocupa_a_saida_inteira(self):
        assert self._fit(0.0, 6.0, 4.0) == (0.0, 4.0)

    def test_somente_fade_in_ocupa_a_saida_inteira(self):
        assert self._fit(10.0, 0.0, 4.0) == (4.0, 0.0)

    def test_sem_duracao_zera_o_fade_out(self):
        assert self._fit(3.0, 6.0, 0.0) == (3.0, 0.0)

    def test_valores_negativos_viram_zero(self):
        assert self._fit(-2.0, -5.0, 30.0) == (0.0, 0.0)

    def test_zero_zero_permanece_zero(self):
        assert self._fit(0.0, 0.0, 30.0) == (0.0, 0.0)


# ===========================================================================
# Guardas de duração desconhecida no áudio principal
# ===========================================================================

class TestDuracaoDesconhecida:

    def test_fade_out_e_pulado_quando_duracao_e_zero(self):
        """
        Sem duração, `st` cairia em 0 e o afade silenciaria o episódio inteiro
        a partir do segundo 3 — pior que não aplicar o efeito.
        """
        cfg = AudioEditConfig(fade_out_enabled=True, fade_out_secs=3.0)
        fc, _ = FfmpegAudioEditor()._build_filter_complex(cfg, input_dur=0.0)
        assert "afade=t=out" not in fc

    def test_fade_in_continua_sendo_aplicado(self):
        """fade in é ancorado no início — não depende de saber a duração."""
        cfg = AudioEditConfig(fade_in_enabled=True, fade_in_secs=2.0)
        fc, _ = FfmpegAudioEditor()._build_filter_complex(cfg, input_dur=0.0)
        assert "afade=t=in:st=0:d=2.0" in fc

    def test_aviso_no_log_quando_duracao_desconhecida(self, audio_file):
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        logs = []
        cfg = AudioEditConfig(eq_enabled=True)
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=0.0), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg, on_log=logs.append)
        assert any("duração" in m.lower() for m in logs)


# ===========================================================================
# _probe_duration — ffprobe com fallback para o ffmpeg
# ===========================================================================

class TestProbeDuration:

    def test_usa_ffprobe_quando_disponivel(self):
        ed = FfmpegAudioEditor()
        with patch.object(FfmpegAudioEditor, "_run_probe") as run:
            run.return_value = MagicMock(returncode=0, stdout="123.45\n", stderr="")
            assert ed._probe_duration("/tmp/a.mp3") == pytest.approx(123.45)
        assert run.call_count == 1     # não precisou do fallback

    def test_cai_para_ffmpeg_quando_ffprobe_indisponivel(self):
        """
        O bundle do PyInstaller já saiu sem `ffprobe.exe`; sem este fallback
        toda duração virava 0 e o pipeline se autodestruía.
        """
        ed = FfmpegAudioEditor()
        saida_ffmpeg = (
            "Input #0, mp3, from 'a.mp3':\n"
            "  Duration: 00:41:07.25, start: 0.000000, bitrate: 192 kb/s\n"
        )

        def _fake(cmd):
            if "ffprobe" in cmd[0]:
                raise FileNotFoundError("ffprobe.exe não encontrado")
            return MagicMock(returncode=1, stdout="", stderr=saida_ffmpeg)

        with patch.object(FfmpegAudioEditor, "_run_probe", side_effect=_fake):
            dur = ed._probe_duration("/tmp/a.mp3")
        # 41 min 7,25 s = 2467,25 s
        assert dur == pytest.approx(2467.25)

    def test_retorna_zero_quando_nenhum_dos_dois_funciona(self):
        ed = FfmpegAudioEditor()
        with patch.object(FfmpegAudioEditor, "_run_probe",
                          side_effect=FileNotFoundError("nada")):
            assert ed._probe_duration("/tmp/a.mp3") == 0.0

    def test_ffprobe_com_saida_vazia_cai_para_ffmpeg(self):
        ed = FfmpegAudioEditor()

        def _fake(cmd):
            if "ffprobe" in cmd[0]:
                return MagicMock(returncode=0, stdout="\n", stderr="")
            return MagicMock(returncode=1, stdout="",
                             stderr="  Duration: 00:00:30.00, start: 0.0\n")

        with patch.object(FfmpegAudioEditor, "_run_probe", side_effect=_fake):
            assert ed._probe_duration("/tmp/a.mp3") == pytest.approx(30.0)


# ===========================================================================
# Saneamento de assets ausentes
# ===========================================================================

class TestDropMissingAssets:

    def _logs_e_cfg(self, cfg):
        logs = []
        novo = FfmpegAudioEditor()._drop_missing_assets(cfg, logs.append)
        return novo, logs

    def test_vinheta_inexistente_e_descartada(self):
        cfg = AudioEditConfig(intro_path="/nao/existe/intro.mp3", eq_enabled=True)
        novo, logs = self._logs_e_cfg(cfg)
        assert novo.intro_path is None
        assert any("não encontrada" in m.lower() for m in logs)

    def test_outro_inexistente_e_descartada(self):
        cfg = AudioEditConfig(outro_path="/nao/existe/outro.mp3")
        novo, _ = self._logs_e_cfg(cfg)
        assert novo.outro_path is None

    def test_musica_inexistente_desabilita_bg(self):
        cfg = AudioEditConfig(bg_music_enabled=True,
                              bg_music_path="/nao/existe/mus.mp3")
        novo, logs = self._logs_e_cfg(cfg)
        assert novo.bg_music_enabled is False
        assert any("música de fundo" in m.lower() for m in logs)

    def test_arquivos_existentes_sao_preservados(self, tmp_path):
        intro = tmp_path / "intro.mp3"
        intro.write_bytes(b"x")
        cfg = AudioEditConfig(intro_path=str(intro))
        novo, logs = self._logs_e_cfg(cfg)
        assert novo.intro_path == str(intro)
        assert novo is cfg          # sem mudanças → mesma instância
        assert logs == []

    def test_process_vira_no_op_quando_unica_etapa_sumiu(self, audio_file):
        """Vinheta apagada era a única etapa: nada a fazer, sem chamar ffmpeg."""
        cfg = AudioEditConfig(intro_path="/nao/existe/intro.mp3")
        with patch("infrastructure.audio.ffmpeg_editor.start_process") as sp, \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=60.0):
            FfmpegAudioEditor().process(audio_file, cfg)
        sp.assert_not_called()


# ===========================================================================
# process() — integração da música de fundo em uma única passagem
# ===========================================================================

class TestProcessBgMusic:

    _BG = "/tmp/music.mp3"

    def _run(self, cfg, audio_file, probe=60.0):
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        captured: list = []
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   side_effect=lambda cmd, **kw: (captured.append(cmd[:]), proc)[1]), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=probe), \
             patch("os.path.isfile", return_value=True), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg)
        return captured

    def test_uma_unica_chamada_ao_ffmpeg(self, audio_file):
        cfg = AudioEditConfig(eq_enabled=True, bg_music_path=self._BG,
                              bg_music_enabled=True)
        captured = self._run(cfg, audio_file)
        assert len(captured) == 1
        assert self._BG in captured[0]
        fc = captured[0][captured[0].index("-filter_complex") + 1]
        assert "amix" in fc

    def test_stream_loop_presente_apenas_com_loop_ligado(self, audio_file):
        cfg_on = AudioEditConfig(bg_music_path=self._BG, bg_music_enabled=True,
                                 bg_music_loop=True)
        cfg_off = AudioEditConfig(bg_music_path=self._BG, bg_music_enabled=True,
                                  bg_music_loop=False)
        assert "-stream_loop" in self._run(cfg_on, audio_file)[0]
        assert "-stream_loop" not in self._run(cfg_off, audio_file)[0]

    def test_stream_loop_vem_imediatamente_antes_do_input_da_musica(self, audio_file):
        """`-stream_loop` é opção de INPUT: precisa preceder o -i da música."""
        cfg = AudioEditConfig(bg_music_path=self._BG, bg_music_enabled=True,
                              bg_music_loop=True, intro_path="/tmp/i.mp3")
        cmd = self._run(cfg, audio_file)[0]
        i = cmd.index("-stream_loop")
        assert cmd[i + 1] == "-1"
        assert cmd[i + 2] == "-i"
        assert cmd[i + 3] == self._BG

    def test_sem_amix_quando_bg_desabilitado(self, audio_file):
        cfg = AudioEditConfig(eq_enabled=True, bg_music_enabled=False)
        cmd = self._run(cfg, audio_file)[0]
        fc = cmd[cmd.index("-filter_complex") + 1]
        assert "amix" not in fc

    def test_sobreposicao_maior_que_a_vinheta_e_limitada(self, audio_file):
        """
        `acrossfade=d` maior que a vinheta engole a vinheta inteira E o começo
        do sermão (ffmpeg aceita sem reclamar). O limite é a peça mais curta.
        """
        cfg = AudioEditConfig(intro_path="/tmp/i.mp3", intro_overlap_secs=10.0)
        logs = []
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        captured: list = []
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   side_effect=lambda cmd, **kw: (captured.append(cmd[:]), proc)[1]), \
             patch.object(FfmpegAudioEditor, "_probe_duration",
                          side_effect=lambda p: 4.0 if p == "/tmp/i.mp3" else 60.0), \
             patch("os.path.isfile", return_value=True), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg, on_log=logs.append)

        fc = captured[0][captured[0].index("-filter_complex") + 1]
        assert "acrossfade=d=4.0" in fc
        assert any("sobreposição" in m.lower() for m in logs)

    def test_sobreposicao_dentro_do_limite_nao_e_alterada(self, audio_file):
        cfg = AudioEditConfig(intro_path="/tmp/i.mp3", intro_overlap_secs=2.0)
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        captured: list = []
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   side_effect=lambda cmd, **kw: (captured.append(cmd[:]), proc)[1]), \
             patch.object(FfmpegAudioEditor, "_probe_duration",
                          side_effect=lambda p: 4.0 if p == "/tmp/i.mp3" else 60.0), \
             patch("os.path.isfile", return_value=True), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg)

        fc = captured[0][captured[0].index("-filter_complex") + 1]
        assert "acrossfade=d=2.0" in fc

    def test_log_informa_fades_efetivos_quando_reduzidos(self, audio_file):
        cfg = AudioEditConfig(
            bg_music_path=self._BG, bg_music_enabled=True,
            bg_music_fade_in=3.0, bg_music_fade_out=6.0,
        )
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        logs = []
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=8.0), \
             patch("os.path.isfile", return_value=True), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg, on_log=logs.append)

        msgs = " ".join(logs)
        assert "reduzidos" in msgs
        # o log principal mostra os valores EFETIVOS, não os pedidos
        assert "fade‑in=2.7s" in msgs
        assert "fade‑out=5.3s" in msgs

    def test_log_nao_menciona_reducao_quando_os_fades_cabem(self, audio_file):
        cfg = AudioEditConfig(
            bg_music_path=self._BG, bg_music_enabled=True,
            bg_music_fade_in=3.0, bg_music_fade_out=6.0,
        )
        proc = _make_proc_mock(stdout_lines=["progress=end\n"], returncode=0)
        logs = []
        with patch("infrastructure.audio.ffmpeg_editor.start_process",
                   return_value=proc), \
             patch.object(FfmpegAudioEditor, "_probe_duration", return_value=600.0), \
             patch("os.path.isfile", return_value=True), \
             patch("os.replace"):
            FfmpegAudioEditor().process(audio_file, cfg, on_log=logs.append)

        assert "reduzidos" not in " ".join(logs)

    def test_duracao_total_desconta_as_sobreposicoes(self, audio_file):
        """
        Com acrossfade a saída é menor que a soma das peças; sem descontar as
        sobreposições, o fade out da música cairia depois do fim real.
        """
        cfg = AudioEditConfig(
            bg_music_path=self._BG, bg_music_enabled=True,
            intro_path="/tmp/i.mp3", outro_path="/tmp/o.mp3",
            intro_overlap_secs=2.0, outro_overlap_secs=3.0,
        )
        # cada peça mede 10 s (probe fixo) → 30 - 2 - 3 = 25 s
        cmd = self._run(cfg, audio_file, probe=10.0)[0]
        fc = cmd[cmd.index("-filter_complex") + 1]
        assert "atrim=end=25.000" in fc

