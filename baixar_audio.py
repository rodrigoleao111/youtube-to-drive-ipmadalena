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

class OperacaoCancelada(Exception):
    pass

def _noop(*args, **kwargs):
    pass

def _make_callbacks(on_log, on_status, on_progress):
    return (
        on_log      if callable(on_log)      else _noop,
        on_status   if callable(on_status)   else _noop,
        on_progress if callable(on_progress) else _noop,
    )


# ---------------------------------------------------------------------------
# Configurações persistidas
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """Retorna o dict de configuração (lê config.json ou usa defaults)."""
    defaults = {
        "channel_url":    _DEFAULT_CHANNEL_URL,
        "drive_folder_id": _DEFAULT_DRIVE_FOLDER_ID,
    }
    if not os.path.exists(CONFIG_FILE):
        return defaults
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # garante que todas as chaves existam
        for k, v in defaults.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return defaults


def save_config(channel_url: str = None, drive_folder_id: str = None):
    """Persiste as configurações em config.json (apenas os campos fornecidos)."""
    cfg = load_config()
    if channel_url is not None:
        cfg["channel_url"] = channel_url.strip()
    if drive_folder_id is not None:
        cfg["drive_folder_id"] = drive_folder_id.strip()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


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
    """Atualiza o yt-dlp para a versão mais recente via pip (silencioso)."""
    log = on_log if callable(on_log) else _noop
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp", "-q"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            # Descobre a versão instalada
            ver = subprocess.run(
                ["yt-dlp", "--version"],
                capture_output=True, text=True, timeout=10,
            )
            v = ver.stdout.strip() if ver.returncode == 0 else "?"
            log(f"yt-dlp atualizado — versão {v}.")
        else:
            log("Aviso: não foi possível atualizar o yt-dlp.")
    except Exception as e:
        log(f"Aviso: erro ao verificar atualização do yt-dlp: {e}")


def load_history():
    """Carrega o histórico de datas já processadas."""
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_history(date_str, video_titles):
    """Registra a data e os vídeos processados no histórico."""
    history = load_history()
    history[date_str] = {
        "processado_em": datetime.now().isoformat(),
        "videos": video_titles,
    }
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


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

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
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
# Google Drive
# ---------------------------------------------------------------------------

def get_drive_service(on_log=None):
    log = on_log if callable(on_log) else _noop
    creds = None

    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "rb") as f:
                creds = pickle.load(f)
        except Exception:
            log("Token corrompido — removendo e reautenticando...")
            try:
                os.remove(TOKEN_FILE)
            except Exception:
                pass
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log("Renovando token de acesso...")
            try:
                creds.refresh(Request())
            except Exception:
                log("Falha ao renovar token — reautenticando...")
                try:
                    os.remove(TOKEN_FILE)
                except Exception:
                    pass
                creds = None

        if not creds or not creds.valid:
            if not os.path.exists(CREDENTIALS_FILE):
                raise FileNotFoundError(
                    f"Credenciais não encontradas:\n{CREDENTIALS_FILE}\n\n"
                    "Siga as instruções em CONFIGURACAO.md."
                )
            log("Abrindo navegador para autenticação...")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(host="127.0.0.1", port=8085)

        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("drive", "v3", credentials=creds)


def check_auth_status():
    """Retorna True se o token do Drive está presente e válido."""
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    except Exception:
        return False
    if not creds:
        return False
    if creds.valid:
        return True
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
            return True
        except Exception:
            return False
    return False


def run_auth(on_log=None):
    """Executa o fluxo OAuth do Drive. Levanta exceção em caso de falha."""
    get_drive_service(on_log=on_log)


