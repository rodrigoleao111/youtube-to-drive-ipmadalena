#!/usr/bin/env python3
"""
Módulo principal — baixa áudio do canal @IPMadalena e faz upload para o Drive.

Uso via CLI:
    python baixar_audio.py DD/MM/AAAA
    python baixar_audio.py 19/04/2026

Uso via código (GUI):
    from baixar_audio import run
    run("19/04/2026", on_log=..., on_status=..., on_progress=...)
"""

import sys
import os
import re
import subprocess
import glob
import pickle
import threading
import socket
import shutil
import json
import time
from datetime import datetime, timedelta

# Garante UTF-8 no terminal Windows (evita erros com títulos especiais)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request, AuthorizedSession

_DEFAULT_CHANNEL_URL    = "https://www.youtube.com/@IPMadalena/streams"
_DEFAULT_DRIVE_FOLDER_ID = "1KfsI5zCDL4HZ2pdAWPFfAD3TugplzBez"
SCOPES                  = ["https://www.googleapis.com/auth/drive"]

# Credenciais OAuth embutidas — o usuário não precisa distribuir client_secret.json.
# Geradas no Google Cloud Console do projeto ipmadalena-drive.
_OAUTH_CLIENT_CONFIG = {
    "installed": {
        "client_id":     "435847172721-8rsq01h21sjmqpd023hkkb5suct5lsmi.apps.googleusercontent.com",
        "client_secret": "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",
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

# Quando empacotado com PyInstaller, sys.executable aponta para o .exe gerado.
# Dados do usuário (credentials/, downloads/, etc.) ficam sempre ao lado do .exe.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials", "client_secret.json")
TOKEN_FILE       = os.path.join(BASE_DIR, "credentials", "token.pkl")
DOWNLOAD_DIR     = os.path.join(BASE_DIR, "downloads")
HISTORY_FILE     = os.path.join(BASE_DIR, "historico.json")
LOGS_DIR         = os.path.join(BASE_DIR, "logs")
CONFIG_FILE      = os.path.join(BASE_DIR, "config.json")

# ffmpeg: primeiro ao lado do exe/fonte, depois no bundle PyInstaller
_LOCAL_FFMPEG = os.path.join(BASE_DIR, "ffmpeg", "bin", "ffmpeg.exe")
if not os.path.exists(_LOCAL_FFMPEG) and getattr(sys, "frozen", False):
    _LOCAL_FFMPEG = os.path.join(sys._MEIPASS, "ffmpeg", "bin", "ffmpeg.exe")
FFMPEG_LOCATION = _LOCAL_FFMPEG if os.path.exists(_LOCAL_FFMPEG) else None


def _ytdlp_cmd():
    """Retorna o caminho do yt-dlp, suportando bundle PyInstaller e PATH normal."""
    if getattr(sys, "frozen", False):
        bundled = os.path.join(sys._MEIPASS, "yt-dlp.exe")
        if os.path.exists(bundled):
            return bundled
    return "yt-dlp"

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março",    4: "Abril",
    5: "Maio",    6: "Junho",     7: "Julho",     8: "Agosto",
    9: "Setembro",10: "Outubro",  11: "Novembro", 12: "Dezembro",
}


# ---------------------------------------------------------------------------
# Helpers de callback — evitam verificar None em todo lugar
# ---------------------------------------------------------------------------

# Re-exportado de domain.exceptions para compatibilidade retroativa.
# Código legado que importa OperacaoCancelada de baixar_audio continuará
# funcionando; a exceção lançada pela camada de infra é a mesma classe.
from domain.exceptions import OperacaoCancelada  # noqa: F401, E402

def _noop(*args, **kwargs):
    pass

def _make_callbacks(on_log, on_status, on_progress):
    return (
        on_log      if callable(on_log)      else _noop,
        on_status   if callable(on_status)   else _noop,
        on_progress if callable(on_progress) else _noop,
    )


# ---------------------------------------------------------------------------
# Configurações persistidas — delegam para JsonConfigRepository
# ---------------------------------------------------------------------------

def _config_repo():
    """Instancia JsonConfigRepository com os defaults do projeto."""
    from infrastructure.persistence.json_repositories import JsonConfigRepository
    return JsonConfigRepository(
        file_path = CONFIG_FILE,
        defaults  = {
            "channel_url":     _DEFAULT_CHANNEL_URL,
            "drive_folder_id": _DEFAULT_DRIVE_FOLDER_ID,
        },
    )


def load_config() -> dict:
    """Retorna o dict de configuração (lê config.json ou usa defaults)."""
    return _config_repo().load()


def save_config(channel_url: str = None, drive_folder_id: str = None):
    """Persiste as configurações em config.json (apenas os campos fornecidos)."""
    _config_repo().update(channel_url=channel_url, drive_folder_id=drive_folder_id)


def logout_drive():
    """Remove o token salvo, forçando reautorização na próxima execução."""
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)


