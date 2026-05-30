"""
Testes unitários puros para a camada de domínio.

Sem mocks, sem I/O, sem dependências externas.
Cobre: entities, exceptions, ports (verificação estrutural de Protocol).
"""

import pytest

from domain.audio_presets import (
    EQ_FREQS,
    EQ_GAIN_MAX_DB,
    EQ_GAIN_MIN_DB,
    EQ_PRESET_VOZ_MASCULINA,
    NOISE_INTENSITIES,
)
from domain.entities import (
    AudioEditConfig,
    AudioFile,
    EqBand,
    ProcessingResult,
    Segment,
    Video,
)
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
    IAudioEditor,
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

    def test_subfolder_padrao_none(self):
        """Novo campo subfolder deve ter None como default (retrocompat)."""
        af = AudioFile(path="/tmp/culto.mp3", title="Culto", video_id="abc")
        assert af.subfolder is None

    def test_subfolder_pode_ser_definido(self):
        af = AudioFile(
            path="/tmp/sub/culto.mp3",
            title="Culto",
            video_id="abc",
            subfolder="/tmp/sub",
        )
        assert af.subfolder == "/tmp/sub"

    def test_subfolder_incluido_na_igualdade(self):
        """Dois AudioFiles com o mesmo path mas subfolder diferente não são iguais."""
        af1 = AudioFile(path="/tmp/a.mp3", title="T", video_id="x", subfolder="/tmp/sub1")
        af2 = AudioFile(path="/tmp/a.mp3", title="T", video_id="x", subfolder="/tmp/sub2")
        assert af1 != af2

    def test_subfolder_imutavel(self):
        af = AudioFile(path="/tmp/x.mp3", title="T", video_id="x", subfolder="/tmp/sub")
        with pytest.raises((AttributeError, TypeError)):
            af.subfolder = "/other"  # type: ignore[misc]


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


# ===========================================================================
# audio_presets — constantes do pipeline de edição de áudio
# ===========================================================================

class TestAudioPresets:
    def test_eq_freqs_sao_5_bandas_em_ordem_crescente(self):
        assert len(EQ_FREQS) == 5
        assert list(EQ_FREQS) == sorted(EQ_FREQS)

    def test_eq_freqs_cobrem_espectro_audivel(self):
        assert EQ_FREQS[0] >= 20      # graves
        assert EQ_FREQS[-1] <= 20000  # agudos

    def test_eq_gain_min_e_menor_que_max(self):
        assert EQ_GAIN_MIN_DB < EQ_GAIN_MAX_DB

    def test_preset_voz_masculina_tem_5_bandas(self):
        assert len(EQ_PRESET_VOZ_MASCULINA) == 5

    def test_preset_voz_masculina_freqs_batem_com_eq_freqs(self):
        freqs_preset = tuple(f for f, _ in EQ_PRESET_VOZ_MASCULINA)
        assert freqs_preset == EQ_FREQS

    def test_preset_voz_masculina_corta_graves(self):
        # 80 Hz e 250 Hz devem ter ganho negativo (corte para clareza)
        gains = dict(EQ_PRESET_VOZ_MASCULINA)
        assert gains[80]  < 0
        assert gains[250] < 0

    def test_preset_voz_masculina_realca_presenca(self):
        # 4 kHz deve ter ganho positivo (presença/inteligibilidade)
        gains = dict(EQ_PRESET_VOZ_MASCULINA)
        assert gains[4000] > 0

    def test_noise_intensities_tem_3_niveis(self):
        assert NOISE_INTENSITIES == ("baixa", "media", "alta")


# ===========================================================================
# EqBand
# ===========================================================================

class TestEqBand:
    def test_criacao_basica(self):
        b = EqBand(freq_hz=1000, gain_db=2.5)
        assert b.freq_hz == 1000
        assert b.gain_db == 2.5

    def test_imutavel(self):
        b = EqBand(freq_hz=80, gain_db=-3.0)
        with pytest.raises((AttributeError, TypeError)):
            b.gain_db = 5.0  # type: ignore[misc]

    def test_igualdade_por_valor(self):
        b1 = EqBand(freq_hz=80, gain_db=-3.0)
        b2 = EqBand(freq_hz=80, gain_db=-3.0)
        assert b1 == b2

    def test_diferenca_por_ganho(self):
        b1 = EqBand(freq_hz=80, gain_db=-3.0)
        b2 = EqBand(freq_hz=80, gain_db=+3.0)
        assert b1 != b2


