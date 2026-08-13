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
from urllib.parse import parse_qs, urlparse

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
# Link do YouTube → ID do vídeo
# ---------------------------------------------------------------------------

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_YOUTUBE_HOSTS = {
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
}

# Caminhos que carregam o ID no primeiro segmento após o prefixo:
#   /live/<id>, /shorts/<id>, /embed/<id>, /v/<id>
_PATH_PREFIXES = ("live", "shorts", "embed", "v")


def extract_video_id(url: str) -> Optional[str]:
    """
    Extrai o ID de 11 caracteres de um link do YouTube.

    Aceita as formas usadas pelo YouTube na prática::

        https://www.youtube.com/watch?v=<id>       (com query extra: &t=, &list=)
        https://youtu.be/<id>                      (com ?si=...)
        https://www.youtube.com/live/<id>          (lives — formato dos cultos)
        https://www.youtube.com/shorts/<id>
        https://www.youtube.com/embed/<id>
        <id>                                       (o ID cru, 11 caracteres)

    Retorna ``None`` quando o texto não é um link de vídeo do YouTube
    reconhecível — é assim que a UI valida a entrada antes de disparar
    qualquer thread ou subprocess.
    """
    if not url:
        return None

    raw = url.strip()
    if _VIDEO_ID_RE.match(raw):
        return raw

    # urlparse só identifica hostname quando há esquema
    if "://" not in raw:
        raw = "https://" + raw

    try:
        parsed = urlparse(raw)
    except ValueError:
        return None

    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in _YOUTUBE_HOSTS:
        return None

    def _valid(candidate: str) -> Optional[str]:
        candidate = (candidate or "").strip()
        return candidate if _VIDEO_ID_RE.match(candidate) else None

    parts = [p for p in parsed.path.split("/") if p]

    if host == "youtu.be":
        return _valid(parts[0]) if parts else None

    if parsed.path.rstrip("/") == "/watch":
        return _valid(parse_qs(parsed.query).get("v", [""])[0])

    if len(parts) >= 2 and parts[0].lower() in _PATH_PREFIXES:
        return _valid(parts[1])

    return None


def _normalize_upload_date(value: str) -> str:
    """
    Normaliza o upload_date vindo do yt-dlp.

    O yt-dlp imprime ``NA`` quando o campo não está disponível; nesse caso
    devolvemos string vazia para que o chamador possa aplicar seu fallback.
    """
    value = (value or "").strip()
    return value if len(value) == 8 and value.isdigit() else ""


# ---------------------------------------------------------------------------
# Busca rápida por data — janela de tolerância da data aproximada
# ---------------------------------------------------------------------------

# A busca por data usa duas fases (ver YtDlpVideoSource.list_videos). A fase
# rápida lê a aba do canal em modo --flat-playlist com
# ``youtubetab:approximate_date``: o yt-dlp converte o texto "Streamed X ago"
# em uma data aproximada SEM extrair cada vídeo. A precisão desse texto piora
# com a idade (medido ao vivo em 13/08/2026 no canal @IPMadalena):
#
#   idade ≤ ~1 semana  → erro ≤ 2 dias (inclui o fuso: upload_date é UTC)
#   semanas            → erro ≤ ~7 dias ("2 weeks ago" arredonda para baixo)
#   meses              → erro ≤ ~31 dias
#   anos               → o bucket inteiro colapsa em uma única data
#                        ("11 years ago" → hoje-11a para TODOS os vídeos do ano)
#
# O YouTube sempre arredonda a idade PARA BAIXO, então a data aproximada é
# igual ou POSTERIOR à real — a janela para trás pode ser pequena e fixa,
# e a janela para frente cresce com a idade do vídeo.

# Dias de folga para TRÁS da data alvo (fuso UTC + margem de segurança).
_FLAT_JANELA_PASSADO_DIAS = 3

# Entradas consecutivas mais antigas que a janela antes de encerrar a
# leitura da aba (a lista é decrescente por data; 5 seguidas fora da janela
# significam que já passamos do alvo — mata o subprocess sem enumerar tudo).
_FLAT_PARADA_CONSECUTIVAS = 5

# Máximo de entradas sem data (lives em andamento/agendadas imprimem NA)
# aceitas como candidatas quando a data alvo é ~hoje.
_FLAT_NA_CANDIDATOS_MAX = 5


