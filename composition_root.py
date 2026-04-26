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
    ListVideosUseCase,
    UploadAudioUseCase,
)
from infrastructure.drive.gdrive_storage import GoogleDriveStorage
from infrastructure.notification.plyer_notifier import PlyerNotifier
from infrastructure.persistence.json_repositories import JsonHistoryRepository
from infrastructure.youtube.ytdlp_source import (
    YtDlpAudioDownloader,
    YtDlpVideoSource,
)
from presentation.processing_presenter import ProcessingPresenter


def build_processing_presenter() -> ProcessingPresenter:
    """
    Constrói um ProcessingPresenter fresco com todos os adaptadores wired.

    GoogleDriveStorage lê drive_folder_id no construtor; chamar este builder
    a cada operação garante que mudanças nas configurações sejam refletidas.
    """
    cfg = baixar_audio.load_config()

    storage = GoogleDriveStorage(
        token_file          = baixar_audio.TOKEN_FILE,
        oauth_config        = baixar_audio._OAUTH_CLIENT_CONFIG,
        scopes              = baixar_audio.SCOPES,
        root_folder_id      = cfg["drive_folder_id"],
        delete_after_upload = getattr(sys, "frozen", False),
    )
    history = JsonHistoryRepository(file_path=baixar_audio.HISTORY_FILE)

    return ProcessingPresenter(
        list_videos_uc = ListVideosUseCase(source=YtDlpVideoSource()),
        download_uc    = DownloadSegmentsUseCase(downloader=YtDlpAudioDownloader()),
        upload_uc      = UploadAudioUseCase(storage=storage, history=history),
        channel_url    = cfg["channel_url"],
        download_dir   = baixar_audio.DOWNLOAD_DIR,
    )


def build_notifier() -> PlyerNotifier:
    """Constrói o adaptador de notificações desktop (implementa INotifier)."""
    return PlyerNotifier()