# ===========================================================================
# AudioEditConfig
# ===========================================================================

class TestAudioEditConfigDefaults:
    def test_default_tudo_desligado_exceto_eq_bands(self):
        c = AudioEditConfig()
        assert c.intro_path is None
        assert c.outro_path is None
        assert c.fade_in_enabled  is False
        assert c.fade_out_enabled is False
        assert c.eq_enabled       is False
        assert c.noise_reduction_enabled is False

    def test_default_eq_bands_e_o_preset_voz_masculina(self):
        c = AudioEditConfig()
        bandas = tuple((b.freq_hz, b.gain_db) for b in c.eq_bands)
        assert bandas == EQ_PRESET_VOZ_MASCULINA

    def test_default_intensidade_de_ruido_e_media(self):
        assert AudioEditConfig().noise_reduction_intensity == "media"

    def test_default_fade_secs_padroes_razoaveis(self):
        c = AudioEditConfig()
        assert c.fade_in_secs  == 2.0
        assert c.fade_out_secs == 3.0

    def test_imutavel(self):
        c = AudioEditConfig()
        with pytest.raises((AttributeError, TypeError)):
            c.eq_enabled = True  # type: ignore[misc]


class TestAudioEditConfigHasAnyFilterEnabled:
    def test_default_e_no_op(self):
        assert AudioEditConfig().has_any_filter_enabled is False

    def test_fade_in_ativa(self):
        assert AudioEditConfig(fade_in_enabled=True).has_any_filter_enabled is True

    def test_fade_out_ativa(self):
        assert AudioEditConfig(fade_out_enabled=True).has_any_filter_enabled is True

    def test_eq_ativa(self):
        assert AudioEditConfig(eq_enabled=True).has_any_filter_enabled is True

    def test_noise_reduction_ativa(self):
        assert AudioEditConfig(noise_reduction_enabled=True).has_any_filter_enabled is True

    def test_intro_path_ativa(self):
        assert AudioEditConfig(intro_path="/tmp/intro.mp3").has_any_filter_enabled is True

    def test_outro_path_ativa(self):
        assert AudioEditConfig(outro_path="/tmp/outro.mp3").has_any_filter_enabled is True


class TestAudioEditConfigToDict:
    def test_round_trip_default(self):
        original = AudioEditConfig()
        roundtrip = AudioEditConfig.from_dict(original.to_dict())
        assert roundtrip == original

    def test_round_trip_com_alteracoes(self):
        original = AudioEditConfig(
            intro_path="/tmp/i.mp3",
            outro_path="/tmp/o.mp3",
            intro_overlap_secs=1.5,
            outro_overlap_secs=2.5,
            fade_in_enabled=True,
            fade_in_secs=4.0,
            fade_out_enabled=True,
            fade_out_secs=5.0,
            eq_enabled=True,
            eq_bands=(EqBand(80, -5.0), EqBand(1000, 0.0), EqBand(10000, 2.0)),
            noise_reduction_enabled=True,
            noise_reduction_intensity="alta",
        )
        roundtrip = AudioEditConfig.from_dict(original.to_dict())
        assert roundtrip == original

    def test_to_dict_e_serializavel_em_json(self):
        import json
        d = AudioEditConfig().to_dict()
        # Não deve lançar nenhuma exceção
        json.dumps(d)

    def test_to_dict_usa_listas_para_eq_bands(self):
        d = AudioEditConfig().to_dict()
        assert isinstance(d["eq_bands"], list)
        assert all(isinstance(b, dict) for b in d["eq_bands"])
        assert all("freq_hz" in b and "gain_db" in b for b in d["eq_bands"])


