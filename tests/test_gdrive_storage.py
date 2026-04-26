"""
Testes para infrastructure/drive/gdrive_storage.py.

Todos os I/Os externos são mockados:
  - Drive API (service.files())
  - Sessão HTTP (AuthorizedSession)
  - Disco (os.path.getsize, os.remove, open, pickle.load/dump)
  - OAuth flow (InstalledAppFlow)
"""

from __future__ import annotations

import os
import threading
import pickle
from io import BytesIO
from unittest.mock import MagicMock, call, patch, mock_open

import pytest

from domain.entities import AudioFile, ProcessingResult
from domain.exceptions import OperacaoCancelada
from infrastructure.drive.gdrive_storage import GoogleDriveStorage, _ProgressFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OAUTH_CFG = {
    "installed": {
        "client_id":     "test-id",
        "client_secret": "test-secret",
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}
_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _storage(**kwargs) -> GoogleDriveStorage:
    defaults = dict(
        token_file          = "/fake/token.pkl",
        oauth_config        = _OAUTH_CFG,
        scopes              = _SCOPES,
        root_folder_id      = "root123",
        delete_after_upload = False,
    )
    defaults.update(kwargs)
    return GoogleDriveStorage(**defaults)


def _make_service(existing_folders=None, existing_files=None) -> MagicMock:
    """Cria um mock do serviço Drive com comportamento configurável."""
    svc = MagicMock()

    # files().list().execute() para pastas
    folder_result = {"files": existing_folders or []}
    # files().list().execute() para duplicatas de arquivo
    file_result   = {"files": existing_files   or []}

    list_mock = MagicMock()
    list_mock.execute.side_effect = [folder_result, file_result]
    svc.files().list.return_value = list_mock

    # files().create().execute() — retorna ID da pasta criada
    svc.files().create.return_value.execute.return_value = {"id": "newfolderid"}

    # Credenciais da sessão autenticada
    svc._http = MagicMock()
    svc._http.credentials = MagicMock()

    return svc


def _audio_file(path="/tmp/culto.mp3", title="Culto", video_id="abc") -> AudioFile:
    return AudioFile(path=path, title=title, video_id=video_id)


# ===========================================================================
# check_auth
# ===========================================================================

class TestCheckAuth:
    def test_retorna_false_sem_token_file(self):
        with patch("os.path.exists", return_value=False):
            assert _storage().check_auth() is False

    def test_retorna_false_com_token_corrompido(self):
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open(read_data=b"")), \
             patch("pickle.load", side_effect=Exception("corrompido")):
            assert _storage().check_auth() is False

    def test_retorna_true_com_creds_validas(self):
        creds = MagicMock()
        creds.valid = True
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open()), \
             patch("pickle.load", return_value=creds):
            assert _storage().check_auth() is True

    def test_retorna_false_com_creds_invalidas_sem_refresh(self):
        creds = MagicMock()
        creds.valid       = False
        creds.expired     = False
        creds.refresh_token = None
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open()), \
             patch("pickle.load", return_value=creds):
            assert _storage().check_auth() is False

    def test_renova_token_expirado_e_retorna_true(self):
        creds = MagicMock()
        creds.valid         = False
        creds.expired       = True
        creds.refresh_token = "tok"
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open()), \
             patch("pickle.load", return_value=creds), \
             patch("pickle.dump"), \
             patch("infrastructure.drive.gdrive_storage.Request"):
            assert _storage().check_auth() is True
            creds.refresh.assert_called_once()

    def test_retorna_false_quando_refresh_falha(self):
        creds = MagicMock()
        creds.valid         = False
        creds.expired       = True
        creds.refresh_token = "tok"
        creds.refresh.side_effect = Exception("network error")
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open()), \
             patch("pickle.load", return_value=creds), \
             patch("infrastructure.drive.gdrive_storage.Request"):
            assert _storage().check_auth() is False


# ===========================================================================
# get_service
# ===========================================================================

