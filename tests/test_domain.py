"""
Testes unitários puros para a camada de domínio.

Sem mocks, sem I/O, sem dependências externas.
Cobre: entities, exceptions, ports (verificação estrutural de Protocol).
"""

import pytest

from domain.entities import AudioFile, ProcessingResult, Segment, Video
from domain.exceptions import (
    ConfiguracaoInvalida,
    DomainError,
    IPMadalenaError,
    OperacaoCancelada,
    SegmentoInvalido,
    VideoNaoEncontrado,
)
from domain.ports import (
    IAudioDownloader,
    ICloudStorage,
    IConfigRepository,
    IHistoryRepository,
    INotifier,
    IVideoSource,
)


# ===========================================================================
# Video
# ===========================================================================

class TestVideo:
    def test_criacao_basica(self):
        v = Video(id="abc123", title="Culto", upload_date="20260419")
        assert v.id == "abc123"
        assert v.title == "Culto"
        assert v.upload_date == "20260419"

    def test_youtube_url(self):
        v = Video(id="dQw4w9WgXcQ", title="Test", upload_date="20260101")
        assert v.youtube_url() == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_str(self):
        v = Video(id="x", title="Culto de Páscoa", upload_date="20260419")
        assert "Culto de Páscoa" in str(v)
        assert "20260419" in str(v)

    def test_imutavel(self):
        v = Video(id="x", title="T", upload_date="20260101")
        with pytest.raises((AttributeError, TypeError)):
            v.id = "outro"  # type: ignore[misc]

    def test_igualdade_por_valor(self):
        v1 = Video(id="x", title="T", upload_date="20260101")
        v2 = Video(id="x", title="T", upload_date="20260101")
        assert v1 == v2

    def test_diferenca_por_id(self):
        v1 = Video(id="a", title="T", upload_date="20260101")
        v2 = Video(id="b", title="T", upload_date="20260101")
        assert v1 != v2


# ===========================================================================
# Segment
# ===========================================================================

class TestSegment:
    def test_video_completo_quando_sem_start_end(self):
        s = Segment(video_id="abc", title="Culto")
        assert s.is_full_video is True
        assert s.start is None
        assert s.end is None

    def test_trecho_nao_e_video_completo(self):
        s = Segment(video_id="abc", title="Culto", start="00:10:00", end="01:00:00")
        assert s.is_full_video is False

    def test_start_sem_end_nao_e_video_completo(self):
        s = Segment(video_id="abc", title="Culto", start="00:10:00", end=None)
        assert s.is_full_video is False

    def test_str_completo(self):
        s = Segment(video_id="abc", title="Culto Especial")
        assert "Culto Especial" in str(s)
        assert "completo" in str(s)

    def test_str_com_trecho(self):
        s = Segment(video_id="abc", title="Culto", start="00:15:00", end="01:10:00")
        text = str(s)
        assert "00:15:00" in text
        assert "01:10:00" in text

    def test_imutavel(self):
        s = Segment(video_id="abc", title="T")
        with pytest.raises((AttributeError, TypeError)):
            s.video_id = "outro"  # type: ignore[misc]

    def test_igualdade_por_valor(self):
        s1 = Segment(video_id="a", title="T", start="00:10:00", end="01:00:00")
        s2 = Segment(video_id="a", title="T", start="00:10:00", end="01:00:00")
        assert s1 == s2


# ===========================================================================
# AudioFile
# ===========================================================================

class TestAudioFile:
    def test_criacao(self):
        af = AudioFile(path="/tmp/culto.mp3", title="Culto", video_id="abc")
        assert af.path == "/tmp/culto.mp3"
        assert af.title == "Culto"
        assert af.video_id == "abc"

    def test_filename_extrai_basename(self):
        af = AudioFile(path="/downloads/culto_pascoa.mp3", title="T", video_id="x")
        assert af.filename() == "culto_pascoa.mp3"

    def test_filename_windows_path(self):
        af = AudioFile(
            path=r"C:\users\rasantos\downloads\culto.mp3",
            title="T",
            video_id="x",
        )
        assert af.filename() == "culto.mp3"

    def test_imutavel(self):
        af = AudioFile(path="/tmp/x.mp3", title="T", video_id="x")
        with pytest.raises((AttributeError, TypeError)):
            af.path = "/other"  # type: ignore[misc]


# ===========================================================================
# ProcessingResult
# ===========================================================================

