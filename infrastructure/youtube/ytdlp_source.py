"""
Adaptadores yt-dlp que implementam IVideoSource e IAudioDownloader.

Ambas as classes são stateless — nenhum estado mutável entre chamadas —
e dependem apenas de domain/ e stdlib (via _utils).

Referência de compatibilidade retroativa:
  - list_videos() em baixar_audio.py delega para YtDlpVideoSource
  - download_selected_sections() em baixar_audio.py delega para YtDlpAudioDownloader
"""

from __future__ import annotations

import glob
import os
import re
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from domain.entities import AudioFile, Segment, Video
from domain.exceptions import VideoNaoEncontrado
from infrastructure.youtube._utils import (
    check_cancel,
    ffmpeg_dir,
    start_process,
    ytdlp_exe,
)


def _noop(*_a, **_kw):
    pass


# ---------------------------------------------------------------------------
# IVideoSource
# ---------------------------------------------------------------------------

class YtDlpVideoSource:
    """
    Lista vídeos de um canal YouTube para uma data específica, usando
    yt-dlp em modo --simulate (sem download).

    Implementa o contrato IVideoSource (duck typing / Protocol).
    """

    def list_videos(
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

        Lança VideoNaoEncontrado se não houver vídeos na data.
        Lança OperacaoCancelada se cancel_event for sinalizado.
        """
        log    = on_log    if callable(on_log)    else _noop
        status = on_status if callable(on_status) else _noop

        date          = datetime.strptime(date_str, "%d/%m/%Y")
        dateafter_str = (date - timedelta(days=1)).strftime("%Y%m%d")

        cmd = [
            ytdlp_exe(),
            "--simulate",
            "--print", "%(id)s|||%(title)s|||%(upload_date)s",
            "--dateafter", dateafter_str,
            "--break-on-reject",
            "--socket-timeout", "30",
            "--encoding", "utf-8",
            channel_url,
        ]

        status("Buscando vídeos no YouTube...")
        log(f"Canal: {channel_url}")
        log(f"Data: {date_str}")

        process = start_process(cmd, cancel_event)

        target_date    = date.strftime("%Y%m%d")
        target_date_p1 = (date + timedelta(days=1)).strftime("%Y%m%d")

        videos: List[Video] = []
        for line in process.stdout:
            check_cancel(cancel_event)
            line = line.rstrip()
            if "|||" not in line:
                continue
            parts = line.split("|||", 2)
            if len(parts) == 3:
                vid_id, title, upload_date = parts
                upload_date = upload_date.strip()
                if upload_date not in (target_date, target_date_p1):
                    continue
                videos.append(Video(id=vid_id, title=title, upload_date=upload_date))
                log(f"Encontrado: {title}")

        process.wait()
        check_cancel(cancel_event)

        if not videos:
            raise VideoNaoEncontrado(
                f"Nenhum vídeo encontrado para {date_str}.\n"
                "Verifique se houve culto nessa data no canal."
            )

        log(f"{len(videos)} vídeo(s) encontrado(s).")
        return videos


# ---------------------------------------------------------------------------
# IAudioDownloader
# ---------------------------------------------------------------------------

_DL_PCT_RE          = re.compile(r'\[download\]\s+(\d+\.?\d*)%')
_EXTRACT_DEST_RE    = re.compile(r"\[ExtractAudio\] Destination:\s*(.+)$")


class YtDlpAudioDownloader:
    """
    Baixa o áudio de segmentos de vídeo usando yt-dlp, aplicando corte
    de trecho quando start/end estiverem presentes no Segment.

    Implementa o contrato IAudioDownloader (duck typing / Protocol).

    Cada AudioFile retornado preserva o video_id do Segment de origem; o
    caminho do arquivo é capturado da linha `[ExtractAudio] Destination:`
    do stdout do yt-dlp (em vez de globar o diretório), evitando que
    arquivos pré-existentes em output_dir contaminem o resultado.
    """

    def download(
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
        Baixa cada segmento como MP3 em output_dir.

        Retorna a lista de AudioFile gerados (um por segmento com sucesso),
        na ordem dos segments de entrada. Cada AudioFile traz o video_id
        original e o caminho real do arquivo conforme reportado pelo yt-dlp.

        Lança RuntimeError se yt-dlp retornar código != 0.
        Lança OperacaoCancelada se cancel_event for sinalizado.
        """
        log         = on_log      if callable(on_log)      else _noop
        status      = on_status   if callable(on_status)   else _noop
        dl_progress = on_progress if callable(on_progress) else _noop

        total    = len(segments)
        ffmpeg   = ffmpeg_dir()
        output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

        os.makedirs(output_dir, exist_ok=True)

        results: List[AudioFile] = []

        for idx, seg in enumerate(segments):
            check_cancel(cancel_event)

            url = f"https://www.youtube.com/watch?v={seg.video_id}"

            status(f"Baixando vídeo {idx + 1} de {total}...")
            log(f"Baixando: {seg.title}")
            if not seg.is_full_video:
                log(f"  Trecho: {seg.start} → {seg.end}")
            else:
                log("  Vídeo completo")

            cmd = [
                ytdlp_exe(),
                "--extract-audio",
                "--audio-format", "mp3",
                "--audio-quality", "0",
                "--output", output_template,
                "--socket-timeout", "30",
                "--encoding", "utf-8",
                "--extractor-args", "youtube:player_client=ios,android,web",
            ]
            if not seg.is_full_video:
                cmd += ["--download-sections", f"*{seg.start}-{seg.end}"]
            if ffmpeg:
                cmd += ["--ffmpeg-location", ffmpeg]
            cmd.append(url)

            process = start_process(cmd, cancel_event)

            extracted_path: Optional[str] = None

            for line in process.stdout:
                check_cancel(cancel_event)
                line = line.rstrip()
                if not line:
                    continue
                if "WARNING" in line and "JavaScript" in line:
                    continue
                if "[youtube]" in line and "Downloading" in line:
                    continue

                if line.startswith("[download]") and "%" in line:
                    m = _DL_PCT_RE.match(line)
                    if m:
                        file_pct = float(m.group(1)) / 100.0
                        dl_progress((idx + file_pct) / total)
                    continue

                if "[download] Destination:" in line:
                    fname = os.path.basename(line.split("Destination:", 1)[-1].strip())
                    log(f"Destino: {fname}")
                elif line.startswith("[ExtractAudio]"):
                    m = _EXTRACT_DEST_RE.match(line)
                    if m:
                        # Captura o caminho real do MP3 gerado por este segmento.
                        extracted_path = m.group(1).strip()
                    dl_progress((idx + 1) / total)
                    status("Convertendo para MP3...")
                    log("Convertendo para MP3...")
                else:
                    log(line)

            process.wait()
            check_cancel(cancel_event)

            if process.returncode != 0:
                raise RuntimeError(
                    f"yt-dlp encerrou com código {process.returncode} "
                    f"ao baixar '{seg.title}'.\n"
                    "Verifique sua conexão e tente novamente."
                )

            if extracted_path and os.path.exists(extracted_path):
                results.append(AudioFile(
                    path     = extracted_path,
                    title    = os.path.splitext(os.path.basename(extracted_path))[0],
                    video_id = seg.video_id,
                ))
            else:
                # Fallback defensivo: yt-dlp terminou OK mas não emitiu
                # `[ExtractAudio] Destination:` reconhecível. Procura o MP3
                # mais recente em output_dir cujo nome contenha o título do
                # segment — evita devolver arquivos arbitrários.
                pattern = os.path.join(output_dir, "*.mp3")
                candidates = [p for p in glob.glob(pattern)
                              if seg.title.lower()[:20] in os.path.basename(p).lower()]
                if candidates:
                    latest = max(candidates, key=os.path.getmtime)
                    results.append(AudioFile(
                        path     = latest,
                        title    = os.path.splitext(os.path.basename(latest))[0],
                        video_id = seg.video_id,
                    ))

        return results
