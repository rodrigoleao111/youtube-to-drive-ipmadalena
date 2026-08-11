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

import os
from dataclasses import dataclass
from typing import Callable, List, Optional

from application.use_cases import (
    DownloadSegmentsUseCase,
    EditAudioUseCase,
    FetchVideoUseCase,
    GetChaptersUseCase,
    ListVideosUseCase,
    UploadAudioUseCase,
)
from domain.entities import AudioFile, Segment
from domain.exceptions import VideoNaoEncontrado
from domain.ports import IArchiver


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
    upload_enabled: bool = True
    """Quando False, o passo de upload para o Drive é pulado."""

    fetch_video_uc: Optional[FetchVideoUseCase] = None
    """
    Use case do modo "link" (Fase 1 alternativa). Opcional apenas para não
    obrigar quem só usa o fluxo por data a montá-lo; o composition root
    sempre injeta. `fetch_video()` levanta RuntimeError se estiver ausente.
    """

    archiver: Optional[IArchiver] = None
    """
    Compactador usado para empacotar cada episódio antes do upload (áudio +
    capa + descrição em um único .zip). Sem ele, os arquivos sobem soltos.
    """

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
    # Fase 1 (alternativa): vídeo único a partir do link
    # -----------------------------------------------------------------------

    def fetch_video(
        self,
        url: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> dict:
        """
        Resolve o vídeo do link via FetchVideoUseCase.

        Retorna um dict no MESMO formato dos itens de ``list_videos()``
        (``id``, ``title``, ``upload_date``), para que a View trate os dois
        modos — busca por data e link direto — com o mesmo código a partir daqui.

        Raises
        ------
        RuntimeError
            Se o link for inválido ou o vídeo não puder ser resolvido
            (VideoNaoEncontrado é convertido, como em ``list_videos()``), ou
            se o presenter tiver sido construído sem ``fetch_video_uc``.
        OperacaoCancelada
            Se ``cancel_event`` for sinalizado durante a busca.
        """
        if self.fetch_video_uc is None:
            raise RuntimeError(
                "Busca por link indisponível: presenter construído sem fetch_video_uc."
            )

        try:
            video = self.fetch_video_uc.execute(
                url,
                cancel_event=cancel_event,
                on_log=on_log,
                on_status=on_status,
            )
        except VideoNaoEncontrado as exc:
            raise RuntimeError(str(exc)) from exc

        return {
            "id":          video.id,
            "title":       video.title,
            "upload_date": video.upload_date,
        }

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
            raise RuntimeError("Nenhum arquivo de áudio gerado após o download.")

        audio_files = self.edit_uc.execute(
            audio_files,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
            on_progress=on_edit_progress,
        )

        if self.upload_enabled:
            upload_files = self._build_upload_list(audio_files, on_log=on_log)
            self.upload_uc.execute(
                date_str,
                upload_files,
                cancel_event=cancel_event,
                on_log=on_log,
                on_status=on_status,
                on_progress=on_upload_progress,
                on_upload_stats=on_upload_stats,
            )
        else:
            _noop = lambda *_a, **_kw: None
            on_status and on_status("Upload para o Drive desabilitado — arquivos mantidos localmente.")
            on_log and on_log("Upload para o Drive desabilitado nas configurações.")

        return [s["title"] for s in segments_data]

    # -----------------------------------------------------------------------
    # Empacotamento para upload
    # -----------------------------------------------------------------------

    def build_upload_package(
        self,
        audio: AudioFile,
        *,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> List[AudioFile]:
        """
        Monta a lista de upload de UM áudio já baixado.

        Existe para o re-envio manual da tela Início, que não passa pelo
        pipeline de download mas precisa subir o mesmo pacote `.zip` que o
        fluxo normal — senão o Drive fica com uma mistura de pacotes e MP3
        soltos para o mesmo episódio.
        """
        return self._build_upload_list([audio], on_log=on_log)

    # -----------------------------------------------------------------------
    # Helpers privados
    # -----------------------------------------------------------------------

    # Vídeos ficam fora do zip e sobem ao lado: já são formatos comprimidos e
    # grandes, zipar não reduz nada e só atrasa o upload.
    _EXT_FORA_DO_PACOTE = (".mp4", ".mkv", ".webm")

    # Nunca sobem nem entram no pacote: pacotes de execuções anteriores (que
    # seriam duplicados no Drive) e temporários de uma edição interrompida.
    _EXT_IGNORADAS = (".zip", ".tmp")

    def _build_upload_list(
        self,
        audio_files: List[AudioFile],
        *,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> List[AudioFile]:
        """
        Monta a lista de arquivos para upload a partir das subpastas.

        Para cada AudioFile com ``subfolder`` preenchido, os artefatos do
        episódio (MP3 + capa.jpg + descricao.txt) são compactados em um único
        ``<nome do áudio>.zip`` — é o zip que sobe para o Drive, não os
        arquivos soltos. Vídeos (MP4) ficam fora do pacote e sobem ao lado:
        zipar um formato já comprimido de centenas de MB não reduz nada.

        Sem ``archiver`` injetado, cai no comportamento anterior (cada arquivo
        da subpasta sobe individualmente).

        AudioFiles sem subfolder (retrocompatibilidade) passam direto.
        Subpastas duplicadas são ignoradas — evita que dois AudioFiles do
        mesmo segmento dupliquem os artefatos.
        """
        log = on_log if callable(on_log) else (lambda *_a, **_kw: None)

        upload_list: List[AudioFile] = []
        seen_subfolders: set = set()

        for af in audio_files:
            if not (af.subfolder and os.path.isdir(af.subfolder)):
                # Retrocompatibilidade: AudioFile sem subfolder
                upload_list.append(af)
                continue

            if af.subfolder in seen_subfolders:
                continue
            seen_subfolders.add(af.subfolder)

            arquivos = [
                os.path.join(af.subfolder, fname)
                for fname in sorted(os.listdir(af.subfolder))
                if os.path.isfile(os.path.join(af.subfolder, fname))
                and os.path.splitext(fname)[1].lower() not in self._EXT_IGNORADAS
            ]

            no_pacote = [
                p for p in arquivos
                if os.path.splitext(p)[1].lower() not in self._EXT_FORA_DO_PACOTE
            ]
            fora_do_pacote = [p for p in arquivos if p not in no_pacote]

            if self.archiver is not None and no_pacote:
                upload_list.append(
                    self._empacotar(af, no_pacote, log=log)
                )
            else:
                no_pacote and log(
                    "[Pacote] Compactador indisponível — enviando arquivos soltos."
                )
                fora_do_pacote = arquivos      # sem zip, tudo sobe individual

            for fpath in fora_do_pacote:
                upload_list.append(AudioFile(
                    path      = fpath,
                    title     = os.path.splitext(os.path.basename(fpath))[0],
                    video_id  = af.video_id,
                    subfolder = af.subfolder,
                ))

        return upload_list

    def _empacotar(
        self,
        af: AudioFile,
        arquivos: List[str],
        *,
        log: Callable[[str], None],
    ) -> AudioFile:
        """
        Compacta ``arquivos`` em ``<nome do áudio>.zip`` dentro da subpasta.

        O nome vem do arquivo de áudio (``af.path``), não do título do
        segmento: é o nome que o usuário vê no episódio e o que o yt-dlp já
        sanitizou para o sistema de arquivos.
        """
        nome_base = os.path.splitext(os.path.basename(af.path))[0]
        zip_path  = os.path.join(af.subfolder, f"{nome_base}.zip")

        self.archiver.create(arquivos, zip_path, on_log=log)

        return AudioFile(
            path      = zip_path,
            title     = nome_base,
            video_id  = af.video_id,
            subfolder = af.subfolder,
        )
