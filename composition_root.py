"""
Composition root — fábrica única do ProcessingPresenter.

Este é o ÚNICO módulo do projeto que conhece todas as camadas (domain,
application, infrastructure, presentation) e monta o grafo de dependências.
Os demais módulos (app.py, baixar_audio.run, ...) apenas chamam
`build_processing_presenter()` e recebem um presenter pronto.

Reconstruir o presenter a cada chamada permite refletir mudanças nas
configurações (channel_url, drive_folder_id) que o usuário tenha feito
desde a última invocação.

Princípio: o composition root é o único lugar onde a "regra de ouro" da
Clean Architecture (camadas internas não conhecem camadas externas) é
deliberadamente quebrada — porque ele PRECISA conhecer todas para conectá-las.
"""

from __future__ import annotations

import sys

import baixar_audio
from application.use_cases import (
    DownloadSegmentsUseCase,
    EditAudioUseCase,
    GetChaptersUseCase,
    ListVideosUseCase,
    UploadAudioUseCase,
)
from infrastructure.audio.ffmpeg_editor import FfmpegAudioEditor
from infrastructure.drive.gdrive_storage import GoogleDriveStorage
from infrastructure.notification.plyer_notifier import PlyerNotifier
from infrastructure.persistence.json_repositories import JsonHistoryRepository
from infrastructure.youtube.ytdlp_source import (
    YtDlpAudioDownloader,
    YtDlpVideoSource,
)
from presentation.audio_test_presenter import AudioTestPresenter
from presentation.processing_presenter import ProcessingPresenter


def build_processing_presenter() -> ProcessingPresenter:
    """
    Constrói um ProcessingPresenter fresco com todos os adaptadores wired.

    GoogleDriveStorage lê drive_folder_id no construtor; chamar este builder
    a cada operação garante que mudanças nas configurações sejam refletidas.
    """
    cfg          = baixar_audio.load_config()
    config_repo  = baixar_audio.config_repo()

    storage = GoogleDriveStorage(
        token_file          = baixar_audio.TOKEN_FILE,
        oauth_config        = baixar_audio._OAUTH_CLIENT_CONFIG,
        scopes              = baixar_audio.SCOPES,
        root_folder_id      = cfg["drive_folder_id"],
        delete_after_upload = getattr(sys, "frozen", False) and not cfg.get("keep_files", False),
    )
    history = JsonHistoryRepository(file_path=baixar_audio.HISTORY_FILE)

    video_source = YtDlpVideoSource()

    return ProcessingPresenter(
        list_videos_uc = ListVideosUseCase(source=video_source),
        download_uc    = DownloadSegmentsUseCase(downloader=YtDlpAudioDownloader()),
        edit_uc        = EditAudioUseCase(
            editor        = FfmpegAudioEditor(),
            config_repo   = config_repo,
            # Expande basenames persistidos no config.json → paths absolutos
            # dentro de VINHETAS_DIR (portabilidade entre instalações).
            path_resolver = baixar_audio.audio_edit_resolve_paths,
        ),
        upload_uc      = UploadAudioUseCase(storage=storage, history=history),
        chapters_uc    = GetChaptersUseCase(source=video_source),
        channel_url    = cfg["channel_url"],
        download_dir   = baixar_audio.DOWNLOAD_DIR,
        upload_enabled = bool(cfg.get("upload_to_drive", True)),
    )


def build_notifier() -> PlyerNotifier:
    """Constrói o adaptador de notificações desktop (implementa INotifier)."""
    return PlyerNotifier()


def build_audio_test_presenter() -> AudioTestPresenter:
    """
    Constrói um presenter para o teste de configuração de áudio.

    Usado pela página "Configurações de Áudio" (SettingsDialog) para gerar
    previews a partir de um arquivo de exemplo do usuário, aplicando a
    configuração que está na tela (sem precisar salvar antes).

    Reaproveita o mesmo `FfmpegAudioEditor` do pipeline de produção.
    """
    return AudioTestPresenter(editor=FfmpegAudioEditor())