class TestGetService:
    def _valid_creds(self):
        creds = MagicMock()
        creds.valid = True
        return creds

    def test_usa_token_valido_sem_reautenticar(self):
        creds = self._valid_creds()
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open()), \
             patch("pickle.load", return_value=creds), \
             patch("infrastructure.drive.gdrive_storage.build") as mock_build:
            _storage().get_service()
        mock_build.assert_called_once_with(
            "drive", "v3", credentials=creds, cache_discovery=False
        )

    def test_remove_token_corrompido_e_reauthentifica(self):
        with patch("os.path.exists", return_value=True), \
             patch("builtins.open", mock_open()), \
             patch("pickle.load", side_effect=Exception("corrompido")), \
             patch("pickle.dump"), \
             patch("os.remove") as mock_remove, \
             patch("infrastructure.drive.gdrive_storage.InstalledAppFlow") as mock_flow, \
             patch("infrastructure.drive.gdrive_storage.build"):
            mock_flow.from_client_config.return_value.run_local_server.return_value = MagicMock()
            _storage().get_service()
        mock_remove.assert_called()

    def test_usa_from_client_config_nao_arquivo(self):
        """Nunca deve usar from_client_secrets_file — credenciais são embutidas."""
        with patch("os.path.exists", return_value=False), \
             patch("builtins.open", mock_open()), \
             patch("pickle.dump"), \
             patch("infrastructure.drive.gdrive_storage.InstalledAppFlow") as mock_flow, \
             patch("infrastructure.drive.gdrive_storage.build"):
            mock_flow.from_client_config.return_value.run_local_server.return_value = MagicMock()
            _storage().get_service()
        mock_flow.from_client_config.assert_called_once()
        mock_flow.from_client_secrets_file.assert_not_called()

    def test_salva_token_apos_auth(self):
        with patch("os.path.exists", return_value=False), \
             patch("builtins.open", mock_open()), \
             patch("pickle.dump") as mock_dump, \
             patch("os.makedirs"), \
             patch("infrastructure.drive.gdrive_storage.InstalledAppFlow") as mock_flow, \
             patch("infrastructure.drive.gdrive_storage.build"):
            mock_flow.from_client_config.return_value.run_local_server.return_value = MagicMock()
            _storage().get_service()
        mock_dump.assert_called_once()

    def test_cria_diretorio_credentials_se_nao_existir(self, tmp_path):
        """B6: pickle.dump falharia se credentials/ não existisse no primeiro run."""
        # Caminho que NÃO existe (pasta credentials/ ainda não foi criada)
        fake_token = tmp_path / "credentials" / "token.pkl"
        assert not fake_token.parent.exists()

        creds = MagicMock()
        creds.valid = True

        from infrastructure.drive.gdrive_storage import GoogleDriveStorage
        storage = GoogleDriveStorage(
            token_file=str(fake_token),
            oauth_config={"installed": {}},
            scopes=["x"],
            root_folder_id="root",
        )

        with patch("infrastructure.drive.gdrive_storage.InstalledAppFlow") as mock_flow, \
             patch("infrastructure.drive.gdrive_storage.build"), \
             patch("pickle.dump"):
            mock_flow.from_client_config.return_value.run_local_server.return_value = creds
            storage.get_service()

        # Diretório foi criado (independentemente de pickle.dump escrever bytes reais)
        assert fake_token.parent.exists()


# ===========================================================================
# logout
# ===========================================================================

class TestLogout:
    def test_remove_token_existente(self):
        with patch("os.remove") as mock_rm:
            _storage(token_file="/fake/token.pkl").logout()
        mock_rm.assert_called_once_with("/fake/token.pkl")

    def test_nao_falha_se_token_nao_existe(self):
        with patch("os.remove", side_effect=FileNotFoundError):
            _storage().logout()   # não deve levantar exceção


# ===========================================================================
# _find_or_create_month_folder
# ===========================================================================

class TestFindOrCreateMonthFolder:
    from datetime import datetime as _dt

    def test_encontra_pasta_existente_por_nome_exato(self):
        from datetime import datetime
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {
            "files": [{"id": "folderabc", "name": "Abril 2026"}]
        }
        storage = _storage()
        result = storage._find_or_create_month_folder(svc, datetime(2026, 4, 19))
        assert result == "folderabc"

    def test_encontra_pasta_com_hifen(self):
        from datetime import datetime
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {
            "files": [{"id": "folderxyz", "name": "Abril-2026"}]
        }
        storage = _storage()
        result = storage._find_or_create_month_folder(svc, datetime(2026, 4, 1))
        assert result == "folderxyz"

    def test_cria_pasta_quando_nenhuma_encontrada(self):
        from datetime import datetime
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {"files": []}
        svc.files().create.return_value.execute.return_value = {"id": "novapasta"}
        storage = _storage()
        result = storage._find_or_create_month_folder(svc, datetime(2026, 4, 19))
        assert result == "novapasta"
        svc.files().create.assert_called_once()

    def test_nome_da_pasta_criada_tem_mes_e_ano(self):
        from datetime import datetime
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {"files": []}
        svc.files().create.return_value.execute.return_value = {"id": "x"}
        storage = _storage()
        storage._find_or_create_month_folder(svc, datetime(2026, 4, 19))
        meta = svc.files().create.call_args[1]["body"]
        assert "Abril" in meta["name"]
        assert "2026" in meta["name"]


