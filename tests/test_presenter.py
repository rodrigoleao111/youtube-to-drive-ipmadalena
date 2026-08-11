"""
Testes para presentation/processing_presenter.py.

Usa MagicMock para os use cases (ListVideosUseCase, DownloadSegmentsUseCase,
UploadAudioUseCase). Sem acesso a disco, rede ou subprocess.
"""

from __future__ import annotations

import os
import threading
from unittest.mock import MagicMock

import pytest

from domain.entities import AudioFile, ProcessingResult, Segment, Video
from domain.exceptions import OperacaoCancelada, VideoNaoEncontrado
from infrastructure.archive.zip_archiver import ZipArchiver
from presentation.processing_presenter import ProcessingPresenter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_video(vid="abc123", title="Culto", date="20260419") -> Video:
    return Video(id=vid, title=title, upload_date=date)


def _make_audio(path="/tmp/culto.mp3", title="Culto", vid="abc123") -> AudioFile:
    return AudioFile(path=path, title=title, video_id=vid)


_SEM_ARCHIVER = object()   # sentinela: distingue "default" de "sem compactador"


def _make_presenter(
    *, list_uc=None, download_uc=None, edit_uc=None, upload_uc=None,
    chapters_uc=None, fetch_video_uc=None, archiver=_SEM_ARCHIVER,
    channel_url="https://youtube.com/@IPMadalena/streams",
    download_dir="/tmp/downloads",
) -> ProcessingPresenter:
    # edit_uc default = passa adiante a lista de entrada (no-op)
    if edit_uc is None:
        edit_uc = MagicMock()
        edit_uc.execute.side_effect = lambda audio_files, **kw: audio_files
    # Compactador real (I/O local em tmp_path) — é o que o composition root
    # injeta em produção. Passe archiver=None para exercitar o fallback.
    if archiver is _SEM_ARCHIVER:
        archiver = ZipArchiver()
    return ProcessingPresenter(
        list_videos_uc=list_uc or MagicMock(),
        download_uc=download_uc or MagicMock(),
        edit_uc=edit_uc,
        upload_uc=upload_uc or MagicMock(),
        chapters_uc=chapters_uc or MagicMock(),
        channel_url=channel_url,
        download_dir=download_dir,
        fetch_video_uc=fetch_video_uc or MagicMock(),
        archiver=archiver,
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
# fetch_video()
# ===========================================================================

class TestPresenterFetchVideo:

    URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_delega_para_fetch_video_uc_com_a_url(self):
        uc = MagicMock()
        uc.execute.return_value = _make_video()
        _make_presenter(fetch_video_uc=uc).fetch_video(self.URL)
        args, _ = uc.execute.call_args
        assert args[0] == self.URL

    def test_retorna_dict_no_formato_de_list_videos(self):
        uc = MagicMock()
        uc.execute.return_value = _make_video("xyz789", "Culto ao vivo", "20260503")
        result = _make_presenter(fetch_video_uc=uc).fetch_video(self.URL)
        assert result == {
            "id": "xyz789",
            "title": "Culto ao vivo",
            "upload_date": "20260503",
        }

    def test_repassa_cancel_event_e_callbacks(self):
        uc = MagicMock()
        uc.execute.return_value = _make_video()
        ev = threading.Event()
        log, status = MagicMock(), MagicMock()
        _make_presenter(fetch_video_uc=uc).fetch_video(
            self.URL, cancel_event=ev, on_log=log, on_status=status
        )
        _, kwargs = uc.execute.call_args
        assert kwargs["cancel_event"] is ev
        assert kwargs["on_log"] is log
        assert kwargs["on_status"] is status

    def test_converte_video_nao_encontrado_em_runtime_error(self):
        uc = MagicMock()
        uc.execute.side_effect = VideoNaoEncontrado("Link do YouTube inválido.")
        with pytest.raises(RuntimeError, match="inválido"):
            _make_presenter(fetch_video_uc=uc).fetch_video(self.URL)

    def test_propaga_operacao_cancelada(self):
        uc = MagicMock()
        uc.execute.side_effect = OperacaoCancelada("cancelado")
        with pytest.raises(OperacaoCancelada):
            _make_presenter(fetch_video_uc=uc).fetch_video(self.URL)

    def test_sem_use_case_levanta_runtime_error(self):
        # Presenter montado sem o modo link (default None)
        p = ProcessingPresenter(
            list_videos_uc=MagicMock(),
            download_uc=MagicMock(),
            edit_uc=MagicMock(),
            upload_uc=MagicMock(),
            chapters_uc=MagicMock(),
            channel_url="https://canal",
            download_dir="/tmp",
        )
        assert p.fetch_video_uc is None
        with pytest.raises(RuntimeError):
            p.fetch_video(self.URL)


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
        with pytest.raises(RuntimeError, match="áudio"):
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
        with pytest.raises(RuntimeError, match="áudio"):
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
        # Substitui o upload_uc do helper pelo que levanta exceção
        edit_uc = MagicMock()
        edit_uc.execute.side_effect = lambda audio_files, **kw: audio_files
        p = _make_presenter(
            download_uc=MagicMock(execute=MagicMock(return_value=[_make_audio()])),
            edit_uc=edit_uc,
            upload_uc=upload_uc,
        )
        with pytest.raises(OperacaoCancelada):
            p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])


