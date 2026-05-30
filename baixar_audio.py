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
import socket
import shutil
from datetime import datetime

# Garante UTF-8 no terminal Windows (evita erros com títulos especiais)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_DEFAULT_CHANNEL_URL    = "https://www.youtube.com/@IPMadalena/streams"
_DEFAULT_DRIVE_FOLDER_ID = "1KfsI5zCDL4HZ2pdAWPFfAD3TugplzBez"
SCOPES                  = ["https://www.googleapis.com/auth/drive"]
GITHUB_REPO             = "rodrigoleao111/youtube-to-drive-ipmadalena"

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

TOKEN_FILE       = os.path.join(BASE_DIR, "credentials", "token.pkl")
DOWNLOAD_DIR     = os.path.join(BASE_DIR, "downloads")
HISTORY_FILE     = os.path.join(BASE_DIR, "historico.json")
LOGS_DIR         = os.path.join(BASE_DIR, "logs")
CONFIG_FILE      = os.path.join(BASE_DIR, "config.json")
VINHETAS_DIR     = os.path.join(BASE_DIR, "assets", "vinhetas")

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


# Re-exportado de domain.exceptions para compatibilidade retroativa.
# Código legado que importa OperacaoCancelada de baixar_audio continuará
# funcionando; a exceção lançada pela camada de infra é a mesma classe.
from domain.exceptions import OperacaoCancelada  # noqa: F401, E402

def _noop(*args, **kwargs):
    pass


# ---------------------------------------------------------------------------
# Configurações persistidas — delegam para JsonConfigRepository
# ---------------------------------------------------------------------------

def config_repo():
    """
    Instancia JsonConfigRepository com os defaults do projeto.

    Público para que `composition_root` possa injetá-lo nos use cases que
    precisam ler/escrever configuração em runtime (ex.: EditAudioUseCase).
    """
    from infrastructure.persistence.json_repositories import JsonConfigRepository
    from domain.entities import AudioEditConfig
    return JsonConfigRepository(
        file_path = CONFIG_FILE,
        defaults  = {
            "channel_url":     _DEFAULT_CHANNEL_URL,
            "drive_folder_id": _DEFAULT_DRIVE_FOLDER_ID,
            "audio_edit":      AudioEditConfig().to_dict(),
            "chapter_name":    "",
            "keep_files":      False,
            "upload_to_drive": True,
            "save_video":      False,
            "video_quality":   "alta",  # "alta" | "baixa"
            "spotify": {
                "show_id":       "",
                "title_prefix":  "",
                "default_tags":  "",
            },
        },
    )


def load_config() -> dict:
    """Retorna o dict de configuração (lê config.json ou usa defaults)."""
    return config_repo().load()


def save_config(channel_url: str = None, drive_folder_id: str = None):
    """Persiste as configurações em config.json (apenas os campos fornecidos)."""
    config_repo().update(channel_url=channel_url, drive_folder_id=drive_folder_id)


# ---------------------------------------------------------------------------
# Helpers de path para vinhetas — convertem entre absolute (runtime) e
# basename (formato persistido no config.json).
#
# Por que separar: o config.json é o ÚNICO arquivo que precisa ser portátil
# entre instalações (mover a pasta do app não pode quebrar a config). Como
# o BASE_DIR é recalculado a cada inicialização, basta gravar só o nome da
# vinheta (`intro.mp3`) e expandir para `{VINHETAS_DIR}/intro.mp3` no load.
# Paths fora de VINHETAS_DIR (caso o usuário ainda não tenha "selecionado")
# são preservados sem modificação.
# ---------------------------------------------------------------------------

def audio_edit_persist_paths(d: dict) -> dict:
    """
    Converte caminhos absolutos dentro de VINHETAS_DIR para apenas o basename.

    Usado no caminho UI → config.json. Paths fora de VINHETAS_DIR (raro —
    só aconteceria se o copy do _select_vinheta foi pulado por algum motivo)
    permanecem absolutos.
    """
    if not d:
        return d
    result = dict(d)
    for key in ("intro_path", "outro_path", "bg_music_path"):
        p = result.get(key)
        if not p:
            continue
        try:
            if os.path.dirname(os.path.abspath(p)) == os.path.abspath(VINHETAS_DIR):
                result[key] = os.path.basename(p)
        except Exception:
            pass
    return result


def audio_edit_resolve_paths(d: dict) -> dict:
    """
    Converte basenames para caminhos absolutos dentro de VINHETAS_DIR.

    Usado no caminho config.json → AudioEditConfig. Paths já absolutos
    (legado de versões antigas) permanecem inalterados.
    """
    if not d:
        return d
    result = dict(d)
    for key in ("intro_path", "outro_path", "bg_music_path"):
        p = result.get(key)
        if not p:
            continue
        if not os.path.isabs(p):
            result[key] = os.path.join(VINHETAS_DIR, p)
    return result


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
    """Remove arquivos residuais (MP3/webm) da pasta downloads/.

    Falhas individuais (arquivo travado por outro processo, permissão negada)
    são logadas como aviso mas não interrompem a limpeza dos demais arquivos.
    """
    log = on_log if callable(on_log) else _noop
    if not os.path.exists(DOWNLOAD_DIR):
        return
    removed = 0
    failed  = []
    for ext in ("*.mp3", "*.webm", "*.m4a", "*.opus"):
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, ext)):
            try:
                os.remove(f)
                removed += 1
            except Exception as e:
                failed.append((os.path.basename(f), str(e)))
    if removed:
        log(f"Limpeza: {removed} arquivo(s) residual(is) removido(s) de downloads/.")
    for name, reason in failed:
        log(f"Aviso: não removeu '{name}' — {reason}")


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


# ---------------------------------------------------------------------------
# Função run() — fluxo completo (CLI; processa todos os vídeos da data inteiros)
# ---------------------------------------------------------------------------

def run(date_str, on_log=None, on_status=None, on_progress=None):
    """
    Executa o fluxo completo sem pausa para seleção (usado pelo CLI).

    Lista todos os vídeos da data, baixa cada um inteiro (sem corte de trecho)
    e faz upload para o Drive. A GUI usa o `ProcessingPresenter` diretamente,
    com seleção manual de vídeos e trechos.

    Delega ao `composition_root`, que constrói o presenter com toda a
    infraestrutura wired.
    """
    from composition_root import build_processing_presenter

    log      = on_log      if callable(on_log)      else _noop
    status   = on_status   if callable(on_status)   else _noop
    progress = on_progress if callable(on_progress) else _noop

    presenter = build_processing_presenter()

    videos = presenter.list_videos(date_str, on_log=log, on_status=status)
    segments = [{"id": v["id"], "title": v["title"]} for v in videos]   # vídeos completos

    presenter.process_segments(
        date_str, segments,
        on_log=log, on_status=status, on_upload_progress=progress,
    )


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
