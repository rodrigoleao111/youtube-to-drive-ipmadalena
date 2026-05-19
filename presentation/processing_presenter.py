"""
ProcessingPresenter — coordenador do pipeline de processamento de uma data.

Combina os use cases da camada `application/` em duas operações de alto nível
chamadas pelos worker threads da GUI:

  - list_videos(date_str)               → List[dict]   (Fase 1 do fluxo)
  - process_segments(date_str, segs)    → List[str]    (Fase 2: download + upload)

Não conhece Tk nem nenhuma biblioteca de UI. A View (App) chama os métodos
do presenter de dentro de seus threads worker e fornece callbacks
(`on_log`, `on_status`, `on_progress`, etc.) que o presenter aciona durante
a execução. A View é responsável pelo marshalling dos callbacks para a thread
da UI (via queue.Queue ou after()).

O presenter não gerencia threads, filas, popups ou qualquer estado da UI —
sua responsabilidade é exclusivamente compor os use cases do domínio em
operações com significado para a tela principal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from application.use_cases import (
    DownloadSegmentsUseCase,
    EditAudioUseCase,
    GetChaptersUseCase,
    ListVideosUseCase,
    UploadAudioUseCase,
)
from domain.entities import Segment
from domain.exceptions import VideoNaoEncontrado


@dataclass
class ProcessingPresenter:
    """
    Coordena o fluxo principal de processamento (list → download → upload+history).

    Recebe os três use cases via injeção de dependência, mantendo a presentation
    independente de qual implementação concreta de cada port está em uso.
    """

    list_videos_uc: ListVideosUseCase
    download_uc: DownloadSegmentsUseCase
    edit_uc: EditAudioUseCase
    upload_uc: UploadAudioUseCase
    chapters_uc: GetChaptersUseCase
    channel_url: str
    download_dir: str

    # -----------------------------------------------------------------------
    # Fase 1 do fluxo: listagem
    # -----------------------------------------------------------------------

    def list_videos(
        self,
        date_str: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> List[dict]:
        """
        Lista os vídeos para a data via ListVideosUseCase.

        Retorna lista de dicts com chaves ``id``, ``title``, ``upload_date`` —
        formato esperado pelos popups de seleção da GUI atual. A conversão
        Video → dict acontece aqui, isolando a View dos tipos de domínio.

        Raises
        ------
        RuntimeError
            Se nenhum vídeo for encontrado (VideoNaoEncontrado é convertido).
        OperacaoCancelada
            Se ``cancel_event`` for sinalizado durante a busca.
        """
        try:
            videos = self.list_videos_uc.execute(
                date_str,
                self.channel_url,
                cancel_event=cancel_event,
                on_log=on_log,
                on_status=on_status,
            )
        except VideoNaoEncontrado as exc:
            # Mantém o contrato histórico de baixar_audio.list_videos()
            raise RuntimeError(str(exc)) from exc

        return [
            {"id": v.id, "title": v.title, "upload_date": v.upload_date}
            for v in videos
        ]

    # -----------------------------------------------------------------------
    # Fase 1b do fluxo: capítulos de um vídeo
    # -----------------------------------------------------------------------

    def get_chapters(
        self,
        video_id: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> List[dict]:
        """
        Retorna os capítulos do vídeo como lista de dicts.

        Cada dict tem chaves ``title``, ``start`` e ``end`` (strings HH:MM:SS).
        Retorna lista vazia se o vídeo não tiver capítulos.
        """
        return self.chapters_uc.execute(
            video_id,
            cancel_event=cancel_event,
            on_log=on_log,
        )

    # -----------------------------------------------------------------------
    # Fase 2 do fluxo: download + upload + registro
    # -----------------------------------------------------------------------

    def process_segments(
        self,
        date_str: str,
        segments_data: List[dict],
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_download_progress: Optional[Callable[[float], None]] = None,
        on_edit_progress: Optional[Callable[[float], None]] = None,
        on_upload_progress: Optional[Callable[[float], None]] = None,
        on_upload_stats: Optional[Callable] = None,
    ) -> List[str]:
        """
        Faz download, edição e upload dos segmentos selecionados.

        ``segments_data`` é o formato esperado pela GUI:
            [{"id": str, "title": str, "start": str|None, "end": str|None}, ...]

        Etapas:
          1. Converte dicts → Segment (entidade do domínio).
          2. ``DownloadSegmentsUseCase.execute()`` → List[AudioFile].
          3. ``EditAudioUseCase.execute()`` aplica vinhetas/fade/EQ/denoise
             quando habilitados (no-op rápido caso contrário).
          4. ``UploadAudioUseCase.execute()`` → ProcessingResult (também grava
             no histórico via IHistoryRepository quando há ao menos um upload).

        Returns
        -------
        List[str]
            Títulos dos segmentos processados (na mesma ordem de entrada),
            usados pelo App para a mensagem de conclusão e notificação.

        Raises
        ------
        RuntimeError
            Se o download não gerar nenhum arquivo MP3.
        OperacaoCancelada
            Se ``cancel_event`` for sinalizado durante download, edição ou upload.
        """
        segments = [
            Segment(
                video_id=s["id"],
                title=s["title"],
                start=s.get("start"),
                end=s.get("end"),
            )
            for s in segments_data
        ]

        audio_files = self.download_uc.execute(
            segments,
            self.download_dir,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
            on_progress=on_download_progress,
        )

        if not audio_files:
            raise RuntimeError("Nenhum arquivo MP3 gerado após o download.")

        audio_files = self.edit_uc.execute(
            audio_files,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
            on_progress=on_edit_progress,
        )

        self.upload_uc.execute(
            date_str,
            audio_files,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
            on_progress=on_upload_progress,
            on_upload_stats=on_upload_stats,
        )

        return [s["title"] for s in segments_data]