class TestAudioEditConfigFromDict:
    def test_none_retorna_default(self):
        assert AudioEditConfig.from_dict(None) == AudioEditConfig()

    def test_dict_vazio_retorna_default(self):
        assert AudioEditConfig.from_dict({}) == AudioEditConfig()

    def test_campos_ausentes_recebem_default(self):
        c = AudioEditConfig.from_dict({"fade_in_enabled": True})
        assert c.fade_in_enabled is True
        # Demais campos com defaults
        assert c.fade_in_secs == 2.0
        assert c.eq_enabled is False
        assert c.noise_reduction_intensity == "media"

    def test_eq_bands_ausente_aplica_preset_voz_masculina(self):
        c = AudioEditConfig.from_dict({"eq_enabled": True})
        bandas = tuple((b.freq_hz, b.gain_db) for b in c.eq_bands)
        assert bandas == EQ_PRESET_VOZ_MASCULINA

    def test_eq_bands_vazio_aplica_preset(self):
        # Lista vazia explícita também aciona o default
        c = AudioEditConfig.from_dict({"eq_bands": []})
        assert len(c.eq_bands) == 5

    def test_eq_bands_customizadas_preservam_valores(self):
        c = AudioEditConfig.from_dict({
            "eq_bands": [
                {"freq_hz": 100, "gain_db": -6.0},
                {"freq_hz": 5000, "gain_db": 4.0},
            ],
        })
        assert len(c.eq_bands) == 2
        assert c.eq_bands[0] == EqBand(100, -6.0)
        assert c.eq_bands[1] == EqBand(5000, 4.0)

    def test_floats_sao_convertidos_de_int(self):
        c = AudioEditConfig.from_dict({
            "fade_in_secs": 3,           # int em vez de float
            "fade_out_secs": 5,
            "intro_overlap_secs": 1,
        })
        assert c.fade_in_secs        == 3.0
        assert c.fade_out_secs       == 5.0
        assert c.intro_overlap_secs  == 1.0


# ===========================================================================
# IAudioEditor (Protocol)
# ===========================================================================

class TestIAudioEditorProtocol:
    def _make_editor(self):
        class FakeEditor:
            def process(self, audio, config, *, cancel_event=None,
                        on_log=None, on_progress=None):
                return audio
        return FakeEditor()

    def test_iaudio_editor_isinstance(self):
        assert isinstance(self._make_editor(), IAudioEditor)

    def test_objeto_sem_metodo_nao_implementa(self):
        class Vazio:
            pass
        assert not isinstance(Vazio(), IAudioEditor)


# ===========================================================================
# AudioEditConfig — Nivelamento de volume (volume_norm_*)
# ===========================================================================

class TestAudioEditConfigVolumeNorm:

    def test_default_volume_norm_disabled(self):
        assert AudioEditConfig().volume_norm_enabled is False

    def test_default_volume_norm_lufs(self):
        assert AudioEditConfig().volume_norm_lufs == -16.0

    def test_volume_norm_enabled_ativa_has_any_filter(self):
        assert AudioEditConfig(volume_norm_enabled=True).has_any_filter_enabled is True

    def test_volume_norm_disabled_nao_ativa_sozinho(self):
        cfg = AudioEditConfig(volume_norm_enabled=False)
        assert cfg.has_any_filter_enabled is False

    def test_to_dict_inclui_volume_norm(self):
        d = AudioEditConfig(volume_norm_enabled=True, volume_norm_lufs=-20.0).to_dict()
        assert d["volume_norm_enabled"] is True
        assert d["volume_norm_lufs"] == -20.0

    def test_from_dict_le_volume_norm(self):
        c = AudioEditConfig.from_dict({
            "volume_norm_enabled": True,
            "volume_norm_lufs": -14.0,
        })
        assert c.volume_norm_enabled is True
        assert c.volume_norm_lufs == -14.0

    def test_from_dict_default_quando_ausente(self):
        c = AudioEditConfig.from_dict({})
        assert c.volume_norm_enabled is False
        assert c.volume_norm_lufs == -16.0

    def test_roundtrip_volume_norm(self):
        original = AudioEditConfig(volume_norm_enabled=True, volume_norm_lufs=-12.0)
        roundtrip = AudioEditConfig.from_dict(original.to_dict())
        assert roundtrip.volume_norm_enabled is True
        assert roundtrip.volume_norm_lufs == -12.0