def _flat_janela_futuro_dias(idade_dias: int) -> int:
    """
    Dias de folga para FRENTE da data alvo, em função da idade do vídeo.

    Acompanha a resolução do "Streamed X ago" do YouTube (ver comentário
    acima). Idades negativas (data alvo no futuro) caem no piso.
    """
    if idade_dias <= 10:
        return 7
    if idade_dias <= 45:
        return 12
    if idade_dias <= 400:
        return 35
    return 400


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

        A busca é feita em duas fases para não pagar uma extração completa
        por vídeo do canal (medido em 13/08/2026: o caminho antigo levava
        ~19 s para a data mais recente — ~15 s enumerando as 1391 entradas
        da aba antes de extrair qualquer vídeo — e crescia ~1,5 s por vídeo
        mais novo que o alvo):

          1. Fase rápida  — lista a aba em --flat-playlist --lazy-playlist
             com datas APROXIMADAS (1 requisição por ~30 entradas, ~0,2 s
             cada) e seleciona os candidatos dentro da janela de tolerância;
             a leitura para assim que as entradas ficam mais antigas que o
             alvo, sem enumerar o canal inteiro.
          2. Confirmação — extração completa SOMENTE dos candidatos, com o
             MESMO filtro exato de sempre (upload_date == alvo ou alvo+1,
             por causa do fuso UTC).

        Se a fase rápida não encontrar nada (datas aproximadas indisponíveis,
        vídeo fora da janela, data sem culto), cai na varredura completa
        original — o resultado final é sempre o mesmo do caminho antigo.

        Lança VideoNaoEncontrado se não houver vídeos na data.
        Lança OperacaoCancelada se cancel_event for sinalizado.
        """
        log    = on_log    if callable(on_log)    else _noop
        status = on_status if callable(on_status) else _noop

        date = datetime.strptime(date_str, "%d/%m/%Y")

        status("Buscando vídeos no YouTube...")
        log(f"Canal: {channel_url}")
        log(f"Data: {date_str}")

        candidatos = self._buscar_candidatos_flat(
            date, channel_url, cancel_event=cancel_event, on_log=log
        )
        if candidatos:
            status(f"Confirmando data de {len(candidatos)} vídeo(s)...")
            videos = self._confirmar_datas(
                candidatos, date, cancel_event=cancel_event, on_log=log
            )
            if videos:
                log(f"{len(videos)} vídeo(s) encontrado(s).")
                return videos

        log("Busca rápida sem resultados — varrendo o canal completo...")
        status("Buscando vídeos no YouTube (varredura completa)...")
        return self._listar_por_varredura(
            date, date_str, channel_url, cancel_event=cancel_event, on_log=log
        )

    # -----------------------------------------------------------------------
    # Fase 1 — candidatos via flat playlist com data aproximada
    # -----------------------------------------------------------------------

    def _buscar_candidatos_flat(
        self,
        date: datetime,
        channel_url: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        hoje: Optional[datetime] = None,
    ) -> List[str]:
        """
        Varre a aba do canal em modo flat (sem extração por vídeo) e devolve
        os IDs cujas datas APROXIMADAS caem na janela de tolerância do alvo.

        ``--lazy-playlist`` faz o yt-dlp imprimir as entradas conforme as
        páginas chegam (medido: 1ª linha em ~1,4 s; sem a flag ele enumera a
        aba inteira antes de imprimir qualquer coisa). Assim dá para encerrar
        o subprocess na hora em que a lista — decrescente por data — passa
        do alvo.

        Entradas sem data (``NA`` = live em andamento/agendada) só entram
        como candidatas quando o alvo é ~hoje: é o único caso em que uma
        live em andamento poderia pertencer à data pesquisada.

        ``hoje`` existe apenas para os testes fixarem o relógio.
        Devolve lista vazia quando nada cai na janela — o chamador decide
        o fallback.
        """
        log  = on_log if callable(on_log) else _noop
        hoje = hoje if hoje is not None else datetime.now()

        idade  = (hoje - date).days
        minimo = (date - timedelta(days=_FLAT_JANELA_PASSADO_DIAS)).strftime("%Y%m%d")
        maximo = (date + timedelta(days=_flat_janela_futuro_dias(idade))).strftime("%Y%m%d")
        aceitar_sem_data = idade <= _FLAT_JANELA_PASSADO_DIAS

        cmd = [
            ytdlp_exe(),
            "--simulate",
            "--flat-playlist",
            "--lazy-playlist",
            "--extractor-args", "youtubetab:approximate_date",
            "--print", "%(id)s|||%(title)s|||%(upload_date)s",
            "--socket-timeout", "30",
            "--encoding", "utf-8",
            channel_url,
        ]

        process = start_process(cmd, cancel_event)

        candidatos: List[str] = []
        sem_data_aceitos    = 0
        antigos_consecutivos = 0
        try:
            for line in process.stdout:
                check_cancel(cancel_event)
                line = line.rstrip()
                if "|||" not in line:
                    continue
                parts = line.split("|||", 2)
                if len(parts) != 3:
                    continue
                vid_id, _title, aprox = parts
                vid_id = vid_id.strip()
                aprox  = _normalize_upload_date(aprox)

                if not aprox:
                    if aceitar_sem_data and sem_data_aceitos < _FLAT_NA_CANDIDATOS_MAX:
                        candidatos.append(vid_id)
                        sem_data_aceitos += 1
                    continue

                # Strings YYYYMMDD comparam corretamente como texto.
                if aprox < minimo:
                    antigos_consecutivos += 1
                    if antigos_consecutivos >= _FLAT_PARADA_CONSECUTIVAS:
                        break
                    continue

                antigos_consecutivos = 0
                if aprox <= maximo and vid_id not in candidatos:
                    candidatos.append(vid_id)
        finally:
            # Encerramento antecipado (break/cancelamento): o subprocess ainda
            # estaria enumerando o resto do canal.
            try:
                process.terminate()
            except Exception:
                pass
            process.wait()

        check_cancel(cancel_event)
        if candidatos:
            log(f"Busca rápida: {len(candidatos)} candidato(s) na janela da data.")
        return candidatos

    # -----------------------------------------------------------------------
    # Fase 2 — confirmação com extração completa apenas dos candidatos
    # -----------------------------------------------------------------------

    def _confirmar_datas(
        self,
        video_ids: List[str],
        date: datetime,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> List[Video]:
        """
        Extrai os metadados completos dos candidatos (um único processo
        yt-dlp com todas as URLs) e aplica o filtro EXATO de data — o mesmo
        da varredura completa: upload_date == alvo ou alvo+1 (fuso UTC).

        ``--ignore-errors`` evita que um candidato indisponível (vídeo
        privado/removido) aborte a confirmação dos demais.
        """
        log = on_log if callable(on_log) else _noop

        target_date    = date.strftime("%Y%m%d")
        target_date_p1 = (date + timedelta(days=1)).strftime("%Y%m%d")

        cmd = [
            ytdlp_exe(),
            "--simulate",
            "--ignore-errors",
            "--print", "%(id)s|||%(title)s|||%(upload_date)s",
            "--socket-timeout", "30",
            "--encoding", "utf-8",
        ] + [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]

        process = start_process(cmd, cancel_event)

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
        return videos

    # -----------------------------------------------------------------------
    # Fallback — varredura completa (caminho original, inalterado)
    # -----------------------------------------------------------------------

    def _listar_por_varredura(
        self,
        date: datetime,
        date_str: str,
        channel_url: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> List[Video]:
        """
        Varredura completa do canal: extração por vídeo com --dateafter +
        --break-on-reject. É o comportamento original de list_videos() —
        lento, porém garantido — usado quando a busca rápida não encontra
        nada (inclusive para confirmar o "nenhum vídeo na data").
        """
        log = on_log if callable(on_log) else _noop

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

    def fetch_video(
        self,
        url: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> Video:
        """
        Resolve um único vídeo a partir do link informado pelo usuário.

        Usa o mesmo ``--print`` de list_videos() para reaproveitar o formato,
        mas com ``--no-playlist`` (links de live costumam trazer ``&list=``)
        e sem nenhum filtro de data — quem escolhe o vídeo é o usuário.

        Implementa o contrato IVideoFetcher (duck typing / Protocol).

        Lança VideoNaoEncontrado se o link for inválido ou o vídeo não puder
        ser resolvido. Lança OperacaoCancelada se cancel_event for sinalizado.
        """
        log    = on_log    if callable(on_log)    else _noop
        status = on_status if callable(on_status) else _noop

        video_id = extract_video_id(url)
        if not video_id:
            raise VideoNaoEncontrado(
                "Link do YouTube inválido.\n"
                "Use um link de vídeo (ex.: https://www.youtube.com/watch?v=...)."
            )

        cmd = [
            ytdlp_exe(),
            "--simulate",
            "--no-playlist",
            "--print", "%(id)s|||%(title)s|||%(upload_date)s",
            "--socket-timeout", "30",
            "--encoding", "utf-8",
            "--extractor-args", "youtube:player_client=ios,android,web",
            f"https://www.youtube.com/watch?v={video_id}",
        ]

        status("Buscando vídeo no YouTube...")
        log(f"Link: {url}")

        process = start_process(cmd, cancel_event)

        video: Optional[Video] = None
        for line in process.stdout:
            check_cancel(cancel_event)
            line = line.rstrip()
            if "|||" not in line:
                continue
            parts = line.split("|||", 2)
            # Só a primeira linha interessa; o loop segue drenando o stdout
            # para não travar o subprocess com o pipe cheio.
            if len(parts) == 3 and video is None:
                vid_id, title, upload_date = parts
                video = Video(
                    id          = vid_id.strip() or video_id,
                    title       = title.strip(),
                    upload_date = _normalize_upload_date(upload_date),
                )

        process.wait()
        check_cancel(cancel_event)

        if video is None or process.returncode != 0:
            raise VideoNaoEncontrado(
                "Não foi possível obter os dados do vídeo.\n"
                "Verifique se o link está correto e se o vídeo está disponível."
            )

        log(f"Encontrado: {video.title}")
        return video

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
    return _truncar_nome(sanitized, 150) if sanitized else "video"


# ---------------------------------------------------------------------------
# Orçamento de tamanho de caminho (MAX_PATH do Windows)
# ---------------------------------------------------------------------------

# Sem `LongPathsEnabled` no registro, a API Win32 rejeita caminhos com 260+
# caracteres. O yt-dlp falha com "Cannot write video description file ..." e
# encerra com código 1 — sem pista de que o problema é o tamanho do caminho.
_MAX_PATH = 260

# Folga para os sufixos que o yt-dlp e o pipeline acrescentam ao nome base:
# ".description" (12), ".mp4.part" (9), ".f251.webm" (10), ".mp3.tmp" (8).
_RESERVA_SUFIXO = 20

# Piso: abaixo disso o nome deixa de identificar o episódio. Se nem isso couber,
# o problema é a pasta de downloads estar fundo demais na árvore.
_MIN_NOME = 24


def _truncar_nome(nome: str, limite: int) -> str:
    """Corta em ``limite`` caracteres sem deixar espaço/ponto no fim."""
    if limite <= 0:
        return ""
    return nome[:limite].rstrip(". ")


def build_output_names(output_dir: str, title: str) -> Tuple[str, str]:
    """
    Devolve ``(nome_da_subpasta, nome_do_arquivo)`` que caibam no MAX_PATH.

    O mesmo nome sanitizado é usado para a subpasta e para os arquivos dentro
    dela, então o caminho final é
    ``output_dir\\<nome>\\<nome><sufixo>`` — o nome entra DUAS vezes na conta.
    Antes o arquivo usava o template ``%(title)s`` do yt-dlp, que ignora esse
    orçamento (e reintroduz caracteres de largura total no lugar de ``|`` e
    ``:``): um culto com título longo estourava os 260 caracteres e o download
    morria antes de começar.

    Quando não há espaço, o nome é truncado (nunca abaixo de ``_MIN_NOME``);
    o chamador loga o ajuste.
    """
    nome = sanitize_folder_name(title)

    # 2 separadores: output_dir\nome\nome
    orcamento = _MAX_PATH - len(output_dir) - 2 - _RESERVA_SUFIXO
    limite = max(_MIN_NOME, orcamento // 2)

    if len(nome) > limite:
        nome = _truncar_nome(nome, limite) or "video"

    return nome, nome


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
            # Nome da pasta E dos arquivos com orçamento de MAX_PATH: o mesmo
            # nome entra duas vezes no caminho final.
            nome_pasta, nome_arquivo = build_output_names(output_dir, seg.title)
            if nome_pasta != sanitize_folder_name(seg.title):
                log(f"  Nome encurtado para caber no limite de "
                    f"{_MAX_PATH} caracteres do Windows: '{nome_arquivo}'")

            subfolder = os.path.join(output_dir, nome_pasta)
            os.makedirs(subfolder, exist_ok=True)

            url = f"https://www.youtube.com/watch?v={seg.video_id}"
            # `%` do título precisa ser escapado: o -o do yt-dlp é um template
            # de formatação e um `%` solto quebraria o parsing.
            output_template = os.path.join(
                subfolder, f"{nome_arquivo.replace('%', '%%')}.%(ext)s"
            )

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
