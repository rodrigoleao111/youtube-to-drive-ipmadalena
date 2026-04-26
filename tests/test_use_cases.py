"""
Testes para application/use_cases.py.

Usa MagicMock para simular os ports do domínio (IVideoSource, IAudioDownloader,
ICloudStorage, IHistoryRepository). Sem acesso a disco, rede ou subprocess.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, call

import pytest

from application.use_cases import (
    DownloadSegmentsUseCase,
    ListVideosUseCase,
    UploadAudioUseCase,
)
from domain.entities import AudioFile, ProcessingResult, Segment, Video
from domain.exceptions import OperacaoCancelada, VideoNaoEncontrado


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_video(vid="abc123", title="Culto", date="20260419"):
    return Video(id=vid, title=title, upload_date=date)


def _make_segment(vid="abc123", title="Culto", start=None, end=None):
    return Segment(video_id=vid, title=title, start=start, end=end)


def _make_audio(path="/tmp/culto.mp3", title="Culto", vid="abc123"):
    return AudioFile(path=path, title=title, video_id=vid)


def _make_result(date_str="19/04/2026", uploaded=(), skipped=()):
    return ProcessingResult(date_str=date_str, uploaded_files=uploaded, skipped_files=skipped)


# ===========================================================================
# ListVideosUseCase
# ===========================================================================

class TestListVideosUseCase:

    def _uc(self, source=None):
        return ListVideosUseCase(source=source or MagicMock())

    # -----------------------------------------------------------------------
    # Delegação correta para o port
    # -----------------------------------------------------------------------

    def test_delega_para_source_list_videos(self):
        source = MagicMock()
        source.list_videos.return_value = []
        uc = ListVideosUseCase(source=source)
        uc.execute("19/04/2026", "https://canal")
        source.list_videos.assert_called_once()

    def test_repassa_date_str_e_channel_url(self):
        source = MagicMock()
        source.list_videos.return_value = []
        uc = ListVideosUseCase(source=source)
        uc.execute("19/04/2026", "https://canal.exemplo")
        args, kwargs = source.list_videos.call_args
        assert args[0] == "19/04/2026"
        assert args[1] == "https://canal.exemplo"

    def test_repassa_cancel_event(self):
        source = MagicMock()
        source.list_videos.return_value = []
        ev = threading.Event()
        uc = ListVideosUseCase(source=source)
        uc.execute("19/04/2026", "https://canal", cancel_event=ev)
        _, kwargs = source.list_videos.call_args
        assert kwargs["cancel_event"] is ev

    def test_repassa_on_log(self):
        source = MagicMock()
        source.list_videos.return_value = []
        log = MagicMock()
        uc = ListVideosUseCase(source=source)
        uc.execute("19/04/2026", "https://canal", on_log=log)
        _, kwargs = source.list_videos.call_args
        assert kwargs["on_log"] is log

    def test_repassa_on_status(self):
        source = MagicMock()
        source.list_videos.return_value = []
        status = MagicMock()
        uc = ListVideosUseCase(source=source)
        uc.execute("19/04/2026", "https://canal", on_status=status)
        _, kwargs = source.list_videos.call_args
        assert kwargs["on_status"] is status

    # -----------------------------------------------------------------------
    # Valor de retorno
    # -----------------------------------------------------------------------

    def test_retorna_lista_vazia(self):
        source = MagicMock()
        source.list_videos.return_value = []
        assert ListVideosUseCase(source=source).execute("19/04/2026", "url") == []

    def test_retorna_videos_do_source(self):
        v1 = _make_video("id1")
        v2 = _make_video("id2")
        source = MagicMock()
        source.list_videos.return_value = [v1, v2]
        result = ListVideosUseCase(source=source).execute("19/04/2026", "url")
        assert result == [v1, v2]

    # -----------------------------------------------------------------------
    # Propagação de exceções
    # -----------------------------------------------------------------------

    def test_propaga_video_nao_encontrado(self):
        source = MagicMock()
        source.list_videos.side_effect = VideoNaoEncontrado("19/04/2026")
        with pytest.raises(VideoNaoEncontrado):
            ListVideosUseCase(source=source).execute("19/04/2026", "url")

    def test_propaga_operacao_cancelada(self):
        source = MagicMock()
        source.list_videos.side_effect = OperacaoCancelada("cancelado")
        with pytest.raises(OperacaoCancelada):
            ListVideosUseCase(source=source).execute("19/04/2026", "url")


# ===========================================================================
# DownloadSegmentsUseCase
# ===========================================================================

class TestDownloadSegmentsUseCase:

    def _uc(self, downloader=None):
        return DownloadSegmentsUseCase(downloader=downloader or MagicMock())

    # -----------------------------------------------------------------------
    # Delegação correta para o port
    # -----------------------------------------------------------------------

    def test_delega_para_downloader_download(self):
        dl = MagicMock()
        dl.download.return_value = []
        DownloadSegmentsUseCase(downloader=dl).execute([], "/tmp")
        dl.download.assert_called_once()

    def test_repassa_segments_e_output_dir(self):
        dl = MagicMock()
        dl.download.return_value = []
        segs = [_make_segment()]
        DownloadSegmentsUseCase(downloader=dl).execute(segs, "/saida")
        args, _ = dl.download.call_args
        assert args[0] == segs
        assert args[1] == "/saida"

    def test_repassa_cancel_event(self):
        dl = MagicMock()
        dl.download.return_value = []
        ev = threading.Event()
        DownloadSegmentsUseCase(downloader=dl).execute([], "/tmp", cancel_event=ev)
        _, kwargs = dl.download.call_args
        assert kwargs["cancel_event"] is ev

    def test_repassa_on_progress(self):
        dl = MagicMock()
        dl.download.return_value = []
        cb = MagicMock()
        DownloadSegmentsUseCase(downloader=dl).execute([], "/tmp", on_progress=cb)
        _, kwargs = dl.download.call_args
        assert kwargs["on_progress"] is cb

    def test_repassa_on_log_e_on_status(self):
        dl = MagicMock()
        dl.download.return_value = []
        log, status = MagicMock(), MagicMock()
        DownloadSegmentsUseCase(downloader=dl).execute(
            [], "/tmp", on_log=log, on_status=status
        )
        _, kwargs = dl.download.call_args
        assert kwargs["on_log"] is log
        assert kwargs["on_status"] is status

    # -----------------------------------------------------------------------
    # Valor de retorno
    # -----------------------------------------------------------------------

    def test_retorna_lista_de_audio_files(self):
        af = _make_audio()
        dl = MagicMock()
        dl.download.return_value = [af]
        result = DownloadSegmentsUseCase(downloader=dl).execute([_make_segment()], "/tmp")
        assert result == [af]

    def test_retorna_lista_vazia_sem_segmentos(self):
        dl = MagicMock()
        dl.download.return_value = []
        assert DownloadSegmentsUseCase(downloader=dl).execute([], "/tmp") == []

    # -----------------------------------------------------------------------
    # Propagação de exceções
    # -----------------------------------------------------------------------

    def test_propaga_operacao_cancelada(self):
        dl = MagicMock()
        dl.download.side_effect = OperacaoCancelada("cancelado")
        with pytest.raises(OperacaoCancelada):
            DownloadSegmentsUseCase(downloader=dl).execute([_make_segment()], "/tmp")

    def test_propaga_runtime_error_do_ytdlp(self):
        dl = MagicMock()
        dl.download.side_effect = RuntimeError("yt-dlp falhou")
        with pytest.raises(RuntimeError, match="yt-dlp falhou"):
            DownloadSegmentsUseCase(downloader=dl).execute([_make_segment()], "/tmp")


# ===========================================================================
# UploadAudioUseCase
# ===========================================================================

class TestUploadAudioUseCase:

    def _uc(self, storage=None, history=None):
        storage = storage or MagicMock()
        history = history or MagicMock()
        storage.upload.return_value = _make_result(uploaded=("culto.mp3",))
        return UploadAudioUseCase(storage=storage, history=history), storage, history

    # -----------------------------------------------------------------------
    # Delegação para ICloudStorage
    # -----------------------------------------------------------------------

    def test_delega_para_storage_upload(self):
        uc, storage, _ = self._uc()
        uc.execute("19/04/2026", [_make_audio()])
        storage.upload.assert_called_once()

    def test_repassa_date_str_e_audio_files(self):
        uc, storage, _ = self._uc()
        files = [_make_audio()]
        uc.execute("19/04/2026", files)
        args, _ = storage.upload.call_args
        assert args[0] == files
        assert args[1] == "19/04/2026"

    def test_repassa_cancel_event(self):
        uc, storage, _ = self._uc()
        ev = threading.Event()
        uc.execute("19/04/2026", [], cancel_event=ev)
        _, kwargs = storage.upload.call_args
        assert kwargs["cancel_event"] is ev

    def test_repassa_on_progress(self):
        uc, storage, _ = self._uc()
        cb = MagicMock()
        uc.execute("19/04/2026", [], on_progress=cb)
        _, kwargs = storage.upload.call_args
        assert kwargs["on_progress"] is cb

    def test_extra_kwargs_repassados_ao_storage(self):
        """on_upload_stats (e outros) devem fluir até ICloudStorage.upload()."""
        uc, storage, _ = self._uc()
        stats_cb = MagicMock()
        uc.execute("19/04/2026", [], on_upload_stats=stats_cb)
        _, kwargs = storage.upload.call_args
        assert kwargs["on_upload_stats"] is stats_cb

    # -----------------------------------------------------------------------
    # Registro no histórico
    # -----------------------------------------------------------------------

    def test_grava_historico_quando_ha_uploaded_files(self):
        storage = MagicMock()
        history = MagicMock()
        storage.upload.return_value = _make_result(uploaded=("a.mp3",))
        uc = UploadAudioUseCase(storage=storage, history=history)
        uc.execute("19/04/2026", [_make_audio(title="Culto")])
        history.record.assert_called_once_with("19/04/2026", ["Culto"])

    def test_nao_grava_historico_quando_todos_ignorados(self):
        """Se tudo foram duplicatas (uploaded_files vazio), não grava histórico."""
        storage = MagicMock()
        history = MagicMock()
        storage.upload.return_value = _make_result(uploaded=(), skipped=("a.mp3",))
        uc = UploadAudioUseCase(storage=storage, history=history)
        uc.execute("19/04/2026", [_make_audio()])
        history.record.assert_not_called()

    def test_historico_recebe_titulos_dos_audio_files(self):
        storage = MagicMock()
        history = MagicMock()
        storage.upload.return_value = _make_result(uploaded=("a.mp3", "b.mp3"))
        uc = UploadAudioUseCase(storage=storage, history=history)
        af1 = _make_audio(title="Culto A")
        af2 = _make_audio(title="Culto B")
        uc.execute("19/04/2026", [af1, af2])
        history.record.assert_called_once_with("19/04/2026", ["Culto A", "Culto B"])

    def test_historico_nao_chamado_se_lista_de_arquivos_vazia(self):
        storage = MagicMock()
        history = MagicMock()
        storage.upload.return_value = _make_result(uploaded=())
        uc = UploadAudioUseCase(storage=storage, history=history)
        uc.execute("19/04/2026", [])
        history.record.assert_not_called()

    # -----------------------------------------------------------------------
    # Valor de retorno
    # -----------------------------------------------------------------------

    def test_retorna_processing_result_do_storage(self):
        storage = MagicMock()
        history = MagicMock()
        expected = _make_result(uploaded=("culto.mp3",))
        storage.upload.return_value = expected
        uc = UploadAudioUseCase(storage=storage, history=history)
        result = uc.execute("19/04/2026", [_make_audio()])
        assert result is expected

    def test_retorna_result_mesmo_quando_nao_grava_historico(self):
        storage = MagicMock()
        history = MagicMock()
        expected = _make_result(uploaded=(), skipped=("x.mp3",))
        storage.upload.return_value = expected
        uc = UploadAudioUseCase(storage=storage, history=history)
        result = uc.execute("19/04/2026", [_make_audio()])
        assert result is expected

    # -----------------------------------------------------------------------
    # Propagação de exceções
    # -----------------------------------------------------------------------

    def test_propaga_operacao_cancelada_do_storage(self):
        storage = MagicMock()
        history = MagicMock()
        storage.upload.side_effect = OperacaoCancelada("cancelado")
        uc = UploadAudioUseCase(storage=storage, history=history)
        with pytest.raises(OperacaoCancelada):
            uc.execute("19/04/2026", [_make_audio()])

    def test_nao_grava_historico_se_storage_levanta_excecao(self):
        storage = MagicMock()
        history = MagicMock()
        storage.upload.side_effect = RuntimeError("falha no upload")
        uc = UploadAudioUseCase(storage=storage, history=history)
        with pytest.raises(RuntimeError):
            uc.execute("19/04/2026", [_make_audio()])
        history.record.assert_not_called()
