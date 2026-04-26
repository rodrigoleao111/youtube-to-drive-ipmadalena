"""
Use cases da camada de aplicação.

Orquestram os ports do domínio sem conhecer detalhes de infraestrutura.
Cada use case recebe os ports via injeção de dependência no construtor,
seguindo o princípio da inversão de dependência (DIP).

Responsabilidade:
  - Compor ports do domínio em sequências de operações com significado de negócio.
  - Não conter lógica de UI, I/O direto ou referências a infraestrutura concreta.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from domain.entities import AudioFile, ProcessingResult, Segment, Video
from domain.ports import (
    IAudioDownloader,
    ICloudStorage,
    IHistoryRepository,
    IVideoSource,
)


# ---------------------------------------------------------------------------
# Fase 1 do fluxo: listagem de vídeos
# ---------------------------------------------------------------------------

@dataclass
class ListVideosUseCase:
    """
    Lista os vídeos disponíveis para uma data no canal configurado.

    Delega inteiramente para IVideoSource; existe na camada de aplicação
    para isolar o caller dos detalhes de qual implementação está em uso.
    """

    source: IVideoSource

    def execute(
        self,
        date_str: str,
        channel_url: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> List[Video]:
        """
        Retorna a lista de vídeos publicados na data informada.

        Parameters
        ----------
        date_str:
            Data no formato DD/MM/AAAA.
        channel_url:
            URL do canal no YouTube.
        cancel_event:
            threading.Event opcional — propaga OperacaoCancelada se sinalizado.
        on_log / on_status:
            Callbacks de feedback para a UI.

        Raises
        ------
        VideoNaoEncontrado
            Se nenhum vídeo for encontrado para a data.
        OperacaoCancelada
            Se cancel_event for sinalizado durante a busca.
        """
        return self.source.list_videos(
            date_str,
            channel_url,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
        )


# ---------------------------------------------------------------------------
# Fase 2 do fluxo: download dos segmentos selecionados
# ---------------------------------------------------------------------------

@dataclass
class DownloadSegmentsUseCase:
    """
    Baixa o áudio dos segmentos selecionados para um diretório local.

    Delega para IAudioDownloader sem acessar disco ou subprocess diretamente.
    """

    downloader: IAudioDownloader

    def execute(
        self,
        segments: List[Segment],
        output_dir: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> List[AudioFile]:
        """
        Baixa os segmentos e retorna a lista de AudioFile gerados.

        Parameters
        ----------
        segments:
            Segmentos a baixar (cada um pode ser trecho ou vídeo completo).
        output_dir:
            Pasta de destino dos arquivos MP3.
        cancel_event:
            threading.Event opcional.
        on_log / on_status / on_progress:
            Callbacks de feedback para a UI.

        Raises
        ------
        OperacaoCancelada
            Se cancel_event for sinalizado entre vídeos.
        RuntimeError
            Se yt-dlp retornar código de saída diferente de zero.
        """
        return self.downloader.download(
            segments,
            output_dir,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
            on_progress=on_progress,
        )


# ---------------------------------------------------------------------------
# Fase 3 do fluxo: upload + registro no histórico
# ---------------------------------------------------------------------------

@dataclass
class UploadAudioUseCase:
    """
    Envia os arquivos de áudio para a nuvem e registra a data no histórico.

    Esta é a principal responsabilidade da camada de aplicação: compor dois
    ports do domínio (ICloudStorage + IHistoryRepository) em uma única
    operação atômica do ponto de vista do negócio.

    O histórico é registrado somente quando ao menos um arquivo é enviado
    com sucesso — datas com todos os arquivos ignorados (duplicatas) não
    geram nova entrada no histórico.
    """

    storage: ICloudStorage
    history: IHistoryRepository

    def execute(
        self,
        date_str: str,
        audio_files: List[AudioFile],
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
        **extra_storage_kwargs,
    ) -> ProcessingResult:
        """
        Faz upload dos arquivos e persiste o histórico ao concluir.

        Parameters
        ----------
        date_str:
            Data processada, no formato DD/MM/AAAA.
        audio_files:
            Lista de AudioFile a enviar.
        cancel_event:
            threading.Event opcional.
        on_log / on_status / on_progress:
            Callbacks de feedback para a UI.
        **extra_storage_kwargs:
            Kwargs adicionais repassados a ICloudStorage.upload()
            (ex.: ``on_upload_stats`` usado por GoogleDriveStorage).

        Returns
        -------
        ProcessingResult
            Totais de arquivos enviados e ignorados (duplicatas).

        Raises
        ------
        OperacaoCancelada
            Se cancel_event for sinalizado durante o upload.
        """
        result = self.storage.upload(
            audio_files,
            date_str,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
            on_progress=on_progress,
            **extra_storage_kwargs,
        )

        # Registra no histórico apenas quando ao menos um arquivo foi enviado
        if result.uploaded_files:
            self.history.record(date_str, [af.title for af in audio_files])

        return result
