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
import json
import os
import re
import subprocess
import sys
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

    def get_chapters(
        self,
        video_id: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> List[dict]:
        """
        Retorna os capítulos do vídeo como lista de dicts com chaves
        ``title``, ``start`` e ``end`` (strings HH:MM:SS).

        Retorna lista vazia se o vídeo não tiver capítulos ou se o
        yt-dlp falhar (best-effort — não lança exceção).

        Implementa o contrato IChapterSource (duck typing / Protocol).
        """
        log = on_log if callable(on_log) else _noop

        url = f"https://www.youtube.com/watch?v={video_id}"
        cmd = [
            ytdlp_exe(),
            "--dump-json",
            "--no-playlist",
            "--socket-timeout", "30",
            "--encoding", "utf-8",
            "--extractor-args", "youtube:player_client=ios,android,web",
            url,
        ]

        log(f"Buscando capítulos do vídeo {video_id}...")

        try:
            process = start_process(cmd, cancel_event)
            output = process.stdout.read()
            process.wait()
            check_cancel(cancel_event)
        except Exception:
            return []

        if process.returncode != 0:
            return []

        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return []

        raw_chapters = data.get("chapters") or []
        if not raw_chapters:
            log("Vídeo sem capítulos definidos.")
            return []

        total_duration = data.get("duration") or 0
        chapters = []
        for i, ch in enumerate(raw_chapters):
            start_sec = ch.get("start_time", 0)
            # end_time nem sempre vem; usa start do próximo ou duração total
            end_sec = ch.get("end_time") or (
                raw_chapters[i + 1]["start_time"]
                if i + 1 < len(raw_chapters)
                else total_duration
            )
            chapters.append({
                "title": ch.get("title", f"Capítulo {i + 1}"),
                "start": _seconds_to_hms(start_sec),
                "end":   _seconds_to_hms(end_sec),
            })

        log(f"{len(chapters)} capítulo(s) encontrado(s).")
        return chapters


def fetch_video_metadata(video_id: str, cancel_event=None) -> dict:
    """
    Retorna um dict com 'description' e 'thumbnail_url' do vídeo.

    Usa yt-dlp -j (dump JSON completo). Como start_process redireciona
    stderr→stdout, warnings do yt-dlp podem aparecer antes do JSON — por
    isso percorremos linha a linha procurando a que começa com '{' (o JSON
    compacto do yt-dlp é sempre uma única linha).

    Retorna {'description': '', 'thumbnail_url': ''} em qualquer falha.
    """
    import json as _json
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        ytdlp_exe(),
        "-j",
        "--skip-download",
        "--no-playlist",
        "--socket-timeout", "30",
        "--encoding", "utf-8",
        "--extractor-args", "youtube:player_client=ios,android,web",
        url,
    ]
    try:
        process = start_process(cmd, cancel_event)
        output = process.stdout.read()
        process.wait()
        check_cancel(cancel_event)
        if process.returncode == 0:
            # Percorre as linhas à procura do objeto JSON (ignora warnings/infos)
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        info = _json.loads(line)
                        return {
                            "description":   (info.get("description") or "").strip(),
                            "thumbnail_url": info.get("thumbnail") or "",
                        }
                    except _json.JSONDecodeError:
                        continue
    except Exception:
        pass
    return {"description": "", "thumbnail_url": ""}


def fetch_video_description(video_id: str, cancel_event=None) -> str:
    """Compat wrapper — prefer fetch_video_metadata."""
    return fetch_video_metadata(video_id, cancel_event).get("description", "")


def _seconds_to_hms(seconds: float) -> str:
    """Converte segundos (float) para string 'HH:MM:SS'."""
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ---------------------------------------------------------------------------
# Helpers de nome de pasta e IAudioDownloader
# ---------------------------------------------------------------------------

_DL_PCT_RE      = re.compile(r'\[download\]\s+(\d+\.?\d*)%')
_MERGER_DEST_RE = re.compile(r'\[Merger\] Merging formats into "(.+)"$')
_MP4_DEST_RE    = re.compile(r'\[download\] Destination:\s*(.+\.mp4)$', re.IGNORECASE)


def sanitize_folder_name(title: str) -> str:
    """
    Sanitiza um título para uso como nome de pasta no Windows/Linux.

    Remove caracteres proibidos no Windows (\\/:*?"<>|), colapsa espaços
    múltiplos, remove pontos e espaços no final (proibidos no Windows) e
    trunca a 150 caracteres para evitar paths excessivamente longos.
    """
    sanitized = re.sub(r'[\\/:*?"<>|]', '', title)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip().rstrip('. ')
    return sanitized[:150] if sanitized else "video"