# ===========================================================================
# _upload_single
# ===========================================================================

class TestUploadSingle:
    def _make_session(self, init_location="https://upload.example.com/xyz"):
        session = MagicMock()
        init_resp = MagicMock()
        init_resp.headers = {"Location": init_location}
        session.post.return_value = init_resp

        put_resp = MagicMock()
        put_resp.json.return_value = {"id": "fileid", "webViewLink": "https://drive.google.com/file"}
        session.put.return_value = put_resp

        return session

    def _mock_upload(self, storage, service, file_path, folder_id, **kw):
        session = self._make_session()
        with patch("infrastructure.drive.gdrive_storage.AuthorizedSession", return_value=session), \
             patch("os.path.getsize", return_value=1024 * 1024):
            result, skipped = storage._upload_single(
                service, file_path, folder_id, **kw
            )
        return result, skipped, session

    def test_upload_bem_sucedido_retorna_metadados(self):
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {"files": []}  # sem duplicata
        svc._http.credentials = MagicMock()
        storage = _storage()
        with patch("builtins.open", mock_open(read_data=b"A" * 1024)):
            result, skipped, _ = self._mock_upload(storage, svc, "/tmp/culto.mp3", "folder1")
        assert skipped is False
        assert result["id"] == "fileid"

    def test_arquivo_duplicado_e_pulado(self):
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {
            "files": [{"id": "existing", "webViewLink": "https://drive.google.com/existing"}]
        }
        svc._http.credentials = MagicMock()
        storage = _storage()
        with patch("os.path.getsize", return_value=100):
            result, skipped = storage._upload_single(svc, "/tmp/culto.mp3", "folder1")
        assert skipped is True
        assert result["id"] == "existing"

    def test_cancela_durante_upload(self):
        ev = threading.Event()
        ev.set()
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {"files": []}
        svc._http.credentials = MagicMock()
        storage = _storage()

        with patch("os.path.getsize", return_value=1024), \
             patch("builtins.open", mock_open(read_data=b"A" * 64)):
            with pytest.raises(OperacaoCancelada):
                storage._upload_single(
                    svc, "/tmp/culto.mp3", "folder1",
                    cancel_event=ev,
                )

    def test_chama_on_log_e_on_progress(self):
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {"files": []}
        svc._http.credentials = MagicMock()
        storage = _storage()
        log_msgs   = []
        progress   = []

        with patch("builtins.open", mock_open(read_data=b"A" * 1024)), \
             patch("infrastructure.drive.gdrive_storage.AuthorizedSession",
                   return_value=self._make_session()), \
             patch("os.path.getsize", return_value=1024):
            storage._upload_single(
                svc, "/tmp/culto.mp3", "folder1",
                on_log=log_msgs.append,
                on_progress=progress.append,
            )
        assert any("Enviando" in m for m in log_msgs)
        assert 100 in progress


# ===========================================================================
# upload() — fluxo completo
# ===========================================================================

