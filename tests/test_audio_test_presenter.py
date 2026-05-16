"""
Testes para presentation/audio_test_presenter.py.

AudioTestPresenter é sync — sem QThread, sem Qt — então os testes são puros
(MagicMock + tmp_path para I/O real de arquivos).
"""

from __future__ import annotations

import os
import threading
from unittest.mock import MagicMock

import pytest

from domain.entities import AudioEditConfig, AudioFile
from domain.exceptions import OperacaoCancelada
from presentation.audio_test_presenter import AudioTestPresenter


# ---------------------------------------------------------------------------
# Fixtures e helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_file(tmp_path):
    """Cria um arquivo de exemplo (placeholder de áudio)."""
    p = tmp_path / "exemplo.mp3"
    p.write_bytes(b"audio fake content")
    return str(p)


@pytest.fixture
def preview_path(tmp_path):
    """Caminho de saída do preview (em pasta 'downloads' simulada)."""
    out_dir = tmp_path / "downloads"
    return str(out_dir / "_test_preview.mp3")


# ===========================================================================
# Construção e Protocol
# ===========================================================================

class TestAudioTestPresenterConstrucao:
    def test_e_dataclass_com_editor(self):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        assert p.editor is editor


# ===========================================================================
# Validação de entrada
# ===========================================================================

class TestSampleFileValidation:
    def test_levanta_se_sample_path_vazio(self, preview_path):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        with pytest.raises(FileNotFoundError):
            p.execute("", preview_path, AudioEditConfig())
        editor.process.assert_not_called()

    def test_levanta_se_sample_path_nao_existe(self, preview_path):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        with pytest.raises(FileNotFoundError):
            p.execute("/path/inexistente.mp3", preview_path, AudioEditConfig())
        editor.process.assert_not_called()


# ===========================================================================
# No-op fast path (sem filtros habilitados)
# ===========================================================================

class TestNoOpFastPath:
    def test_copia_sample_para_preview_sem_chamar_editor(self, sample_file, preview_path):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)

        result = p.execute(sample_file, preview_path, AudioEditConfig())

        assert result == preview_path
        assert os.path.exists(preview_path)
        editor.process.assert_not_called()

    def test_preview_tem_mesmo_conteudo_do_sample_no_no_op(
        self, sample_file, preview_path
    ):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        p.execute(sample_file, preview_path, AudioEditConfig())
        assert open(preview_path, "rb").read() == open(sample_file, "rb").read()

    def test_progresso_chega_em_1_no_no_op(self, sample_file, preview_path):
        editor   = MagicMock()
        progress = MagicMock()
        p = AudioTestPresenter(editor=editor)
        p.execute(sample_file, preview_path, AudioEditConfig(),
                  on_progress=progress)
        assert progress.call_args_list[-1].args[0] == 1.0

    def test_emite_log_de_no_op(self, sample_file, preview_path):
        editor = MagicMock()
        log    = MagicMock()
        p = AudioTestPresenter(editor=editor)
        p.execute(sample_file, preview_path, AudioEditConfig(), on_log=log)
        msgs = " ".join(c.args[0] for c in log.call_args_list).lower()
        assert "nenhum filtro" in msgs

    def test_cria_pasta_de_destino(self, sample_file, tmp_path):
        # Pasta ainda não existe
        out_dir = tmp_path / "novos" / "downloads"
        preview_path = str(out_dir / "_test_preview.mp3")
        assert not out_dir.exists()

        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        p.execute(sample_file, preview_path, AudioEditConfig())

        assert out_dir.exists()
        assert os.path.exists(preview_path)


# ===========================================================================
# Pipeline habilitado (com filtros)
# ===========================================================================

class TestPipelineComFiltros:
    def test_chama_editor_com_audio_no_preview_path(self, sample_file, preview_path):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True)

        p.execute(sample_file, preview_path, cfg)

        editor.process.assert_called_once()
        args, _ = editor.process.call_args
        audio_arg = args[0]
        assert isinstance(audio_arg, AudioFile)
        # O AudioFile passado tem o caminho do PREVIEW (não o sample original)
        assert audio_arg.path == preview_path

    def test_audio_file_tem_video_id_test_marcador(self, sample_file, preview_path):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True)
        p.execute(sample_file, preview_path, cfg)
        args, _ = editor.process.call_args
        audio_arg = args[0]
        # Prefixo '_test_' permite cleanup_downloads ignorar como upload real
        assert audio_arg.video_id == "_test_"

    def test_passa_o_config_recebido(self, sample_file, preview_path):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True, fade_in_enabled=True, fade_in_secs=4.0)

        p.execute(sample_file, preview_path, cfg)

        args, _ = editor.process.call_args
        config_arg = args[1]
        assert config_arg is cfg

    def test_sample_original_nao_e_modificado(self, sample_file, preview_path):
        """O sample do usuário NÃO deve ser tocado — só o preview."""
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True)

        original = open(sample_file, "rb").read()
        p.execute(sample_file, preview_path, cfg)

        assert open(sample_file, "rb").read() == original

    def test_repassa_callbacks_para_o_editor(self, sample_file, preview_path):
        editor   = MagicMock()
        log      = MagicMock()
        progress = MagicMock()
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True)

        p.execute(
            sample_file, preview_path, cfg,
            on_log=log, on_progress=progress,
        )

        kwargs = editor.process.call_args.kwargs
        assert kwargs["on_log"] is log
        assert kwargs["on_progress"] is progress

    def test_repassa_cancel_event_para_o_editor(self, sample_file, preview_path):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True)
        ev = threading.Event()

        p.execute(sample_file, preview_path, cfg, cancel_event=ev)

        assert editor.process.call_args.kwargs["cancel_event"] is ev

    def test_propaga_operacao_cancelada(self, sample_file, preview_path):
        editor = MagicMock()
        editor.process.side_effect = OperacaoCancelada("cancelado")
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True)

        with pytest.raises(OperacaoCancelada):
            p.execute(sample_file, preview_path, cfg)

    def test_propaga_runtime_error_do_editor(self, sample_file, preview_path):
        editor = MagicMock()
        editor.process.side_effect = RuntimeError("ffmpeg falhou")
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True)

        with pytest.raises(RuntimeError):
            p.execute(sample_file, preview_path, cfg)

    def test_retorna_o_preview_path(self, sample_file, preview_path):
        editor = MagicMock()
        p = AudioTestPresenter(editor=editor)
        cfg = AudioEditConfig(eq_enabled=True)

        result = p.execute(sample_file, preview_path, cfg)
        assert result == preview_path