class YtDlpAudioDownloader:
    """
    Baixa segmentos de vídeo usando yt-dlp (MP4) e converte para MP3 via
    ffmpeg, organizando cada segmento em sua própria subpasta dentro de
    output_dir.

    Fluxo por segmento:
      1. Cria subpasta  output_dir/{título sanitizado}/
      2. Baixa MP4 (trecho) via yt-dlp            → subpasta
      3. Salva thumbnail (CDN YouTube) → capa.jpg  → subpasta  (best-effort)
      4. Salva descrição via metadata_fetcher      → descricao.txt (best-effort)
      5. Converte MP4 → MP3 via ffmpeg             → subpasta
      6. Se save_video=False: remove o MP4

    Implementa o contrato IAudioDownloader (duck typing / Protocol).
    O AudioFile retornado aponta para o MP3 e carrega o campo `subfolder`
    com o caminho da subpasta — usado pelo presenter para montar a lista
    de upload com todos os artefatos.
    """

    def __init__(
        self,
        *,
        save_video: bool = False,
        video_quality: str = "alta",
        metadata_fetcher: Optional[Callable[[str], dict]] = None,
    ):
        """
        Parameters
        ----------
        save_video:
            Se True, o MP4 é mantido na subpasta após a conversão para MP3.
            Se False (default), o MP4 é apagado após a conversão.
        video_quality:
            ``"alta"`` (default) → melhor qualidade disponível (bestvideo).
            ``"baixa"`` → menor qualidade disponível (worstvideo).
            Usado apenas quando ``save_video=True``; não afeta o MP3 final.
        metadata_fetcher:
            Callable opcional com assinatura ``(video_id: str) -> dict``.
            O dict deve ter as chaves ``'description'`` (str) e
            ``'thumbnail_url'`` (str). Usado para salvar ``descricao.txt``
            na subpasta. Composition root injeta ``fetch_video_metadata``.
        """
        self._save_video       = save_video
        self._video_quality    = video_quality
        self._metadata_fetcher = metadata_fetcher

    # -----------------------------------------------------------------------
    # IAudioDownloader.download()
    # -----------------------------------------------------------------------

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
        Para cada segmento: cria subpasta → baixa MP4 → salva extras →
        converte MP3 → (opcionalmente remove MP4).

        Retorna List[AudioFile] com o MP3 de cada segmento e o campo
        ``subfolder`` preenchido.

        Lança RuntimeError se yt-dlp ou ffmpeg retornarem código != 0.
        Lança OperacaoCancelada se cancel_event for sinalizado.
        """
        log         = on_log      if callable(on_log)      else _noop
        status      = on_status   if callable(on_status)   else _noop
        dl_progress = on_progress if callable(on_progress) else _noop

        total  = len(segments)
        ffdir  = ffmpeg_dir()

        os.makedirs(output_dir, exist_ok=True)

        results: List[AudioFile] = []

        for idx, seg in enumerate(segments):
            check_cancel(cancel_event)

            # ── 1. Subpasta por segmento ────────────────────────────────────
            safe_title = sanitize_folder_name(seg.title)
            subfolder  = os.path.join(output_dir, safe_title)
            os.makedirs(subfolder, exist_ok=True)

            url             = f"https://www.youtube.com/watch?v={seg.video_id}"
            output_template = os.path.join(subfolder, "%(title)s.%(ext)s")

            status(f"Baixando vídeo {idx + 1} de {total}...")
            log(f"Baixando: {seg.title}")
            if not seg.is_full_video:
                log(f"  Trecho: {seg.start} → {seg.end}")
            else:
                log("  Vídeo completo")

            # ── 2. Download do MP4 ──────────────────────────────────────────
            if self._video_quality == "baixa":
                _fmt = "worstvideo[ext=mp4]+worstaudio[ext=m4a]/worst[ext=mp4]/worst"
            else:   # "alta" (default)
                _fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

            cmd = [
                ytdlp_exe(),
                "-f", _fmt,
                "--merge-output-format", "mp4",
                "--output", output_template,
                "--socket-timeout", "30",
                "--encoding", "utf-8",
                "--extractor-args", "youtube:player_client=ios,android,web",
                # Salva descrição durante o download (mesmo processo, sem req extra)
                "--write-description",
                "--no-write-playlist-metafiles",
            ]
            if not seg.is_full_video:
                cmd += ["--download-sections", f"*{seg.start}-{seg.end}"]
            if ffdir:
                cmd += ["--ffmpeg-location", ffdir]
            cmd.append(url)

            process = start_process(cmd, cancel_event)

            mp4_path:       Optional[str] = None
            last_mp4_dest:  Optional[str] = None

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
                        # Ocupa 80 % do slot deste segmento (20 % restantes = conversão)
                        dl_progress((idx + file_pct * 0.8) / total)
                    continue

                m = _MERGER_DEST_RE.match(line)
                if m:
                    mp4_path = m.group(1).strip()
                    log(f"MP4: {os.path.basename(mp4_path)}")
                    continue

                m = _MP4_DEST_RE.match(line)
                if m:
                    last_mp4_dest = m.group(1).strip()

                if "[download] Destination:" in line:
                    fname = os.path.basename(line.split("Destination:", 1)[-1].strip())
                    log(f"Destino: {fname}")
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

            # Resolve path do MP4: Merger > última linha Destination: *.mp4 > glob
            if not (mp4_path and os.path.exists(mp4_path)):
                if last_mp4_dest and os.path.exists(last_mp4_dest):
                    mp4_path = last_mp4_dest
                else:
                    candidates = glob.glob(os.path.join(subfolder, "*.mp4"))
                    if candidates:
                        mp4_path = max(candidates, key=os.path.getmtime)
                    else:
                        raise RuntimeError(
                            f"Nenhum MP4 encontrado após download de '{seg.title}'."
                        )

            # ── 3. Renomeia .description → descricao.txt (gerado pelo yt-dlp) ──
            # O --write-description cria <título>.description na mesma subpasta.
            # Renomear aqui evita uma segunda chamada ao yt-dlp para buscar a
            # descrição — o mesmo processo que baixou o vídeo já trouxe os metadados.
            _desc_files = glob.glob(os.path.join(subfolder, "*.description"))
            if _desc_files:
                try:
                    os.replace(_desc_files[0], os.path.join(subfolder, "descricao.txt"))
                    log("Descrição salva.")
                except OSError:
                    pass

            # ── 4. Thumbnail + descrição (best-effort) ───────────────────────
            # _save_extras cuida da capa.jpg via CDN do YouTube e, se
            # descricao.txt ainda não existir (fallback), usa metadata_fetcher.
            status("Salvando metadados...")
            self._save_extras(seg.video_id, subfolder, on_log=log)

            # ── 5. Conversão MP4 → MP3 ──────────────────────────────────────
            mp3_path = os.path.splitext(mp4_path)[0] + ".mp3"
            status("Convertendo para MP3...")
            dl_progress((idx + 0.9) / total)
            self._convert_to_mp3(mp4_path, mp3_path, ffdir=ffdir, on_log=log)
            dl_progress((idx + 1.0) / total)

            # ── 6. Remove MP4 se save_video=False ───────────────────────────
            if not self._save_video:
                try:
                    os.remove(mp4_path)
                except OSError:
                    pass

            results.append(AudioFile(
                path      = mp3_path,
                title     = os.path.splitext(os.path.basename(mp3_path))[0],
                video_id  = seg.video_id,
                subfolder = subfolder,
            ))

        return results

    # -----------------------------------------------------------------------
    # Helpers privados
    # -----------------------------------------------------------------------

    def _save_extras(
        self,
        video_id: str,
        subfolder: str,
        *,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Salva thumbnail (capa.jpg) e descrição (descricao.txt) na subpasta.
        Todas as operações são best-effort — falhas são silenciadas.
        """
        log = on_log if callable(on_log) else _noop

        # Thumbnail via CDN do YouTube (sem depender do yt-dlp)
        try:
            import ssl
            import urllib.request

            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode    = ssl.CERT_NONE

            qualities = ["maxresdefault", "hqdefault", "mqdefault", "sddefault", "default"]
            for q in qualities:
                url = f"https://img.youtube.com/vi/{video_id}/{q}.jpg"
                try:
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
                        data = r.read()
                    if len(data) > 500:   # descarta placeholder de 404 (< 500 bytes)
                        jpg_path = os.path.join(subfolder, "capa.jpg")
                        with open(jpg_path, "wb") as fh:
                            fh.write(data)
                        log("Capa salva.")
                        break
                except Exception:
                    continue
        except Exception:
            pass

        # Descrição via metadata_fetcher — fallback caso --write-description
        # não tenha criado o arquivo (rede lenta, versão antiga de yt-dlp, etc.)
        txt_path = os.path.join(subfolder, "descricao.txt")
        if self._metadata_fetcher and not os.path.isfile(txt_path):
            try:
                meta = self._metadata_fetcher(video_id)
                desc = (meta.get("description") or "").strip()
                if desc:
                    with open(txt_path, "w", encoding="utf-8") as fh:
                        fh.write(desc)
                    log("Descrição salva (fallback).")
            except Exception:
                pass

    def _convert_to_mp3(
        self,
        mp4_path: str,
        mp3_path: str,
        *,
        ffdir: Optional[str] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> None:
        """
        Converte mp4_path → mp3_path usando ffmpeg.

        Usa subprocess.run (sem stream de progresso — operação curta).
        Lança RuntimeError se ffmpeg retornar código != 0.
        """
        log = on_log if callable(on_log) else _noop

        if ffdir:
            ffmpeg_bin = os.path.join(ffdir, "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
            if not os.path.exists(ffmpeg_bin):
                ffmpeg_bin = os.path.join(ffdir, "ffmpeg")
        else:
            ffmpeg_bin = "ffmpeg"

        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", mp4_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "0",
            "-f", "mp3",
            mp3_path,
        ]

        extra: dict = {}
        if sys.platform == "win32":
            extra["creationflags"] = subprocess.CREATE_NO_WINDOW

        log(f"Convertendo '{os.path.basename(mp4_path)}' para MP3...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            **extra,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg falhou ao converter '{os.path.basename(mp4_path)}' para MP3.\n"
                f"Últimas linhas do stderr:\n{result.stderr[-500:]}"
            )
        log("Conversão para MP3 concluída.")
