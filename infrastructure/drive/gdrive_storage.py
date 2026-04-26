"""
Adaptador Google Drive que implementa ICloudStorage.

Responsabilidades:
  - Autenticação OAuth2 (token pickle, refresh, reauth)
  - Localização / criação de pasta do mês no Drive
  - Upload de arquivos MP3 via sessão HTTP autenticada (resumable upload)
  - Progresso byte-a-byte e cancelamento responsivo
  - Verificação de duplicatas antes de enviar

Nenhuma lógica de negócio aqui — apenas I/O de rede e disco.
"""

from __future__ import annotations

import os
import pickle
import sys
import time
from datetime import datetime
from typing import Callable, List, Optional

from googleapiclient.discovery import build
from google.auth.transport.requests import AuthorizedSession, Request
from google_auth_oauthlib.flow import InstalledAppFlow

from domain.entities import AudioFile, ProcessingResult
from domain.exceptions import OperacaoCancelada


def _noop(*_a, **_kw):
    pass


_MESES_PT = {
    1: "Janeiro",  2: "Fevereiro", 3: "Março",    4: "Abril",
    5: "Maio",     6: "Junho",     7: "Julho",     8: "Agosto",
    9: "Setembro", 10: "Outubro",  11: "Novembro", 12: "Dezembro",
}


# ---------------------------------------------------------------------------
# _ProgressFile — wrapper de streaming com progresso e cancelamento
# ---------------------------------------------------------------------------

