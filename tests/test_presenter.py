"""
Testes para presentation/processing_presenter.py.

Usa MagicMock para os use cases (ListVideosUseCase, DownloadSegmentsUseCase,
UploadAudioUseCase). Sem acesso a disco, rede ou subprocess.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from domain.entities import AudioFile, ProcessingResult, Segment, Video
from domain.exceptions import OperacaoCancelada, VideoNaoEncontrado
from presentation.processing_presenter import ProcessingPresenter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_video(vid="abc123", title="Culto", date="20260419") -> Video:
    return Video(id=vid, title=title, upload_date=date)


def _make_audio(path="/tmp/culto.mp3", title="Culto", vid="abc123") -> AudioFile:
    return AudioFile(path=path, title=title, video_id=vid)


def _make_presenter(
    *, list_uc=None, download_uc=None, upload_uc=None,
    channel_url="https://youtube.com/@IPMadalena/streams",
    download_dir="/tmp/downloads",
) -> ProcessingPresenter:
    return ProcessingPresenter(
        list_videos_uc=list_uc or MagicMock(),
        download_uc=download_uc or MagicMock(),
        upload_uc=upload_uc or MagicMock(),
        channel_url=channel_url,
        download_dir=download_dir,
    )


# ===========================================================================
# list_videos()
# ===========================================================================

class TestPresenterListVideos:

    def test_chama_use_case_com_date_str_e_channel_url(self):
        list_uc = MagicMock()
        list_uc.execute.return_value = []
        p = _make_presenter(list_uc=list_uc, channel_url="https://canal.exemplo")
        p.list_videos("19/04/2026")
        args, _ = list_uc.execute.call_args
        assert args[0] == "19/04/2026"
        assert args[1] == "https://canal.exemplo"

    def test_repassa_cancel_event_e_callbacks(self):
        list_uc = MagicMock()
        list_uc.execute.return_value = []
        ev = threading.Event()
        log, status = MagicMock(), MagicMock()
        _make_presenter(list_uc=list_uc).list_videos(
            "19/04/2026", cancel_event=ev, on_log=log, on_status=status,
        )
        _, kwargs = list_uc.execute.call_args
        assert kwargs["cancel_event"] is ev
        assert kwargs["on_log"] is log
        assert kwargs["on_status"] is status

    def test_converte_videos_para_dicts(self):
        list_uc = MagicMock()
        list_uc.execute.return_value = [
            _make_video("id1", "Culto A", "20260419"),
            _make_video("id2", "Culto B", "20260420"),
        ]
        result = _make_presenter(list_uc=list_uc).list_videos("19/04/2026")
        assert result == [
            {"id": "id1", "title": "Culto A", "upload_date": "20260419"},
            {"id": "id2", "title": "Culto B", "upload_date": "20260420"},
        ]

    def test_retorna_lista_vazia_quando_use_case_vazio(self):
        list_uc = MagicMock()
        list_uc.execute.return_value = []
        assert _make_presenter(list_uc=list_uc).list_videos("19/04/2026") == []

    def test_video_nao_encontrado_vira_runtime_error(self):
        """Mantém o contrato histórico de baixar_audio.list_videos()."""
        list_uc = MagicMock()
        list_uc.execute.side_effect = VideoNaoEncontrado("19/04/2026")
        with pytest.raises(RuntimeError, match="19/04/2026"):
            _make_presenter(list_uc=list_uc).list_videos("19/04/2026")

    def test_propaga_operacao_cancelada(self):
        list_uc = MagicMock()
        list_uc.execute.side_effect = OperacaoCancelada("cancelado")
        with pytest.raises(OperacaoCancelada):
            _make_presenter(list_uc=list_uc).list_videos("19/04/2026")


# ===========================================================================
# process_segments()
# ===========================================================================

class TestPresenterProcessSegments:

    def _setup(self, *, audio_files=None, upload_result=None):
        download_uc = MagicMock()
        upload_uc = MagicMock()
        download_uc.execute.return_value = audio_files if audio_files is not None else [_make_audio()]
        upload_uc.execute.return_value = upload_result or ProcessingResult(
            date_str="19/04/2026", uploaded_files=("culto.mp3",)
        )
        p = _make_presenter(download_uc=download_uc, upload_uc=upload_uc, download_dir="/saida")
        return p, download_uc, upload_uc

    # -----------------------------------------------------------------------
    # Conversão de dicts → Segment
    # -----------------------------------------------------------------------

    def test_converte_dicts_para_segments(self):
        p, download_uc, _ = self._setup()
        p.process_segments(
            "19/04/2026",
            [{"id": "v1", "title": "Culto A", "start": "00:00:10", "end": "00:30:00"}],
        )
        args, _ = download_uc.execute.call_args
        seg_list = args[0]
        assert len(seg_list) == 1
        assert isinstance(seg_list[0], Segment)
        assert seg_list[0].video_id == "v1"
        assert seg_list[0].title == "Culto A"
        assert seg_list[0].start == "00:00:10"
        assert seg_list[0].end == "00:30:00"

    def test_segment_sem_start_end(self):
        p, download_uc, _ = self._setup()
        p.process_segments("19/04/2026", [{"id": "v1", "title": "Culto"}])
        seg = download_uc.execute.call_args[0][0][0]
        assert seg.start is None
        assert seg.end is None

    def test_multiplos_segments_preservam_ordem(self):
        p, download_uc, _ = self._setup()
        segs = [
            {"id": "v1", "title": "A"},
            {"id": "v2", "title": "B"},
            {"id": "v3", "title": "C"},
        ]
        p.process_segments("19/04/2026", segs)
        seg_list = download_uc.execute.call_args[0][0]
        assert [s.video_id for s in seg_list] == ["v1", "v2", "v3"]

    # -----------------------------------------------------------------------
    # Chamadas aos use cases
    # -----------------------------------------------------------------------

    def test_chama_download_e_upload_em_ordem(self):
        p, download_uc, upload_uc = self._setup()
        call_order = []
        download_uc.execute.side_effect = lambda *a, **kw: (
            call_order.append("download") or [_make_audio()]
        )
        upload_uc.execute.side_effect = lambda *a, **kw: (
            call_order.append("upload")
            or ProcessingResult(date_str="x", uploaded_files=("a.mp3",))
        )
        p.process_segments("19/04/2026", [{"id": "v1", "title": "Culto"}])
        assert call_order == ["download", "upload"]

    def test_download_recebe_output_dir(self):
        p, download_uc, _ = self._setup()
        p.process_segments("19/04/2026", [{"id": "v1", "title": "Culto"}])
        args, _ = download_uc.execute.call_args
        assert args[1] == "/saida"

    def test_upload_recebe_audio_files_do_download(self):
        af1 = _make_audio("/tmp/a.mp3", "A")
        af2 = _make_audio("/tmp/b.mp3", "B")
        p, download_uc, upload_uc = self._setup(audio_files=[af1, af2])
        p.process_segments(
            "19/04/2026",
            [{"id": "v1", "title": "A"}, {"id": "v2", "title": "B"}],
        )
        args, _ = upload_uc.execute.call_args
        assert args[0] == "19/04/2026"
        assert args[1] == [af1, af2]

    # -----------------------------------------------------------------------
    # Forwarding de callbacks
    # -----------------------------------------------------------------------

    def test_repassa_callbacks_corretos_para_download(self):
        p, download_uc, _ = self._setup()
        ev = threading.Event()
        log, status, dl_progress = MagicMock(), MagicMock(), MagicMock()
        p.process_segments(
            "19/04/2026", [{"id": "v1", "title": "x"}],
            cancel_event=ev, on_log=log, on_status=status,
            on_download_progress=dl_progress,
        )
        _, kwargs = download_uc.execute.call_args
        assert kwargs["cancel_event"] is ev
        assert kwargs["on_log"] is log
        assert kwargs["on_status"] is status
        assert kwargs["on_progress"] is dl_progress

    def test_repassa_callbacks_corretos_para_upload(self):
        p, _, upload_uc = self._setup()
        ev = threading.Event()
        log, status = MagicMock(), MagicMock()
        up_progress, up_stats = MagicMock(), MagicMock()
        p.process_segments(
            "19/04/2026", [{"id": "v1", "title": "x"}],
            cancel_event=ev, on_log=log, on_status=status,
            on_upload_progress=up_progress, on_upload_stats=up_stats,
        )
        _, kwargs = upload_uc.execute.call_args
        assert kwargs["cancel_event"] is ev
        assert kwargs["on_log"] is log
        assert kwargs["on_status"] is status
        assert kwargs["on_progress"] is up_progress
        assert kwargs["on_upload_stats"] is up_stats

    # -----------------------------------------------------------------------
    # Valor de retorno e contrato com a View
    # -----------------------------------------------------------------------

    def test_retorna_lista_de_titulos_dos_segments(self):
        p, _, _ = self._setup()
        result = p.process_segments(
            "19/04/2026",
            [{"id": "v1", "title": "Culto A"}, {"id": "v2", "title": "Culto B"}],
        )
        assert result == ["Culto A", "Culto B"]

    def test_retorna_lista_vazia_para_segments_vazios_falha_no_download(self):
        """Sem segments, download retorna [] e o presenter levanta RuntimeError."""
        download_uc = MagicMock()
        download_uc.execute.return_value = []
        upload_uc = MagicMock()
        p = _make_presenter(download_uc=download_uc, upload_uc=upload_uc)
        with pytest.raises(RuntimeError, match="Nenhum arquivo MP3"):
            p.process_segments("19/04/2026", [])
        upload_uc.execute.assert_not_called()

    # -----------------------------------------------------------------------
    # Erros e cancelamento
    # -----------------------------------------------------------------------

    def test_runtime_error_se_download_nao_gerar_arquivos(self):
        download_uc = MagicMock()
        download_uc.execute.return_value = []   # zero arquivos baixados
        upload_uc = MagicMock()
        p = _make_presenter(download_uc=download_uc, upload_uc=upload_uc)
        with pytest.raises(RuntimeError, match="Nenhum arquivo MP3"):
            p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])
        upload_uc.execute.assert_not_called()

    def test_propaga_operacao_cancelada_no_download(self):
        download_uc = MagicMock()
        download_uc.execute.side_effect = OperacaoCancelada("cancelado")
        upload_uc = MagicMock()
        p = _make_presenter(download_uc=download_uc, upload_uc=upload_uc)
        with pytest.raises(OperacaoCancelada):
            p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])
        upload_uc.execute.assert_not_called()

    def test_propaga_operacao_cancelada_no_upload(self):
        upload_uc = MagicMock()
        upload_uc.execute.side_effect = OperacaoCancelada("cancelado")
        p, _, _ = self._setup(upload_result=None)
        # Substitui o upload_uc do setup pelo que levanta exceção
        p = ProcessingPresenter(
            list_videos_uc=MagicMock(),
            download_uc=MagicMock(execute=MagicMock(return_value=[_make_audio()])),
            upload_uc=upload_uc,
            channel_url="x",
            download_dir="/tmp",
        )
        with pytest.raises(OperacaoCancelada):
            p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])