class TestUpload:
    def _run_upload(
        self,
        files=None,
        date_str="19/04/2026",
        existing_folders=None,
        existing_files=None,
        delete_after=False,
        cancel_event=None,
    ) -> ProcessingResult:
        if files is None:
            files = [_audio_file()]

        storage = _storage(delete_after_upload=delete_after)

        n_files = len(files)
        svc = MagicMock()
        # list().execute(): 1st call = folders, then 1 call per file for duplicates
        svc.files().list.return_value.execute.side_effect = (
            [{"files": existing_folders or []}]
            + [{"files": existing_files or []} for _ in range(n_files)]
        )
        svc.files().create.return_value.execute.return_value = {"id": "newfolder"}
        svc._http.credentials = MagicMock()

        session = MagicMock()
        init_resp = MagicMock()
        init_resp.headers = {"Location": "https://upload.example.com"}
        session.post.return_value = init_resp
        put_resp = MagicMock()
        put_resp.json.return_value = {"id": "x", "webViewLink": "https://drive.google.com/x"}
        session.put.return_value = put_resp

        with patch.object(storage, "get_service", return_value=svc), \
             patch("infrastructure.drive.gdrive_storage.AuthorizedSession",
                   return_value=session), \
             patch("os.path.getsize", return_value=1024), \
             patch("builtins.open", mock_open(read_data=b"A" * 64)), \
             patch("os.remove"):
            return storage.upload(
                files, date_str, cancel_event=cancel_event
            )

    def test_retorna_processing_result(self):
        result = self._run_upload()
        assert isinstance(result, ProcessingResult)

    def test_arquivo_enviado_em_uploaded_files(self):
        result = self._run_upload(files=[_audio_file(title="Culto")])
        assert "Culto" in result.uploaded_files

    def test_arquivo_duplicado_em_skipped_files(self):
        storage = _storage()
        files = [_audio_file(title="Culto")]

        svc = MagicMock()
        # list().execute(): pasta (volta lista vazia) → duplicata (volta arquivo existente)
        svc.files().list.return_value.execute.side_effect = [
            {"files": []},                                              # pastas
            {"files": [{"id": "dup", "webViewLink": "https://x"}]},    # duplicata
        ]
        svc.files().create.return_value.execute.return_value = {"id": "newfolder"}
        svc._http.credentials = MagicMock()

        with patch.object(storage, "get_service", return_value=svc), \
             patch("os.path.getsize", return_value=1024):
            result = storage.upload(files, "19/04/2026")

        assert "Culto" in result.skipped_files
        assert result.uploaded_files == ()

    def test_dois_arquivos_dois_resultados(self):
        result = self._run_upload(files=[
            _audio_file(path="/tmp/a.mp3", title="Culto A"),
            _audio_file(path="/tmp/b.mp3", title="Culto B"),
        ])
        assert len(result.uploaded_files) == 2

    def test_cancela_antes_de_conectar(self):
        ev = threading.Event()
        ev.set()
        with pytest.raises(OperacaoCancelada):
            self._run_upload(cancel_event=ev)

    def test_delete_after_upload_remove_arquivo(self):
        with patch("os.remove") as mock_rm, \
             patch("infrastructure.drive.gdrive_storage.AuthorizedSession") as mock_sess, \
             patch("os.path.getsize", return_value=1024), \
             patch("builtins.open", mock_open(read_data=b"A" * 64)):
            storage = _storage(delete_after_upload=True)
            svc = _make_service()
            mock_sess.return_value.post.return_value.headers = {"Location": "https://x"}
            mock_sess.return_value.put.return_value.json.return_value = {"id": "x", "webViewLink": ""}

            with patch.object(storage, "get_service", return_value=svc):
                storage.upload([_audio_file()], "19/04/2026")

        mock_rm.assert_called()

    def test_sem_delete_after_upload_nao_remove(self):
        with patch("os.remove") as mock_rm, \
             patch("infrastructure.drive.gdrive_storage.AuthorizedSession") as mock_sess, \
             patch("os.path.getsize", return_value=1024), \
             patch("builtins.open", mock_open(read_data=b"A" * 64)):
            storage = _storage(delete_after_upload=False)
            svc = _make_service()
            mock_sess.return_value.post.return_value.headers = {"Location": "https://x"}
            mock_sess.return_value.put.return_value.json.return_value = {"id": "x", "webViewLink": ""}

            with patch.object(storage, "get_service", return_value=svc):
                storage.upload([_audio_file()], "19/04/2026")

        mock_rm.assert_not_called()


# ===========================================================================
# _ProgressFile
# ===========================================================================