class _ProgressFile:
    """
    Wrapper de arquivo para streaming via requests.

    - Verifica cancelamento a cada leitura (~65 KB) → resposta < 100 ms
    - Atualiza label de stats a cada 1 MB (taxa instantânea do último chunk)
    - Loga no texto apenas nos marcos 25 %, 50 % e 75 % (evita poluição)
    - Expõe average_rate_mbps() para o log final de conclusão
    """

    _STATS_EVERY = 1 * 1024 * 1024   # atualiza label a cada 1 MB
    _MILESTONES  = (25, 50, 75)

    def __init__(
        self,
        file_path: str,
        file_size: int,
        on_log: Callable,
        on_progress: Callable,
        on_upload_stats: Callable,
        cancel_event,
    ):
        self._f              = open(file_path, "rb")
        self._size           = file_size
        self._sent           = 0
        self._log            = on_log
        self._progress       = on_progress
        self._stats          = on_upload_stats
        self._cancel         = cancel_event
        self._start_time     = time.time()
        self._last_stats     = 0
        self._last_stats_t   = time.time()
        self._next_milestone = 0

    def read(self, n: int = -1) -> bytes:
        if self._cancel and self._cancel.is_set():
            raise OperacaoCancelada("Upload cancelado pelo usuário.")
        data = self._f.read(n)
        if data:
            self._sent += len(data)
            # Guarda contra divisão por zero em arquivos vazios (file_size == 0).
            # yt-dlp normalmente não gera MP3 vazio, mas falha do ffmpeg pode produzir.
            pct = int(self._sent / self._size * 100) if self._size else 100
            self._progress(pct)

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

    def average_rate_mbps(self) -> float:
        elapsed = time.time() - self._start_time
        return (self._sent / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0

    def __len__(self) -> int:
        return self._size

    def close(self) -> None:
        self._f.close()


# ---------------------------------------------------------------------------
# GoogleDriveStorage
# ---------------------------------------------------------------------------

class GoogleDriveStorage:
    """
    Adaptador de armazenamento Google Drive.

    Implementa o contrato ICloudStorage (duck typing / Protocol).

    Parameters
    ----------
    token_file:
        Caminho do arquivo token.pkl onde o token OAuth é persistido.
    oauth_config:
        Dict com credenciais do cliente OAuth (formato InstalledApp).
    scopes:
        Lista de escopos OAuth a solicitar.
    root_folder_id:
        ID da pasta raiz no Drive onde as subpastas de mês são criadas.
    delete_after_upload:
        Se True, remove os arquivos locais após upload bem-sucedido.
        Deve ser True em produção (exe instalado) e False em dev.
    """

    def __init__(
        self,
        token_file: str,
        oauth_config: dict,
        scopes: List[str],
        root_folder_id: str,
        *,
        delete_after_upload: bool = False,
    ):
        self._token_file          = token_file
        self._oauth_config        = oauth_config
        self._scopes              = scopes
        self._root_folder_id      = root_folder_id
        self._delete_after_upload = delete_after_upload

    # -------------------------------------------------------------------
    # Autenticação
    # -------------------------------------------------------------------

    def get_service(self, on_log: Optional[Callable] = None):
        """
        Retorna um serviço Drive API autenticado.

        Tenta usar o token salvo; faz refresh se expirado; abre browser se
        necessário. Salva o token atualizado em self._token_file.
        """
        log = on_log if callable(on_log) else _noop
        creds = None

        if os.path.exists(self._token_file):
            try:
                with open(self._token_file, "rb") as f:
                    creds = pickle.load(f)
            except Exception:
                log("Token corrompido — removendo e reautenticando...")
                try:
                    os.remove(self._token_file)
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
                        os.remove(self._token_file)
                    except Exception:
                        pass
                    creds = None

            if not creds or not creds.valid:
                log("Abrindo navegador para autenticação...")
                flow = InstalledAppFlow.from_client_config(
                    self._oauth_config, self._scopes
                )
                creds = flow.run_local_server(host="127.0.0.1", port=8085)

            with open(self._token_file, "wb") as f:
                pickle.dump(creds, f)

        return build("drive", "v3", credentials=creds)

    def check_auth(self) -> bool:
        """Retorna True se o token existe e está válido (ou pode ser renovado)."""
        if not os.path.exists(self._token_file):
            return False
        try:
            with open(self._token_file, "rb") as f:
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
                with open(self._token_file, "wb") as f:
                    pickle.dump(creds, f)
                return True
            except Exception:
                return False
        return False

    def logout(self) -> None:
        """Remove o token salvo; exige nova autorização na próxima operação."""
        try:
            os.remove(self._token_file)
        except FileNotFoundError:
            pass

    # -------------------------------------------------------------------
    # Pasta do mês
    # -------------------------------------------------------------------

    def _find_or_create_month_folder(
        self,
        service,
        date: datetime,
        on_log: Optional[Callable] = None,
    ) -> str:
        """
        Localiza a pasta do mês no Drive por nome fuzzy.
        Cria automaticamente se não encontrar.
        Retorna o ID da pasta.
        """
        log = on_log if callable(on_log) else _noop
        mes = _MESES_PT[date.month]
        ano = date.year

        results = service.files().list(
            q=(
                f"'{self._root_folder_id}' in parents "
                "and mimeType='application/vnd.google-apps.folder' "
                "and trashed=false"
            ),
            fields="files(id, name)",
            orderBy="name",
        ).execute()
        folders = results.get("files", [])

        # Candidatos para match fuzzy. Cada candidato inclui o ano para evitar
        # colisão entre meses iguais de anos diferentes (ex.: pasta "Maio Festival
        # 2025" não deve casar com busca por Maio/2026). O candidato bare `mes`
        # foi removido por ser muito permissivo.
        candidates = [
            f"{mes} {ano}", f"{mes}-{ano}", f"{mes}/{ano}",
            f"{ano}-{date.month:02d}", f"{date.month:02d}/{ano}",
        ]
        for folder in folders:
            for c in candidates:
                if c.lower() in folder["name"].lower():
                    log(f"Pasta do mês encontrada: {folder['name']}")
                    return folder["id"]

        # Não encontrada — cria automaticamente
        folder_name = f"{mes} {ano}"
        log(f"Criando pasta '{folder_name}' no Drive...")
        meta = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [self._root_folder_id],
        }
        folder = service.files().create(body=meta, fields="id").execute()
        return folder["id"]

    # -------------------------------------------------------------------
    # Upload de arquivo individual
    # -------------------------------------------------------------------

    def _upload_single(
        self,
        service,
        file_path: str,
        folder_id: str,
        *,
        on_log: Callable = _noop,
        on_progress: Callable = _noop,
        on_upload_stats: Callable = _noop,
        cancel_event=None,
    ) -> tuple[dict, bool]:
        """
        Faz upload de um único arquivo MP3 via resumable upload.

        Verifica duplicatas antes de enviar.
        Retorna (metadados_drive, was_skipped).
          was_skipped=True quando o arquivo já existia no Drive.
        """
        file_name       = os.path.basename(file_path)
        file_size_bytes = os.path.getsize(file_path)
        file_size_mb    = file_size_bytes / (1024 * 1024)

        # Verifica duplicata.
        # Escape segundo Drive Query Language: '\' vira '\\' e "'" vira "\'".
        # Trocar apóstrofos por '' (vazio) causaria falso negativo (a query não bateria
        # com o arquivo real) e o arquivo seria re-enviado.
        safe_name = file_name.replace("\\", "\\\\").replace("'", "\\'")
        existing  = service.files().list(
            q=f"'{folder_id}' in parents and name='{safe_name}' and trashed=false",
            fields="files(id, webViewLink)",
        ).execute().get("files", [])
        if existing:
            link = existing[0].get("webViewLink", "")
            on_log("Arquivo já existe no Drive, pulando.")
            on_log(f"  → {link}")
            on_progress(100)
            on_upload_stats(file_size_mb, file_size_mb, 0.0)
            return existing[0], True   # was_skipped=True

        if cancel_event and cancel_event.is_set():
            raise OperacaoCancelada("Upload cancelado pelo usuário.")

        on_log(f"Enviando '{file_name}' ({file_size_mb:.1f} MB)...")
        on_progress(0)
        on_upload_stats(0.0, file_size_mb, 0.0)

        creds   = service._http.credentials
        session = AuthorizedSession(creds)

        # Inicia upload resumível — obtém URI de destino
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

        # Streaming com progresso e cancelamento
        pf = _ProgressFile(
            file_path, file_size_bytes,
            on_log=on_log, on_progress=on_progress, on_upload_stats=on_upload_stats,
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

        on_progress(100)
        on_upload_stats(file_size_mb, file_size_mb, avg_rate)
        result = upload_resp.json()
        link   = result.get("webViewLink", "")
        on_log(
            f"Upload concluído! {file_size_mb:.1f} MB — "
            f"taxa média: {avg_rate:.2f} MB/s"
        )
        on_log(f"  → {link}")
        return result, False   # was_skipped=False

    # -------------------------------------------------------------------
    # ICloudStorage.upload()
    # -------------------------------------------------------------------

    def upload(
        self,
        files: List[AudioFile],
        date_str: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable] = None,
        on_status: Optional[Callable] = None,
        on_progress: Optional[Callable] = None,
        on_upload_stats: Optional[Callable] = None,
    ) -> ProcessingResult:
        """
        Envia todos os arquivos para a pasta do mês no Drive.

        - Verifica duplicatas antes de enviar (pulados são contados separadamente)
        - Remove arquivos locais após upload se delete_after_upload=True
        - Retorna ProcessingResult com listas de enviados e pulados

        Lança OperacaoCancelada se cancel_event for sinalizado.
        """
        log          = on_log          if callable(on_log)          else _noop
        status       = on_status       if callable(on_status)       else _noop
        progress     = on_progress     if callable(on_progress)     else _noop
        upload_stats = on_upload_stats if callable(on_upload_stats) else _noop

        date = datetime.strptime(date_str, "%d/%m/%Y")

        if cancel_event and cancel_event.is_set():
            raise OperacaoCancelada("Operação cancelada.")

        status("Conectando ao Google Drive...")
        log("Conectando ao Google Drive...")
        service = self.get_service(on_log=log)
        log("Conectado.")

        if cancel_event and cancel_event.is_set():
            raise OperacaoCancelada("Operação cancelada.")

        status("Localizando pasta do mês...")
        folder_id = self._find_or_create_month_folder(service, date, on_log=log)

        total    = len(files)
        uploaded = []
        skipped  = []

        for i, audio_file in enumerate(files, 1):
            if cancel_event and cancel_event.is_set():
                raise OperacaoCancelada("Operação cancelada.")

            status(f"Enviando arquivo {i} de {total}...")
            _result, was_skipped = self._upload_single(
                service,
                audio_file.path,
                folder_id,
                on_log=log,
                on_progress=progress,
                on_upload_stats=upload_stats,
                cancel_event=cancel_event,
            )

            if was_skipped:
                skipped.append(audio_file.title)
            else:
                uploaded.append(audio_file.title)

            if self._delete_after_upload:
                try:
                    os.remove(audio_file.path)
                except Exception:
                    pass
            else:
                log(f"[DEBUG] Arquivo mantido em: {audio_file.path}")

        status("Concluído!")
        log(f"✓ {total} arquivo(s) enviado(s) para o Drive.")

        return ProcessingResult(
            date_str=date_str,
            uploaded_files=tuple(uploaded),
            skipped_files=tuple(skipped),
        )