# ===========================================================================
# Passo de edição entre download e upload
# ===========================================================================

class TestPresenterPipelineComEdicao:
    def _setup(self, edit_returns=None):
        """Helper: monta presenter com download/edit/upload mockados."""
        download_uc = MagicMock()
        edit_uc     = MagicMock()
        upload_uc   = MagicMock()

        downloaded = [_make_audio(path="/tmp/a.mp3"),
                      _make_audio(path="/tmp/b.mp3")]
        download_uc.execute.return_value = downloaded

        if edit_returns is None:
            edit_uc.execute.side_effect = lambda audio_files, **kw: audio_files
        else:
            edit_uc.execute.return_value = edit_returns

        upload_uc.execute.return_value = ProcessingResult(
            date_str="19/04/2026", uploaded_files=("a.mp3",),
        )
        p = _make_presenter(
            download_uc=download_uc, edit_uc=edit_uc, upload_uc=upload_uc,
        )
        return p, download_uc, edit_uc, upload_uc

    def test_edicao_chamada_uma_vez_entre_download_e_upload(self):
        p, _, edit_uc, _ = self._setup()
        p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])
        assert edit_uc.execute.call_count == 1

    def test_edicao_recebe_audio_files_do_download(self):
        p, download_uc, edit_uc, _ = self._setup()
        p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])

        downloaded = download_uc.execute.return_value
        first_arg = edit_uc.execute.call_args.args[0]
        assert first_arg == downloaded

    def test_upload_recebe_audio_files_da_edicao(self):
        # Edição devolve uma lista DIFERENTE (simulando que pôde editar in-place)
        edited = [_make_audio(path="/tmp/edited.mp3")]
        p, _, _, upload_uc = self._setup(edit_returns=edited)
        p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])

        # 2º arg posicional do upload é a lista de AudioFile
        args = upload_uc.execute.call_args.args
        assert args[1] == edited

    def test_ordem_de_chamada_download_edicao_upload(self):
        p, download_uc, edit_uc, upload_uc = self._setup()

        call_order = []
        download_uc.execute.side_effect = lambda *a, **kw: (
            call_order.append("download") or
            [_make_audio(path="/tmp/a.mp3")]
        )
        edit_uc.execute.side_effect = lambda audio_files, **kw: (
            call_order.append("edit") or audio_files
        )
        upload_uc.execute.side_effect = lambda *a, **kw: (
            call_order.append("upload") or
            ProcessingResult(date_str="19/04/2026", uploaded_files=("a.mp3",))
        )
        p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])

        assert call_order == ["download", "edit", "upload"]

    def test_repassa_on_edit_progress_para_o_use_case(self):
        p, _, edit_uc, _ = self._setup()
        progress = MagicMock()
        p.process_segments(
            "19/04/2026", [{"id": "v1", "title": "x"}],
            on_edit_progress=progress,
        )
        kwargs = edit_uc.execute.call_args.kwargs
        assert kwargs["on_progress"] is progress

    def test_repassa_cancel_event_para_a_edicao(self):
        p, _, edit_uc, _ = self._setup()
        ev = threading.Event()
        p.process_segments(
            "19/04/2026", [{"id": "v1", "title": "x"}], cancel_event=ev,
        )
        assert edit_uc.execute.call_args.kwargs["cancel_event"] is ev

    def test_propaga_operacao_cancelada_na_edicao(self):
        p, _, edit_uc, upload_uc = self._setup()
        edit_uc.execute.side_effect = OperacaoCancelada("cancelado")
        with pytest.raises(OperacaoCancelada):
            p.process_segments("19/04/2026", [{"id": "v1", "title": "x"}])
        upload_uc.execute.assert_not_called()