class TestAudioEditConfigBgMusic:
    """Testa os campos de música de fundo adicionados ao AudioEditConfig."""

    def test_defaults_bg_music(self):
        cfg = AudioEditConfig()
        assert cfg.bg_music_path is None
        assert cfg.bg_music_enabled is False
        assert cfg.bg_music_volume == 0.12
        assert cfg.bg_music_delay == 0.0
        assert cfg.bg_music_fade_in == 3.0
        assert cfg.bg_music_fade_out == 6.0

    def test_bg_music_habilitado_ativa_has_any_filter(self):
        cfg = AudioEditConfig(bg_music_enabled=True, bg_music_path="/tmp/music.mp3")
        assert cfg.has_any_filter_enabled is True

    def test_bg_music_habilitado_sem_path_nao_ativa_filter(self):
        """enabled=True mas path=None não deve ativar o pipeline."""
        cfg = AudioEditConfig(bg_music_enabled=True, bg_music_path=None)
        assert cfg.has_any_filter_enabled is False

    def test_bg_music_desabilitado_nao_ativa_filter(self):
        cfg = AudioEditConfig(bg_music_enabled=False, bg_music_path="/tmp/music.mp3")
        assert cfg.has_any_filter_enabled is False

    def test_to_dict_inclui_campos_bg_music(self):
        cfg = AudioEditConfig(
            bg_music_path="/tmp/music.mp3",
            bg_music_enabled=True,
            bg_music_volume=0.15,
            bg_music_delay=2.0,
            bg_music_fade_in=4.0,
            bg_music_fade_out=8.0,
        )
        d = cfg.to_dict()
        assert d["bg_music_path"] == "/tmp/music.mp3"
        assert d["bg_music_enabled"] is True
        assert d["bg_music_volume"] == 0.15
        assert d["bg_music_delay"] == 2.0
        assert d["bg_music_fade_in"] == 4.0
        assert d["bg_music_fade_out"] == 8.0

    def test_from_dict_le_campos_bg_music(self):
        cfg = AudioEditConfig.from_dict({
            "bg_music_path": "/tmp/music.mp3",
            "bg_music_enabled": True,
            "bg_music_volume": 0.20,
            "bg_music_delay": 3.0,
            "bg_music_fade_in": 5.0,
            "bg_music_fade_out": 7.0,
        })
        assert cfg.bg_music_path == "/tmp/music.mp3"
        assert cfg.bg_music_enabled is True
        assert cfg.bg_music_volume == 0.20
        assert cfg.bg_music_delay == 3.0
        assert cfg.bg_music_fade_in == 5.0
        assert cfg.bg_music_fade_out == 7.0

    def test_from_dict_defaults_quando_ausentes(self):
        cfg = AudioEditConfig.from_dict({})
        assert cfg.bg_music_path is None
        assert cfg.bg_music_enabled is False
        assert cfg.bg_music_volume == 0.12
        assert cfg.bg_music_delay == 0.0
        assert cfg.bg_music_fade_in == 3.0
        assert cfg.bg_music_fade_out == 6.0

    def test_default_bg_music_loop_true(self):
        assert AudioEditConfig().bg_music_loop is True

    def test_to_dict_inclui_bg_music_loop(self):
        d = AudioEditConfig(bg_music_loop=False).to_dict()
        assert d["bg_music_loop"] is False

    def test_from_dict_le_bg_music_loop(self):
        cfg = AudioEditConfig.from_dict({"bg_music_loop": False})
        assert cfg.bg_music_loop is False

    def test_from_dict_default_loop_quando_ausente(self):
        cfg = AudioEditConfig.from_dict({})
        assert cfg.bg_music_loop is True

    def test_roundtrip_bg_music(self):
        original = AudioEditConfig(
            bg_music_path="/tmp/music.mp3",
            bg_music_enabled=True,
            bg_music_volume=0.10,
            bg_music_delay=1.5,
            bg_music_fade_in=2.5,
            bg_music_fade_out=5.0,
            bg_music_loop=False,
        )
        roundtrip = AudioEditConfig.from_dict(original.to_dict())
        assert roundtrip.bg_music_path == "/tmp/music.mp3"
        assert roundtrip.bg_music_enabled is True
        assert roundtrip.bg_music_volume == 0.10
        assert roundtrip.bg_music_delay == 1.5
        assert roundtrip.bg_music_fade_in == 2.5
        assert roundtrip.bg_music_fade_out == 5.0
        assert roundtrip.bg_music_loop is False