# ---------------------------------------------------------------------------
# Funções utilitárias de robustez
# ---------------------------------------------------------------------------

def check_internet(timeout=5):
    """Verifica conectividade tentando alcançar o DNS público do Google."""
    try:
        socket.setdefaulttimeout(timeout)
        socket.create_connection(("8.8.8.8", 53))
        return True
    except OSError:
        return False
    finally:
        socket.setdefaulttimeout(None)  # evita herdar timeout em sockets futuros (OAuth, etc.)


def check_disk_space(min_mb=500):
    """
    Verifica espaço livre no diretório de downloads.
    Retorna (ok: bool, free_mb: float).
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    free_mb = shutil.disk_usage(DOWNLOAD_DIR).free / (1024 * 1024)
    return free_mb >= min_mb, free_mb


def cleanup_downloads(on_log=None):
    """Remove arquivos residuais (MP3/webm) da pasta downloads/."""
    log = on_log if callable(on_log) else _noop
    if not os.path.exists(DOWNLOAD_DIR):
        return
    removed = 0
    for ext in ("*.mp3", "*.webm", "*.m4a", "*.opus"):
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, ext)):
            try:
                os.remove(f)
                removed += 1
            except Exception:
                pass
    if removed:
        log(f"Limpeza: {removed} arquivo(s) residual(is) removido(s) de downloads/.")


def update_ytdlp(on_log=None):
    """Atualiza o yt-dlp para a versão mais recente.

    - Frozen (exe instalado): usa o auto-update nativo do yt-dlp standalone (-U).
    - Script normal: atualiza via pip.
    """
    log = on_log if callable(on_log) else _noop

    # No Windows, impede janela de console visível em qualquer subprocess.run
    _no_window = {}
    if sys.platform == "win32":
        _no_window["creationflags"] = subprocess.CREATE_NO_WINDOW

    try:
        if getattr(sys, "frozen", False):
            # Versão empacotada: yt-dlp standalone suporta auto-update com -U
            result = subprocess.run(
                [_ytdlp_cmd(), "-U"],
                capture_output=True, text=True, timeout=60,
                **_no_window,
            )
            if result.returncode == 0:
                output = result.stdout + result.stderr
                m = re.search(r"(\d{4}\.\d{2}\.\d{2})", output)
                v = m.group(1) if m else "?"
                log(f"yt-dlp verificado — versão {v}.")
            else:
                log("Aviso: não foi possível verificar atualização do yt-dlp.")
        else:
            # Versão script: atualiza via pip
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp", "-q"],
                capture_output=True, text=True, timeout=60,
                **_no_window,
            )
            if result.returncode == 0:
                ver = subprocess.run(
                    [_ytdlp_cmd(), "--version"],
                    capture_output=True, text=True, timeout=10,
                    **_no_window,
                )
                v = ver.stdout.strip() if ver.returncode == 0 else "?"
                log(f"yt-dlp atualizado — versão {v}.")
            else:
                log("Aviso: não foi possível atualizar o yt-dlp.")
    except Exception as e:
        log(f"Aviso: erro ao verificar atualização do yt-dlp: {e}")


def _history_repo():
    """Instancia JsonHistoryRepository com o caminho padrão do projeto."""
    from infrastructure.persistence.json_repositories import JsonHistoryRepository
    return JsonHistoryRepository(file_path=HISTORY_FILE)


def load_history():
    """Carrega o histórico de datas já processadas."""
    return _history_repo().load()


def save_history(date_str, video_titles):
    """Registra a data e os vídeos processados no histórico."""
    _history_repo().record(date_str, video_titles)


# ---------------------------------------------------------------------------
# Helper: subprocess com watchdog de cancelamento
# ---------------------------------------------------------------------------

def _start_process(cmd, cancel_event=None):
    """
    Inicia o subprocess e, se cancel_event for fornecido, sobe um watchdog em
    background que termina o processo assim que o evento for sinalizado.
    Retorna o processo.
    """
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # No Windows, impede que o yt-dlp abra uma janela de console visível
    extra = {}
    if sys.platform == "win32":
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        **extra,
    )
    if cancel_event is not None:
        def _watchdog():
            cancel_event.wait()          # bloqueia até o cancelamento
            try:
                process.terminate()
            except Exception:
                pass
        threading.Thread(target=_watchdog, daemon=True).start()

    return process


def _check_cancel(cancel_event):
    """Lança OperacaoCancelada se o evento estiver sinalizado."""
    if cancel_event is not None and cancel_event.is_set():
        raise OperacaoCancelada("Operação cancelada pelo usuário.")


# ---------------------------------------------------------------------------
# Google Drive — funções públicas delegam para GoogleDriveStorage
# ---------------------------------------------------------------------------

def _make_drive_storage(*, delete_after_upload: bool = False):
    """Instancia GoogleDriveStorage com configuração atual do projeto."""
    from infrastructure.drive.gdrive_storage import GoogleDriveStorage
    cfg = load_config()
    return GoogleDriveStorage(
        token_file          = TOKEN_FILE,
        oauth_config        = _OAUTH_CLIENT_CONFIG,
        scopes              = SCOPES,
        root_folder_id      = cfg["drive_folder_id"],
        delete_after_upload = delete_after_upload,
    )


def get_drive_service(on_log=None):
    """Retorna um serviço Drive API autenticado."""
    return _make_drive_storage().get_service(on_log=on_log)


def check_auth_status():
    """Retorna True se o token do Drive está presente e válido."""
    return _make_drive_storage().check_auth()


def run_auth(on_log=None):
    """Executa o fluxo OAuth do Drive. Levanta exceção em caso de falha."""
    _make_drive_storage().get_service(on_log=on_log)


def find_or_create_month_folder(service, date, on_log=None):
    """Localiza ou cria a pasta do mês no Drive. API mantida para compatibilidade."""
    from infrastructure.drive.gdrive_storage import GoogleDriveStorage
    cfg = load_config()
    storage = GoogleDriveStorage(
        token_file     = TOKEN_FILE,
        oauth_config   = _OAUTH_CLIENT_CONFIG,
        scopes         = SCOPES,
        root_folder_id = cfg["drive_folder_id"],
    )
    return storage._find_or_create_month_folder(service, date, on_log=on_log)


def upload_to_drive(service, file_path, folder_id, on_log=None, on_progress=None,
                    on_upload_stats=None, cancel_event=None):
    """
    Faz upload de um único arquivo para o Drive.
    API mantida para compatibilidade; delega para GoogleDriveStorage._upload_single().
    """
    from infrastructure.drive.gdrive_storage import GoogleDriveStorage
    cfg = load_config()
    storage = GoogleDriveStorage(
        token_file     = TOKEN_FILE,
        oauth_config   = _OAUTH_CLIENT_CONFIG,
        scopes         = SCOPES,
        root_folder_id = cfg["drive_folder_id"],
    )
    result, _ = storage._upload_single(
        service, file_path, folder_id,
        on_log          = on_log          if callable(on_log)          else _noop,
        on_progress     = on_progress     if callable(on_progress)     else _noop,
        on_upload_stats = on_upload_stats if callable(on_upload_stats) else _noop,
        cancel_event    = cancel_event,
    )
    return result


# ---------------------------------------------------------------------------
# YouTube — Fase 1: listar vídeos (sem baixar)
# ---------------------------------------------------------------------------

def list_videos(date_str, on_log=None, on_status=None, cancel_event=None):
    """
    Varre o canal com --simulate e retorna a lista de vídeos encontrados
    na data informada, sem fazer nenhum download.

    Retorna lista de dicts:
        {"id": str, "title": str, "upload_date": str}   # upload_date: YYYYMMDD

    Delega para infrastructure.youtube.YtDlpVideoSource; converte os objetos
    Video de domínio de volta para dicts para manter compatibilidade retroativa.
    """
    from infrastructure.youtube.ytdlp_source import YtDlpVideoSource
    from domain.exceptions import VideoNaoEncontrado

    channel_url = load_config()["channel_url"]

    try:
        source = YtDlpVideoSource()
        videos = source.list_videos(
            date_str,
            channel_url,
            cancel_event=cancel_event,
            on_log=on_log,
            on_status=on_status,
        )
    except VideoNaoEncontrado as exc:
        # Converte para RuntimeError para não quebrar chamadores existentes
        raise RuntimeError(str(exc)) from exc

    # Converte Video → dict (contrato público de baixar_audio.py)
    return [{"id": v.id, "title": v.title, "upload_date": v.upload_date} for v in videos]


# ---------------------------------------------------------------------------
# YouTube — Fase 2: baixar vídeos selecionados
# ---------------------------------------------------------------------------

def download_selected(videos, on_log=None, on_status=None,
                      on_download_progress=None, cancel_event=None):
    """
    Recebe a lista de vídeos selecionados pelo usuário (dicts com chave "id")
    e faz o download do áudio de cada um.
    Retorna lista de caminhos dos MP3 baixados.

    on_download_progress(pct: float) — progresso geral 0.0–1.0 através de todos os vídeos.
    """
    log         = on_log               if callable(on_log)               else _noop
    status      = on_status            if callable(on_status)            else _noop
    dl_progress = on_download_progress if callable(on_download_progress) else _noop

    total_videos     = len(videos)
    current_video    = 0   # quantos vídeos já tiveram ExtractAudio concluído

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    output_template = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

    urls = [f"https://www.youtube.com/watch?v={v['id']}" for v in videos]

    cmd = [
        _ytdlp_cmd(),
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--output", output_template,
        "--socket-timeout", "30",
        "--encoding", "utf-8",
        "--extractor-args", "youtube:player_client=ios,android,web",
    ]
    if FFMPEG_LOCATION:
        cmd += ["--ffmpeg-location", os.path.dirname(FFMPEG_LOCATION)]
    cmd.extend(urls)

    status("Baixando áudio...")
    log(f"Baixando {total_videos} vídeo(s)...")

    process = _start_process(cmd, cancel_event)

    _DL_PCT_RE = re.compile(r'\[download\]\s+(\d+\.?\d*)%')

    for line in process.stdout:
        _check_cancel(cancel_event)
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
                overall  = (current_video + file_pct) / total_videos
                dl_progress(overall)
            continue

        if "[download] Destination:" in line:
            fname = line.split("Destination:")[-1].strip().split("\\")[-1]
            log(f"Baixando: {fname}")
        elif "[ExtractAudio]" in line:
            # download deste vídeo concluído — marca 100% da parte proporcional
            dl_progress((current_video + 1) / total_videos)
            current_video += 1
            status("Convertendo para MP3...")
            log("Convertendo para MP3...")
        else:
            log(line)

    process.wait()
    _check_cancel(cancel_event)

    if process.returncode != 0:
        raise RuntimeError(
            f"yt-dlp encerrou com código {process.returncode}.\n"
            "Verifique sua conexão e tente novamente."
        )

    files = glob.glob(os.path.join(DOWNLOAD_DIR, "*.mp3"))
    return sorted(files)


# ---------------------------------------------------------------------------
# YouTube — Fase 2b: baixar vídeos com trecho selecionado
# ---------------------------------------------------------------------------

def download_selected_sections(
    videos_with_sections: list,
    on_log=None,
    on_status=None,
    on_download_progress=None,
    cancel_event=None,
) -> list:
    """
    Baixa o áudio de cada vídeo, aplicando corte de trecho quando start/end fornecidos.

    Cada elemento de videos_with_sections é um dict:
        {"id": str, "title": str, "start": str|None, "end": str|None}
    start/end no formato "HH:MM:SS"; None = vídeo completo.
    Retorna lista de caminhos dos MP3 baixados.

    Delega para infrastructure.youtube.YtDlpAudioDownloader; converte os
    objetos AudioFile de domínio de volta para caminhos (str) para manter
    compatibilidade retroativa.
    """
    from infrastructure.youtube.ytdlp_source import YtDlpAudioDownloader
    from domain.entities import Segment

    # Converte dicts de entrada → Segment (domínio)
    segments = [
        Segment(
            video_id=v["id"],
            title=v["title"],
            start=v.get("start"),
            end=v.get("end"),
        )
        for v in videos_with_sections
    ]

    downloader = YtDlpAudioDownloader()
    audio_files = downloader.download(
        segments,
        DOWNLOAD_DIR,
        cancel_event=cancel_event,
        on_log=on_log,
        on_status=on_status,
        on_progress=on_download_progress,
    )

    # Compatibilidade retroativa: retorna lista de caminhos (str)
    return [af.path for af in audio_files]


# ---------------------------------------------------------------------------
# Fase 3: upload para o Drive
# ---------------------------------------------------------------------------

def upload_files(date_str, files, on_log=None, on_status=None, on_progress=None,
                 on_upload_stats=None, cancel_event=None):
    """
    Recebe lista de caminhos de MP3 e faz upload para a pasta do mês no Drive.
    Remove os arquivos locais após o upload (somente em modo frozen/produção).

    Delega para infrastructure.drive.GoogleDriveStorage.upload(); converte os
    caminhos (str) para AudioFile para compatibilidade com o contrato de domínio.
    """
    from infrastructure.drive.gdrive_storage import GoogleDriveStorage
    from domain.entities import AudioFile

    # Converte caminhos (str) → AudioFile (domínio)
    audio_files = [
        AudioFile(
            path     = p,
            title    = os.path.splitext(os.path.basename(p))[0],
            video_id = "",
        )
        for p in files
    ]

    storage = GoogleDriveStorage(
        token_file          = TOKEN_FILE,
        oauth_config        = _OAUTH_CLIENT_CONFIG,
        scopes              = SCOPES,
        root_folder_id      = load_config()["drive_folder_id"],
        delete_after_upload = getattr(sys, "frozen", False),
    )

    storage.upload(
        audio_files,
        date_str,
        cancel_event    = cancel_event,
        on_log          = on_log,
        on_status       = on_status,
        on_progress     = on_progress,
        on_upload_stats = on_upload_stats,
    )


# ---------------------------------------------------------------------------
# Função run() — fluxo completo (CLI e fallback)
# ---------------------------------------------------------------------------

def run(date_str, on_log=None, on_status=None, on_progress=None):
    """
    Executa o fluxo completo sem pausa para seleção (usado pelo CLI).
    Para o fluxo com seleção manual, a GUI chama list_videos(),
    download_selected() e upload_files() separadamente.
    """
    log, status, progress = _make_callbacks(on_log, on_status, on_progress)

    videos = list_videos(date_str, on_log=log, on_status=status)
    files  = download_selected(videos, on_log=log, on_status=status)

    if not files:
        raise RuntimeError("Nenhum arquivo MP3 gerado após o download.")

    upload_files(date_str, files, on_log=log, on_status=status, on_progress=progress)


# ---------------------------------------------------------------------------
# Entrada CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Uso:     python baixar_audio.py DD/MM/AAAA")
        print("Exemplo: python baixar_audio.py 19/04/2026")
        sys.exit(1)

    date_str = sys.argv[1]

    try:
        datetime.strptime(date_str, "%d/%m/%Y")
    except ValueError:
        print("Data inválida. Use o formato DD/MM/AAAA  (ex: 19/04/2026)")
        sys.exit(1)

    try:
        run(
            date_str,
            on_log=print,
            on_status=lambda s: print(f"[STATUS] {s}"),
            on_progress=lambda p: print(f"[UPLOAD] {p}%", end="\r"),
        )
    except Exception as e:
        print(f"\n[ERRO] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