# ===========================================================================
# ProcessingPresenter.get_chapters
# ===========================================================================

class TestProcessingPresenterGetChapters:

    def _setup(self):
        chapters_uc = MagicMock()
        p = _make_presenter(chapters_uc=chapters_uc)
        return p, chapters_uc

    def test_delega_para_chapters_uc(self):
        p, chapters_uc = self._setup()
        chapters_uc.execute.return_value = [{"title": "Sermão", "start": "00:10:00", "end": "01:00:00"}]
        result = p.get_chapters("abc123")
        chapters_uc.execute.assert_called_once_with("abc123", cancel_event=None, on_log=None)
        assert result == [{"title": "Sermão", "start": "00:10:00", "end": "01:00:00"}]

    def test_retorna_lista_vazia_quando_sem_capitulos(self):
        p, chapters_uc = self._setup()
        chapters_uc.execute.return_value = []
        assert p.get_chapters("abc123") == []

    def test_repassa_cancel_event(self):
        import threading
        p, chapters_uc = self._setup()
        chapters_uc.execute.return_value = []
        ev = threading.Event()
        p.get_chapters("abc123", cancel_event=ev)
        assert chapters_uc.execute.call_args.kwargs["cancel_event"] is ev

    def test_repassa_on_log(self):
        p, chapters_uc = self._setup()
        chapters_uc.execute.return_value = []
        log = MagicMock()
        p.get_chapters("abc123", on_log=log)
        assert chapters_uc.execute.call_args.kwargs["on_log"] is log


# ===========================================================================
# upload_enabled=False — pula o upload
# ===========================================================================

class TestPresenterUploadDesabilitado:
    """
    Quando upload_enabled=False, o UploadAudioUseCase NÃO deve ser chamado.
    """

    def _seg(self):
        return {"id": "abc", "title": "Culto", "start": None, "end": None}

    def test_upload_nao_chamado_quando_upload_disabled(self):
        download_uc = MagicMock()
        download_uc.execute.return_value = [_make_audio()]
        edit_uc = MagicMock()
        edit_uc.execute.side_effect = lambda af, **kw: af
        upload_uc = MagicMock()

        p = ProcessingPresenter(
            list_videos_uc=MagicMock(),
            download_uc=download_uc,
            edit_uc=edit_uc,
            upload_uc=upload_uc,
            chapters_uc=MagicMock(),
            channel_url="https://canal",
            download_dir="/tmp",
            upload_enabled=False,
        )
        p.process_segments("19/05/2026", [self._seg()])
        upload_uc.execute.assert_not_called()

    def test_download_ainda_chamado_quando_upload_disabled(self):
        download_uc = MagicMock()
        download_uc.execute.return_value = [_make_audio()]
        edit_uc = MagicMock()
        edit_uc.execute.side_effect = lambda af, **kw: af

        p = ProcessingPresenter(
            list_videos_uc=MagicMock(),
            download_uc=download_uc,
            edit_uc=edit_uc,
            upload_uc=MagicMock(),
            chapters_uc=MagicMock(),
            channel_url="https://canal",
            download_dir="/tmp",
            upload_enabled=False,
        )
        p.process_segments("19/05/2026", [self._seg()])
        download_uc.execute.assert_called_once()

    def test_upload_enabled_padrao_e_true(self):
        p = _make_presenter()
        assert p.upload_enabled is True

    def test_on_status_informativo_quando_upload_disabled(self):
        download_uc = MagicMock()
        download_uc.execute.return_value = [_make_audio()]
        edit_uc = MagicMock()
        edit_uc.execute.side_effect = lambda af, **kw: af

        statuses = []
        p = ProcessingPresenter(
            list_videos_uc=MagicMock(),
            download_uc=download_uc,
            edit_uc=edit_uc,
            upload_uc=MagicMock(),
            chapters_uc=MagicMock(),
            channel_url="https://canal",
            download_dir="/tmp",
            upload_enabled=False,
        )
        p.process_segments("19/05/2026", [self._seg()], on_status=statuses.append)
        assert any("desabilitado" in s.lower() for s in statuses)


