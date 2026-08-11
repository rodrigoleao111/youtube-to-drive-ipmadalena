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

from domain.entities import AudioEditConfig, AudioFile, ProcessingResult, Segment, Video
from domain.ports import (
    IAudioDownloader,
    IAudioEditor,
    IChapterSource,
    ICloudStorage,
    IConfigRepository,
    IHistoryRepository,
    IVideoFetcher,
    IVideoSource,
)


def _noop(*_a, **_kw):
    pass


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
# Fase 1 (alternativa): resolução de um vídeo a partir do link
# ---------------------------------------------------------------------------

@dataclass
class FetchVideoUseCase:
    """
    Resolve um único vídeo a partir do link informado pelo usuário.

    É a alternativa ao ListVideosUseCase quando o usuário já sabe qual vídeo
    quer processar: em vez de varrer o canal por data, vai direto ao vídeo.
    Delega para IVideoFetcher.
    """

    source: IVideoFetcher

    def execute(
        self,
        url: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> Video:
        """
        Retorna o Video correspondente ao link.

        Parameters
        ----------
        url:
            Link do vídeo no YouTube (ou o ID de 11 caracteres).
        cancel_event:
            threading.Event opcional — propaga OperacaoCancelada se sinalizado.
        on_log / on_status:
            Callbacks de feedback para a UI.

        Raises
        ------
        VideoNaoEncontrado
            Se o link for inválido ou o vídeo não puder ser resolvido.
        OperacaoCancelada
            Se cancel_event for sinalizado durante a busca.
        """
        return self.source.fetch_video(
            url,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
        )


# ---------------------------------------------------------------------------
# Fase 1b do fluxo: busca de capítulos de um vídeo
# ---------------------------------------------------------------------------

@dataclass
class GetChaptersUseCase:
    """
    Retorna os capítulos de um vídeo do YouTube.

    Delega para IChapterSource; existe na camada de aplicação para isolar
    o caller dos detalhes de implementação (yt-dlp, etc.).
    """

    source: IChapterSource

    def execute(
        self,
        video_id: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> List[dict]:
        """
        Retorna lista de dicts com chaves ``title``, ``start``, ``end`` (HH:MM:SS).

        Retorna lista vazia se o vídeo não tiver capítulos.

        Parameters
        ----------
        video_id:
            ID do vídeo no YouTube.
        cancel_event:
            threading.Event opcional — propaga OperacaoCancelada se sinalizado.
        on_log:
            Callback de log para a UI.
        """
        return self.source.get_chapters(
            video_id,
            cancel_event=cancel_event,
            on_log=on_log,
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
# Fase 2.5 do fluxo: edição de áudio (vinhetas, fade, EQ, denoise)
# ---------------------------------------------------------------------------

@dataclass
class EditAudioUseCase:
    """
    Aplica edição de áudio em uma lista de AudioFiles entre o download e o
    upload — vinhetas, fade in/out, equalização e redução de ruído.

    A configuração é lida do `IConfigRepository` a cada execução (assim
    mudanças feitas pelo usuário desde a última operação são refletidas).
    Quando `AudioEditConfig.has_any_filter_enabled` é False, é um no-op rápido:
    a lista de entrada é devolvida inalterada e o editor não é chamado.

    O `IAudioEditor` substitui cada arquivo no caminho original (path
    preservado), então a lista de saída tem os mesmos `AudioFile`s da entrada.

    Atributos
    ---------
    editor:
        Implementação concreta do `IAudioEditor` que aplica os filtros.
    config_repo:
        Repositório de configuração — ``execute()`` chama ``load()`` a cada
        invocação para refletir mudanças feitas pelo usuário.
    path_resolver:
        Função opcional aplicada ao dict ``audio_edit`` lido do config antes
        de construir o `AudioEditConfig`. Composition root injeta um resolver
        que expande basenames de vinheta para paths absolutos (vide
        `baixar_audio.audio_edit_resolve_paths`). Default = identidade.
    """

    editor: IAudioEditor
    config_repo: IConfigRepository
    path_resolver: Callable[[dict], dict] = lambda d: d

    def execute(
        self,
        audio_files: List[AudioFile],
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> List[AudioFile]:
        """
        Aplica o pipeline de edição em cada arquivo da lista.

        Parameters
        ----------
        audio_files:
            Arquivos baixados (substituídos in-place no disco quando há filtros).
        cancel_event:
            threading.Event opcional — propaga OperacaoCancelada se sinalizado.
        on_log / on_status / on_progress:
            Callbacks de feedback para a UI. ``on_progress`` recebe um valor
            normalizado em [0.0, 1.0] cobrindo o lote inteiro (cada arquivo
            ocupa ``1/n`` da barra).

        Returns
        -------
        List[AudioFile]
            Mesma lista de entrada (paths preservados; conteúdo dos arquivos
            no disco pode ter sido editado).
        """
        log    = on_log    if callable(on_log)    else _noop
        status = on_status if callable(on_status) else _noop

        cfg_dict = (self.config_repo.load() or {}).get("audio_edit") or {}
        cfg_dict = self.path_resolver(cfg_dict)
        config = AudioEditConfig.from_dict(cfg_dict)

        if not config.has_any_filter_enabled:
            log("[Edição] Configuração de edição desabilitada — pulando.")
            return audio_files

        n = max(1, len(audio_files))
        status("Editando áudio...")
        for idx, af in enumerate(audio_files):
            log(f"[Edição] Processando {idx + 1}/{n}: {af.title}")

            def _scoped_progress(p: float, _idx=idx) -> None:
                if callable(on_progress):
                    on_progress((_idx + p) / n)

            self.editor.process(
                af,
                config,
                cancel_event=cancel_event,
                on_log=on_log,
                on_progress=_scoped_progress,
            )

        if callable(on_progress):
            on_progress(1.0)
        return audio_files


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