def find_or_create_month_folder(service, date, on_log=None):
    log = on_log if callable(on_log) else _noop
    cfg = load_config()
    root_folder_id = cfg["drive_folder_id"]
    mes = MESES_PT[date.month]
    ano = date.year

    results = service.files().list(
        q=(
            f"'{root_folder_id}' in parents "
            "and mimeType='application/vnd.google-apps.folder' "
            "and trashed=false"
        ),
        fields="files(id, name)",
        orderBy="name",
    ).execute()
    folders = results.get("files", [])

    candidates = [
        f"{mes} {ano}", f"{mes}-{ano}", f"{mes}/{ano}",
        f"{ano}-{date.month:02d}", f"{date.month:02d}/{ano}", mes,
    ]
    for folder in folders:
        for c in candidates:
            if c.lower() in folder["name"].lower():
                log(f"Pasta do mês encontrada: {folder['name']}")
                return folder["id"]

    # Nenhuma encontrada — cria automaticamente
    folder_name = f"{mes} {ano}"
    log(f"Criando pasta '{folder_name}' no Drive...")
    meta = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [root_folder_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


class _ProgressFile:
    """
    Wrapper de arquivo para streaming via requests.
    - Verifica cancelamento a cada leitura (~65 KB).
    - Atualiza label de stats a cada 1 MB (feedback visual contínuo).
    - Loga no texto apenas nos marcos 25 %, 50 % e 75 % (evita poluição).
    - Expõe average_rate_mbps() para o log final de conclusão.
    """
    _STATS_EVERY = 1 * 1024 * 1024   # atualiza label a cada 1 MB
    _MILESTONES  = (25, 50, 75)       # % para logar progresso no texto

    def __init__(self, file_path, file_size, on_log, on_progress, on_upload_stats,
                 cancel_event):
        self._f              = open(file_path, "rb")
        self._size           = file_size
        self._sent           = 0
        self._log            = on_log
        self._progress       = on_progress
        self._stats          = on_upload_stats
        self._cancel         = cancel_event
        self._start_time     = time.time()
        self._last_stats     = 0      # bytes na última atualização do label
        self._last_stats_t   = time.time()
        self._next_milestone = 0      # índice em _MILESTONES

    def read(self, n=-1):
        if self._cancel and self._cancel.is_set():
            raise OperacaoCancelada("Upload cancelado pelo usuário.")
        data = self._f.read(n)
        if data:
            self._sent += len(data)
            pct = int(self._sent / self._size * 100)
            self._progress(pct)

            # Atualiza label de stats a cada 1 MB
            if self._sent - self._last_stats >= self._STATS_EVERY:
                mb_done  = self._sent / (1024 * 1024)
                mb_total = self._size / (1024 * 1024)
                now      = time.time()
                elapsed  = now - self._last_stats_t
                chunk_mb = (self._sent - self._last_stats) / (1024 * 1024)
                rate     = chunk_mb / elapsed if elapsed > 0 else 0.0
                self._stats(mb_done, mb_total, rate)
                self._last_stats   = self._sent
                self._last_stats_t = now

            # Loga no texto apenas nos marcos 25 %, 50 %, 75 %
            if self._next_milestone < len(self._MILESTONES):
                threshold = self._MILESTONES[self._next_milestone]
                if pct >= threshold:
                    mb_done  = self._sent / (1024 * 1024)
                    mb_total = self._size / (1024 * 1024)
                    avg_rate = self.average_rate_mbps()
                    self._log(
                        f"Upload: {threshold}% — "
                        f"{mb_done:.1f} / {mb_total:.1f} MB "
                        f"({avg_rate:.2f} MB/s)"
                    )
                    self._next_milestone += 1
        return data

    def average_rate_mbps(self):
        """Taxa média desde o início do upload."""
        elapsed = time.time() - self._start_time
        return (self._sent / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0

    def __len__(self):
        return self._size

    def close(self):
        self._f.close()


def upload_to_drive(service, file_path, folder_id, on_log=None, on_progress=None,
                    on_upload_stats=None, cancel_event=None):
    """
    Faz upload via requests + AuthorizedSession (mais rápido que httplib2).
    Progresso reportado a cada 1 MB; cancelamento responsivo em < 100 ms.
    """
    log          = on_log          if callable(on_log)          else _noop
    progress     = on_progress     if callable(on_progress)     else _noop
    upload_stats = on_upload_stats if callable(on_upload_stats) else _noop

    file_name       = os.path.basename(file_path)
    file_size_bytes = os.path.getsize(file_path)
    file_size_mb    = file_size_bytes / (1024 * 1024)

    # Verifica duplicata
    safe_name = file_name.replace("'", "")
    existing = service.files().list(
        q=f"'{folder_id}' in parents and name='{safe_name}' and trashed=false",
        fields="files(id, webViewLink)"
    ).execute().get("files", [])
    if existing:
        link = existing[0].get("webViewLink", "")
        log("Arquivo já existe no Drive, pulando.")
        log(f"  → {link}")
        progress(100)
        upload_stats(file_size_mb, file_size_mb, 0.0)
        return existing[0]

    log(f"Enviando '{file_name}' ({file_size_mb:.1f} MB)...")
    progress(0)
    upload_stats(0.0, file_size_mb, 0.0)

    # Sessão autenticada via requests (substitui httplib2)
    creds   = service._http.credentials
    session = AuthorizedSession(creds)

    # 1. Inicia upload resumível — obtém URI de destino
    init_resp = session.post(
        "https://www.googleapis.com/upload/drive/v3/files",
        params={"uploadType": "resumable", "fields": "id,name,webViewLink"},
        json={"name": file_name, "parents": [folder_id]},
        headers={
            "X-Upload-Content-Type":   "audio/mpeg",
            "X-Upload-Content-Length": str(file_size_bytes),
        },
    )
    init_resp.raise_for_status()
    upload_uri = init_resp.headers["Location"]

    # 2. Streaming do arquivo com progresso e cancelamento
    pf = _ProgressFile(
        file_path, file_size_bytes,
        on_log=log, on_progress=progress, on_upload_stats=upload_stats,
        cancel_event=cancel_event,
    )
    try:
        upload_resp = session.put(
            upload_uri,
            data=pf,
            headers={"Content-Type": "audio/mpeg"},
        )
        upload_resp.raise_for_status()
        avg_rate = pf.average_rate_mbps()
    finally:
        pf.close()

    progress(100)
    upload_stats(file_size_mb, file_size_mb, avg_rate)
    result = upload_resp.json()
    link   = result.get("webViewLink", "")
    log(f"Upload concluído! {file_size_mb:.1f} MB — taxa média: {avg_rate:.2f} MB/s")
    log(f"  → {link}")
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
    """
    log    = on_log    if callable(on_log)    else _noop
    status = on_status if callable(on_status) else _noop

    date          = datetime.strptime(date_str, "%d/%m/%Y")
    dateafter_str = (date - timedelta(days=1)).strftime("%Y%m%d")
    channel_url   = load_config()["channel_url"]

    cmd = [
        _ytdlp_cmd(),
        "--simulate",
        "--print", "%(id)s|||%(title)s|||%(upload_date)s",
        "--dateafter", dateafter_str,
        "--break-on-reject",
        "--socket-timeout", "30",
        channel_url,
    ]

    status("Buscando vídeos no YouTube...")
    log(f"Canal: {channel_url}")
    log(f"Data: {date_str}")

    process = _start_process(cmd, cancel_event)

    target_date    = date.strftime("%Y%m%d")
    target_date_p1 = (date + timedelta(days=1)).strftime("%Y%m%d")

    videos = []
    for line in process.stdout:
        _check_cancel(cancel_event)
        line = line.rstrip()
        if "|||" not in line:
            continue
        parts = line.split("|||", 2)
        if len(parts) == 3:
            vid_id, title, upload_date = parts
            upload_date = upload_date.strip()
            if upload_date not in (target_date, target_date_p1):
                continue
            videos.append({"id": vid_id, "title": title, "upload_date": upload_date})
            log(f"Encontrado: {title}")

    process.wait()
    _check_cancel(cancel_event)

    if not videos:
        raise RuntimeError(
            f"Nenhum vídeo encontrado para {date_str}.\n"
            "Verifique se houve culto nessa data no canal."
        )

    log(f"{len(videos)} vídeo(s) encontrado(s).")
    return videos


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
# Fase 3: upload para o Drive
# ---------------------------------------------------------------------------

def upload_files(date_str, files, on_log=None, on_status=None, on_progress=None,
                 on_upload_stats=None, cancel_event=None):
    """
    Recebe lista de caminhos de MP3 e faz upload para a pasta do mês no Drive.
    Remove os arquivos locais após o upload.
    """
    log, status, progress = _make_callbacks(on_log, on_status, on_progress)

    date = datetime.strptime(date_str, "%d/%m/%Y")

    _check_cancel(cancel_event)
    status("Conectando ao Google Drive...")
    log("Conectando ao Google Drive...")
    service = get_drive_service(on_log=log)
    log("Conectado.")

    _check_cancel(cancel_event)
    status("Localizando pasta do mês...")
    folder_id = find_or_create_month_folder(service, date, on_log=log)

    total = len(files)
    for i, file_path in enumerate(files, 1):
        _check_cancel(cancel_event)
        status(f"Enviando arquivo {i} de {total}...")
        upload_to_drive(service, file_path, folder_id,
                        on_log=log, on_progress=progress,
                        on_upload_stats=on_upload_stats,
                        cancel_event=cancel_event)
        os.remove(file_path)

    status("Concluído!")
    log(f"✓ {total} arquivo(s) enviado(s) para o Drive.")


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