# ===========================================================================
# _build_upload_list()
# ===========================================================================

class TestBuildUploadList:
    """
    Testa ProcessingPresenter._build_upload_list():
      - AudioFile sem subfolder → passa diretamente (retrocompat.)
      - AudioFile com subfolder → áudio + capa + descrição viram UM zip
      - Vídeos ficam fora do pacote e sobem ao lado
      - Subpasta duplicada → ignorada (evita duplicação de artefatos)
    """

    def _presenter(self, **kw):
        return _make_presenter(**kw)

    def _sub_completa(self, tmp_path, nome="Culto"):
        sub = tmp_path / nome
        sub.mkdir()
        (sub / f"{nome}.mp3").write_bytes(b"mp3")
        (sub / "capa.jpg").write_bytes(b"jpg")
        (sub / "descricao.txt").write_text("desc", encoding="utf-8")
        return sub

    def test_audio_file_sem_subfolder_passa_direto(self):
        """AudioFile com subfolder=None vai direto para a upload list (retrocompat)."""
        af = _make_audio(path="/tmp/culto.mp3", title="Culto", vid="v1")
        p  = self._presenter()
        result = p._build_upload_list([af])
        assert result == [af]

    def test_subfolder_gera_um_unico_zip(self, tmp_path):
        sub = self._sub_completa(tmp_path)
        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))

        result = self._presenter()._build_upload_list([af])

        assert len(result) == 1
        assert os.path.basename(result[0].path) == "Culto.zip"
        assert os.path.isfile(result[0].path)

    def test_zip_leva_o_nome_do_arquivo_de_audio(self, tmp_path):
        """O nome do pacote vem do áudio, não do título do segmento."""
        sub = tmp_path / "pasta"
        sub.mkdir()
        (sub / "Culto da Manha 19-04.mp3").write_bytes(b"mp3")
        (sub / "capa.jpg").write_bytes(b"jpg")

        af = AudioFile(path=str(sub / "Culto da Manha 19-04.mp3"),
                       title="titulo diferente", video_id="v1",
                       subfolder=str(sub))
        result = self._presenter()._build_upload_list([af])

        assert os.path.basename(result[0].path) == "Culto da Manha 19-04.zip"
        assert result[0].title == "Culto da Manha 19-04"

    def test_zip_contem_audio_capa_e_descricao(self, tmp_path):
        import zipfile
        sub = self._sub_completa(tmp_path)
        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))

        result = self._presenter()._build_upload_list([af])

        with zipfile.ZipFile(result[0].path) as zf:
            nomes = sorted(zf.namelist())
        assert nomes == ["Culto.mp3", "capa.jpg", "descricao.txt"]

    def test_zip_nao_tem_estrutura_de_pastas(self, tmp_path):
        import zipfile
        sub = self._sub_completa(tmp_path)
        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))

        result = self._presenter()._build_upload_list([af])
        with zipfile.ZipFile(result[0].path) as zf:
            assert all("/" not in n for n in zf.namelist())

    def test_mp4_fica_fora_do_zip_e_sobe_ao_lado(self, tmp_path):
        """
        Zipar MP4 (já comprimido, centenas de MB) não reduz nada; com
        save_video=True o vídeo sobe solto ao lado do pacote.
        """
        import zipfile
        sub = self._sub_completa(tmp_path)
        (sub / "Culto.mp4").write_bytes(b"mp4")

        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))
        result = self._presenter()._build_upload_list([af])

        exts = sorted(os.path.splitext(r.path)[1] for r in result)
        assert exts == [".mp4", ".zip"]
        with zipfile.ZipFile(next(r.path for r in result
                                  if r.path.endswith(".zip"))) as zf:
            assert not any(n.endswith(".mp4") for n in zf.namelist())

    def test_zip_anterior_nao_entra_no_pacote_nem_sobe_solto(self, tmp_path):
        """
        Reprocessar a mesma pasta não deve aninhar o zip antigo nem enviá-lo
        como arquivo separado (duplicaria o episódio no Drive).
        """
        import zipfile
        sub = self._sub_completa(tmp_path)
        (sub / "antigo.zip").write_bytes(b"PK\x03\x04")

        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))
        result = self._presenter()._build_upload_list([af])

        enviados = [os.path.basename(r.path) for r in result]
        assert enviados == ["Culto.zip"]
        with zipfile.ZipFile(result[0].path) as zf:
            assert not any(n.endswith(".zip") for n in zf.namelist())

    def test_temporarios_nao_entram_no_pacote(self, tmp_path):
        """`.tmp` de uma edição interrompida não deve ir para o Drive."""
        import zipfile
        sub = self._sub_completa(tmp_path)
        (sub / "Culto.mp3.tmp").write_bytes(b"parcial")

        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))
        result = self._presenter()._build_upload_list([af])

        assert [os.path.basename(r.path) for r in result] == ["Culto.zip"]
        with zipfile.ZipFile(result[0].path) as zf:
            assert not any(n.endswith(".tmp") for n in zf.namelist())

    def test_build_upload_package_e_publico_e_empacota(self, tmp_path):
        """API usada pelo re-envio da tela Início."""
        sub = self._sub_completa(tmp_path)
        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="", subfolder=str(sub))
        result = self._presenter().build_upload_package(af)
        assert [os.path.basename(r.path) for r in result] == ["Culto.zip"]

    def test_build_upload_package_sem_subpasta_sobe_o_arquivo(self, tmp_path):
        mp3 = tmp_path / "solto.mp3"
        mp3.write_bytes(b"mp3")
        af = AudioFile(path=str(mp3), title="solto", video_id="")
        result = self._presenter().build_upload_package(af)
        assert result == [af]

    def test_subfolder_duplicada_ignorada(self, tmp_path):
        """Dois AudioFiles apontando para a mesma subpasta só processam uma vez."""
        sub = self._sub_completa(tmp_path)
        af1 = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                        video_id="v1", subfolder=str(sub))
        af2 = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                        video_id="v1", subfolder=str(sub))

        result = self._presenter()._build_upload_list([af1, af2])
        assert len(result) == 1

    def test_subfolder_inexistente_cai_em_retrocompat(self):
        """Se subfolder está definido mas não existe, trata como sem subfolder."""
        af = AudioFile(path="/tmp/culto.mp3", title="Culto",
                       video_id="v1", subfolder="/caminho/inexistente")
        result = self._presenter()._build_upload_list([af])
        assert result == [af]

    def test_lista_vazia_retorna_lista_vazia(self):
        assert self._presenter()._build_upload_list([]) == []

    def test_video_id_preservado_no_pacote(self, tmp_path):
        sub = self._sub_completa(tmp_path)
        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="vid123", subfolder=str(sub))
        result = self._presenter()._build_upload_list([af])
        assert all(r.video_id == "vid123" for r in result)

    def test_subfolder_preservado_no_pacote(self, tmp_path):
        """A subpasta segue no AudioFile — o storage a usa para a limpeza local."""
        sub = self._sub_completa(tmp_path)
        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))
        result = self._presenter()._build_upload_list([af])
        assert result[0].subfolder == str(sub)

    def test_log_informa_o_pacote_criado(self, tmp_path):
        sub = self._sub_completa(tmp_path)
        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))
        logs = []
        self._presenter()._build_upload_list([af], on_log=logs.append)
        assert any("Culto.zip" in m for m in logs)

    # -- fallback sem compactador -------------------------------------------

    def test_sem_archiver_envia_arquivos_soltos(self, tmp_path):
        sub = self._sub_completa(tmp_path)
        af = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                       video_id="v1", subfolder=str(sub))

        result = self._presenter(archiver=None)._build_upload_list([af])

        fnames = sorted(os.path.basename(r.path) for r in result)
        assert fnames == ["Culto.mp3", "capa.jpg", "descricao.txt"]
        assert not any(r.path.endswith(".zip") for r in result)

    def test_process_segments_empacota_antes_do_upload(self, tmp_path):
        """O upload recebe o zip, não os arquivos soltos."""
        sub = self._sub_completa(tmp_path)
        audio = AudioFile(path=str(sub / "Culto.mp3"), title="Culto",
                          video_id="v1", subfolder=str(sub))

        download_uc = MagicMock()
        download_uc.execute.return_value = [audio]
        upload_uc = MagicMock()

        p = _make_presenter(download_uc=download_uc, upload_uc=upload_uc)
        p.process_segments("19/04/2026", [{"id": "v1", "title": "Culto"}])

        enviados = upload_uc.execute.call_args.args[1]
        assert [os.path.basename(a.path) for a in enviados] == ["Culto.zip"]