class TestProcessingResult:
    def test_total_somado_corretamente(self):
        r = ProcessingResult(
            date_str="19/04/2026",
            uploaded_files=("a.mp3", "b.mp3"),
            skipped_files=("c.mp3",),
        )
        assert r.total == 3

    def test_success_true_quando_ha_arquivos(self):
        r = ProcessingResult(
            date_str="19/04/2026",
            uploaded_files=("a.mp3",),
        )
        assert r.success is True

    def test_success_false_quando_vazio(self):
        r = ProcessingResult(date_str="19/04/2026")
        assert r.success is False

    def test_summary_apenas_enviados(self):
        r = ProcessingResult(
            date_str="19/04/2026",
            uploaded_files=("a.mp3", "b.mp3"),
        )
        assert "2" in r.summary()
        assert "enviado" in r.summary()

    def test_summary_apenas_ignorados(self):
        r = ProcessingResult(
            date_str="19/04/2026",
            skipped_files=("a.mp3",),
        )
        assert "1" in r.summary()
        assert "existia" in r.summary()

    def test_summary_misto(self):
        r = ProcessingResult(
            date_str="19/04/2026",
            uploaded_files=("a.mp3",),
            skipped_files=("b.mp3",),
        )
        summary = r.summary()
        assert "enviado" in summary
        assert "existia" in summary

    def test_summary_vazio(self):
        r = ProcessingResult(date_str="19/04/2026")
        assert "nenhum" in r.summary()

    def test_defaults_sao_tuplas_vazias(self):
        r = ProcessingResult(date_str="19/04/2026")
        assert r.uploaded_files == ()
        assert r.skipped_files == ()

    def test_imutavel(self):
        r = ProcessingResult(date_str="19/04/2026")
        with pytest.raises((AttributeError, TypeError)):
            r.date_str = "outro"  # type: ignore[misc]


# ===========================================================================
# Exceptions — hierarquia
# ===========================================================================

class TestExceptions:
    def test_operacao_cancelada_e_ipmadalena_error(self):
        assert issubclass(OperacaoCancelada, IPMadalenaError)

    def test_domain_error_e_ipmadalena_error(self):
        assert issubclass(DomainError, IPMadalenaError)

    def test_video_nao_encontrado_e_domain_error(self):
        assert issubclass(VideoNaoEncontrado, DomainError)

    def test_segmento_invalido_e_domain_error(self):
        assert issubclass(SegmentoInvalido, DomainError)

    def test_configuracao_invalida_e_domain_error(self):
        assert issubclass(ConfiguracaoInvalida, DomainError)

    def test_pode_levantar_e_capturar_operacao_cancelada(self):
        with pytest.raises(OperacaoCancelada, match="cancelada"):
            raise OperacaoCancelada("Operação cancelada pelo usuário.")

    def test_pode_capturar_como_ipmadalena_error(self):
        with pytest.raises(IPMadalenaError):
            raise OperacaoCancelada("cancelada")

    def test_ipmadalena_error_e_exception(self):
        with pytest.raises(Exception):
            raise IPMadalenaError("erro base")


# ===========================================================================
# Ports — verificação estrutural (runtime_checkable Protocols)
# ===========================================================================

class TestPorts:
    """
    Verifica que objetos que implementam as assinaturas corretas passam
    na checagem isinstance() dos Protocols com runtime_checkable.

    Nota: Protocol com runtime_checkable só verifica presença dos métodos,
    não suas assinaturas — mas é suficiente para garantir que os nomes
    e a estrutura estão corretos.
    """

    def _make_video_source(self):
        class FakeVideoSource:
            def list_videos(self, date_str, channel_url, **kwargs):
                return []
        return FakeVideoSource()

    def _make_audio_downloader(self):
        class FakeDownloader:
            def download(self, segments, output_dir, **kwargs):
                return []
        return FakeDownloader()

    def _make_cloud_storage(self):
        class FakeStorage:
            def upload(self, files, date_str, **kwargs):
                return ProcessingResult(date_str=date_str)
        return FakeStorage()

    def _make_history_repo(self):
        class FakeHistory:
            def load(self): return {}
            def save(self, h): pass
            def is_processed(self, d): return False
        return FakeHistory()

    def _make_config_repo(self):
        class FakeConfig:
            def load(self): return {}
            def save(self, c): pass
            def get(self, key, default=None): return default
        return FakeConfig()

    def _make_notifier(self):
        class FakeNotifier:
            def notify(self, title, message, **kwargs): pass
        return FakeNotifier()

    def test_ivideo_source_isinstance(self):
        assert isinstance(self._make_video_source(), IVideoSource)

    def test_iaudio_downloader_isinstance(self):
        assert isinstance(self._make_audio_downloader(), IAudioDownloader)

    def test_icloud_storage_isinstance(self):
        assert isinstance(self._make_cloud_storage(), ICloudStorage)

    def test_ihistory_repository_isinstance(self):
        assert isinstance(self._make_history_repo(), IHistoryRepository)

    def test_iconfig_repository_isinstance(self):
        assert isinstance(self._make_config_repo(), IConfigRepository)

    def test_inotifier_isinstance(self):
        assert isinstance(self._make_notifier(), INotifier)

    def test_objeto_sem_metodos_nao_implementa_ivideo_source(self):
        class Vazio:
            pass
        assert not isinstance(Vazio(), IVideoSource)

    def test_objeto_sem_metodos_nao_implementa_iaudio_downloader(self):
        class Vazio:
            pass
        assert not isinstance(Vazio(), IAudioDownloader)