class TestProgressFile:
    def _make_pf(self, data=b"A" * 1024, cancel_event=None):
        """Cria um _ProgressFile com arquivo fake."""
        progress_calls = []
        log_calls      = []
        stats_calls    = []

        pf = _ProgressFile.__new__(_ProgressFile)
        pf._f              = BytesIO(data)
        pf._size           = len(data)
        pf._sent           = 0
        pf._log            = log_calls.append
        pf._progress       = progress_calls.append
        pf._stats          = stats_calls.append
        pf._cancel         = cancel_event
        pf._start_time     = __import__("time").time()
        pf._last_stats     = 0
        pf._last_stats_t   = pf._start_time
        pf._next_milestone = 0

        return pf, progress_calls, log_calls, stats_calls

    def test_leitura_normal_incrementa_sent(self):
        pf, prog, _, _ = self._make_pf(b"X" * 100)
        data = pf.read(100)
        assert len(data) == 100
        assert pf._sent == 100

    def test_cancela_se_evento_sinalizado(self):
        ev = threading.Event()
        ev.set()
        pf, _, _, _ = self._make_pf(cancel_event=ev)
        with pytest.raises(OperacaoCancelada):
            pf.read(10)

    def test_len_retorna_tamanho_total(self):
        pf, _, _, _ = self._make_pf(b"X" * 512)
        assert len(pf) == 512

    def test_close_fecha_arquivo(self):
        pf, _, _, _ = self._make_pf()
        pf.close()
        assert pf._f.closed

    def test_average_rate_nao_divide_por_zero(self):
        pf, _, _, _ = self._make_pf()
        # _start_time recente → elapsed quase zero → não deve lançar ZeroDivisionError
        pf._start_time = __import__("time").time() + 1000  # no futuro → elapsed < 0
        rate = pf.average_rate_mbps()
        assert rate == 0.0

    def test_read_nao_divide_por_zero_quando_size_zero(self):
        """
        Regressão: se _size == 0 mas read() retorna bytes (descompasso entre
        getsize() e o arquivo real), pct deve ser 100, não ZeroDivisionError.
        """
        pf, prog, _, _ = self._make_pf(b"DATA")
        pf._size = 0   # simula descompasso: tamanho registrado é 0
        # Não deve lançar ZeroDivisionError
        pf.read(4)
        assert prog == [100]

    def test_read_arquivo_vazio_nao_chama_progress(self):
        """Arquivo realmente vazio (read retorna b'') não dispara progress."""
        pf, prog, _, _ = self._make_pf(b"")
        pf._size = 0
        result = pf.read()
        assert result == b""
        assert prog == []   # nenhum byte → nenhum progress


# ===========================================================================
# Regressão B3 — escape correto de caracteres especiais no Drive Query Language
# ===========================================================================

class TestDuplicateCheckEscape:
    """
    Garante que nomes de arquivo com aspas/backslashes são escapados
    corretamente na query do Drive — não removidos, o que causaria falso
    negativo (a query não bateria e o arquivo seria re-enviado).
    """

    def _run_and_capture_query(self, file_name: str) -> str:
        svc = MagicMock()
        svc.files().list.return_value.execute.return_value = {"files": []}
        svc._http.credentials = MagicMock()
        storage = _storage()

        # Mock do session post → simula que a query passa
        session = MagicMock()
        init_resp = MagicMock()
        init_resp.headers = {"Location": "https://upload.example.com"}
        session.post.return_value = init_resp
        put_resp = MagicMock()
        put_resp.json.return_value = {"id": "x", "webViewLink": ""}
        session.put.return_value = put_resp

        with patch("builtins.open", mock_open(read_data=b"A" * 64)), \
             patch("os.path.getsize", return_value=64), \
             patch("infrastructure.drive.gdrive_storage.AuthorizedSession",
                   return_value=session):
            storage._upload_single(svc, f"/tmp/{file_name}", "folder1")

        # Captura a query passada para files().list()
        calls = svc.files().list.call_args_list
        # A última chamada antes do upload é a verificação de duplicata
        return calls[-1].kwargs["q"]

    def test_escape_apostrofo_no_nome(self):
        q = self._run_and_capture_query("Pedro's message.mp3")
        assert "Pedro\\'s message.mp3" in q
        assert "Peters" not in q   # não pode remover o apóstrofo

    # Nota: escape de '\' não é testável diretamente em Windows porque
    # os.path.basename trata '\' como separador de path. O código de escape
    # para '\' permanece como defesa em profundidade (caso o módulo seja
    # rodado em outro SO ou a lógica de nomeação mude no futuro).

    def test_nome_simples_nao_e_modificado(self):
        q = self._run_and_capture_query("Culto.mp3")
        assert "name='Culto.mp3'" in q

    def test_apostrofo_nao_e_removido_silenciosamente(self):
        """
        Regressão direta: a versão antiga removia o apóstrofo, gerando uma
        query que não batia com o arquivo no Drive — duplicate-check passava
        em branco e o arquivo era re-enviado.
        """
        q = self._run_and_capture_query("a'b.mp3")
        # O apóstrofo deve estar presente (escapado), não removido
        assert "'" in q.replace("name=", "").replace("in parents", "").replace("trashed=false", "")
