"""
Testes para composition_root.py.

Verifica que o composition root monta o grafo de dependências corretamente:
  - retorna um ProcessingPresenter com use cases concretos
  - reflete configurações atuais (channel_url, drive_folder_id)
  - delete_after_upload espelha sys.frozen
  - history_repo aponta para HISTORY_FILE
  - build_notifier retorna PlyerNotifier
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

import baixar_audio
from application.use_cases import (
    DownloadSegmentsUseCase,
    EditAudioUseCase,
    GetChaptersUseCase,
    ListVideosUseCase,
    UploadAudioUseCase,
)
from composition_root import (
    build_audio_test_presenter,
    build_notifier,
    build_processing_presenter,
)
from domain.ports import INotifier
from infrastructure.audio.ffmpeg_editor import FfmpegAudioEditor
from infrastructure.drive.gdrive_storage import GoogleDriveStorage
from infrastructure.notification.plyer_notifier import PlyerNotifier
from infrastructure.persistence.json_repositories import (
    JsonConfigRepository,
    JsonHistoryRepository,
)
from infrastructure.youtube.ytdlp_source import (
    YtDlpAudioDownloader,
    YtDlpVideoSource,
)
from presentation.audio_test_presenter import AudioTestPresenter
from presentation.processing_presenter import ProcessingPresenter


# ===========================================================================
# build_processing_presenter()
# ===========================================================================

class TestBuildProcessingPresenter:

    def test_retorna_processing_presenter(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert isinstance(p, ProcessingPresenter)

    def test_use_cases_sao_concretos(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert isinstance(p.list_videos_uc, ListVideosUseCase)
        assert isinstance(p.download_uc,    DownloadSegmentsUseCase)
        assert isinstance(p.edit_uc,        EditAudioUseCase)
        assert isinstance(p.upload_uc,      UploadAudioUseCase)
        assert isinstance(p.chapters_uc,    GetChaptersUseCase)

    def test_chapters_uc_usa_yt_dlp_video_source(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert isinstance(p.chapters_uc.source, YtDlpVideoSource)

    def test_list_videos_uc_e_chapters_uc_compartilham_mesmo_source(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert p.list_videos_uc.source is p.chapters_uc.source

    def test_edit_uc_usa_ffmpeg_editor_e_json_config_repo(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert isinstance(p.edit_uc.editor,      FfmpegAudioEditor)
        assert isinstance(p.edit_uc.config_repo, JsonConfigRepository)

    def test_video_source_e_yt_dlp(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert isinstance(p.list_videos_uc.source, YtDlpVideoSource)
        assert isinstance(p.download_uc.downloader, YtDlpAudioDownloader)

    def test_storage_e_google_drive(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert isinstance(p.upload_uc.storage, GoogleDriveStorage)

    def test_history_repo_aponta_para_history_file(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert isinstance(p.upload_uc.history, JsonHistoryRepository)
        assert p.upload_uc.history._path == baixar_audio.HISTORY_FILE

    def test_channel_url_vem_do_config(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "https://youtube.com/@MeuCanal",
            "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert p.channel_url == "https://youtube.com/@MeuCanal"

    def test_drive_folder_id_vem_do_config(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x",
            "drive_folder_id": "pasta-customizada-42",
        }):
            p = build_processing_presenter()
        assert p.upload_uc.storage._root_folder_id == "pasta-customizada-42"

    def test_download_dir_vem_de_baixar_audio(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert p.download_dir == baixar_audio.DOWNLOAD_DIR

    def test_token_file_e_oauth_vem_de_baixar_audio(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }):
            p = build_processing_presenter()
        assert p.upload_uc.storage._token_file   == baixar_audio.TOKEN_FILE
        assert p.upload_uc.storage._oauth_config is baixar_audio._OAUTH_CLIENT_CONFIG
        assert p.upload_uc.storage._scopes       == baixar_audio.SCOPES

    # -----------------------------------------------------------------------
    # delete_after_upload reflete sys.frozen
    # -----------------------------------------------------------------------

    def test_modo_frozen_seta_delete_after_upload_true(self):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y",
        }), patch.object(sys, "frozen", True, create=True):
            p = build_processing_presenter()
        assert p.upload_uc.storage._delete_after_upload is True

    def test_keep_files_true_suprime_delete_mesmo_frozen(self):
        """keep_files=True impede deleção mesmo no modo frozen (exe)."""
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y", "keep_files": True,
        }), patch.object(sys, "frozen", True, create=True):
            p = build_processing_presenter()
        assert p.upload_uc.storage._delete_after_upload is False

    def test_keep_files_false_mantem_comportamento_frozen(self):
        """keep_files=False (default) — frozen continua deletando."""
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "y", "keep_files": False,
        }), patch.object(sys, "frozen", True, create=True):
            p = build_processing_presenter()
        assert p.upload_uc.storage._delete_after_upload is True

    def test_modo_script_seta_delete_after_upload_false(self):
        # Garante que sys.frozen NÃO está setado
        had_frozen = hasattr(sys, "frozen")
        original = getattr(sys, "frozen", None)
        if had_frozen:
            del sys.frozen
        try:
            with patch("baixar_audio.load_config", return_value={
                "channel_url": "x", "drive_folder_id": "y",
            }):
                p = build_processing_presenter()
            assert p.upload_uc.storage._delete_after_upload is False
        finally:
            if had_frozen:
                sys.frozen = original

    # -----------------------------------------------------------------------
    # Reconstrução reflete mudanças de configuração
    # -----------------------------------------------------------------------

    def test_reconstrucao_reflete_mudancas_no_config(self):
        """Cada chamada lê o config atual — mudanças são refletidas."""
        with patch("baixar_audio.load_config") as mock_cfg:
            mock_cfg.return_value = {"channel_url": "v1", "drive_folder_id": "f1"}
            p1 = build_processing_presenter()
            mock_cfg.return_value = {"channel_url": "v2", "drive_folder_id": "f2"}
            p2 = build_processing_presenter()

        assert p1.channel_url == "v1"
        assert p2.channel_url == "v2"
        assert p1.upload_uc.storage._root_folder_id == "f1"
        assert p2.upload_uc.storage._root_folder_id == "f2"


# ===========================================================================
# build_notifier()
# ===========================================================================

class TestBuildNotifier:

    def test_retorna_plyer_notifier(self):
        assert isinstance(build_notifier(), PlyerNotifier)

    def test_implementa_inotifier_protocol(self):
        assert isinstance(build_notifier(), INotifier)


# ===========================================================================
# build_audio_test_presenter()
# ===========================================================================

class TestBuildAudioTestPresenter:

    def test_retorna_audio_test_presenter(self):
        assert isinstance(build_audio_test_presenter(), AudioTestPresenter)

    def test_usa_ffmpeg_audio_editor(self):
        p = build_audio_test_presenter()
        assert isinstance(p.editor, FfmpegAudioEditor)

    def test_reconstrucao_devolve_instancias_separadas(self):
        # Cada chamada cria um presenter novo (sem estado compartilhado)
        p1 = build_audio_test_presenter()
        p2 = build_audio_test_presenter()
        assert p1 is not p2
