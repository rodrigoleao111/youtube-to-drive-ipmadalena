"""
Testes unitários para baixar_audio.py.

Cobre:
  - check_internet
  - check_disk_space
  - cleanup_downloads
  - load_history / save_history
  - _check_cancel / OperacaoCancelada
  - get_drive_service (token corrompido, credenciais embutidas)
  - --socket-timeout nos comandos yt-dlp
  - download_selected_sections (seções + vídeo completo)
  - modo debug: arquivo mantido em downloads/ quando não-frozen
"""

import json
import os
import pickle
import sys
import subprocess
import threading
from unittest.mock import MagicMock, patch

import pytest

import baixar_audio


# ---------------------------------------------------------------------------
# check_internet
# ---------------------------------------------------------------------------

class TestCheckInternet:
    def test_returns_true_when_connected(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value = MagicMock()
            assert baixar_audio.check_internet() is True

    def test_returns_false_when_no_connection(self):
        with patch("socket.create_connection", side_effect=OSError("timeout")):
            assert baixar_audio.check_internet() is False

    def test_uses_google_dns_as_probe(self):
        with patch("socket.create_connection") as mock_conn:
            mock_conn.return_value = MagicMock()
            baixar_audio.check_internet()
        args = mock_conn.call_args[0][0]
        assert args == ("8.8.8.8", 53)

    def test_resets_socket_timeout_after_call(self):
        """Timeout global deve ser None após a chamada (evita quebrar o OAuth)."""
        import socket
        with patch("socket.create_connection"):
            baixar_audio.check_internet()
        assert socket.getdefaulttimeout() is None


# ---------------------------------------------------------------------------
# check_disk_space
# ---------------------------------------------------------------------------

class TestCheckDiskSpace:
    def test_ok_when_enough_space(self, tmp_path):
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)), \
             patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=1000 * 1024 * 1024)
            ok, free_mb = baixar_audio.check_disk_space(min_mb=500)
        assert ok is True
        assert free_mb == pytest.approx(1000.0, abs=1)

    def test_fails_when_insufficient_space(self, tmp_path):
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)), \
             patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=100 * 1024 * 1024)
            ok, free_mb = baixar_audio.check_disk_space(min_mb=500)
        assert ok is False
        assert free_mb == pytest.approx(100.0, abs=1)

    def test_creates_download_dir_if_missing(self, tmp_path):
        target = str(tmp_path / "novo_dir")
        with patch.object(baixar_audio, "DOWNLOAD_DIR", target), \
             patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=999 * 1024 * 1024)
            baixar_audio.check_disk_space()
        assert os.path.isdir(target)


# ---------------------------------------------------------------------------
# cleanup_downloads
# ---------------------------------------------------------------------------

class TestCleanupDownloads:
    def test_removes_audio_residuals(self, tmp_path):
        for name in ["audio.mp3", "video.webm", "track.m4a", "song.opus"]:
            (tmp_path / name).write_text("dummy")
        (tmp_path / "notes.txt").write_text("keep me")

        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)):
            logs = []
            baixar_audio.cleanup_downloads(on_log=logs.append)

        remaining = [f.name for f in tmp_path.iterdir()]
        assert remaining == ["notes.txt"]
        assert any("4" in m for m in logs)

    def test_no_error_when_dir_is_empty(self, tmp_path):
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)):
            baixar_audio.cleanup_downloads()

    def test_no_error_when_dir_does_not_exist(self, tmp_path):
        missing = str(tmp_path / "ghost_dir")
        with patch.object(baixar_audio, "DOWNLOAD_DIR", missing):
            baixar_audio.cleanup_downloads()

    def test_no_log_when_nothing_removed(self, tmp_path):
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)):
            logs = []
            baixar_audio.cleanup_downloads(on_log=logs.append)
        assert logs == []


# ---------------------------------------------------------------------------
# load_history / save_history
# ---------------------------------------------------------------------------

class TestHistory:
    def test_load_returns_empty_when_file_missing(self, tmp_path):
        with patch.object(baixar_audio, "HISTORY_FILE", str(tmp_path / "hist.json")):
            assert baixar_audio.load_history() == {}

    def test_load_returns_empty_on_corrupt_json(self, tmp_path):
        hist_file = tmp_path / "hist.json"
        hist_file.write_text("{ INVALIDO }", encoding="utf-8")
        with patch.object(baixar_audio, "HISTORY_FILE", str(hist_file)):
            assert baixar_audio.load_history() == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        hist_file = tmp_path / "hist.json"
        with patch.object(baixar_audio, "HISTORY_FILE", str(hist_file)):
            baixar_audio.save_history("19/04/2026", ["Culto A", "Culto B"])
            result = baixar_audio.load_history()

        assert "19/04/2026" in result
        assert result["19/04/2026"]["videos"] == ["Culto A", "Culto B"]
        assert "processado_em" in result["19/04/2026"]

    def test_save_preserves_other_entries(self, tmp_path):
        hist_file = tmp_path / "hist.json"
        with patch.object(baixar_audio, "HISTORY_FILE", str(hist_file)):
            baixar_audio.save_history("01/01/2026", ["Culto X"])
            baixar_audio.save_history("02/01/2026", ["Culto Y"])
            result = baixar_audio.load_history()

        assert "01/01/2026" in result
        assert "02/01/2026" in result

    def test_save_overwrites_existing_entry(self, tmp_path):
        hist_file = tmp_path / "hist.json"
        with patch.object(baixar_audio, "HISTORY_FILE", str(hist_file)):
            baixar_audio.save_history("19/04/2026", ["Versão antiga"])
            baixar_audio.save_history("19/04/2026", ["Versão nova"])
            result = baixar_audio.load_history()

        assert result["19/04/2026"]["videos"] == ["Versão nova"]

    def test_history_file_is_valid_json(self, tmp_path):
        hist_file = tmp_path / "hist.json"
        with patch.object(baixar_audio, "HISTORY_FILE", str(hist_file)):
            baixar_audio.save_history("19/04/2026", ["Culto"])

        with open(hist_file, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# _check_cancel / OperacaoCancelada
# ---------------------------------------------------------------------------

class TestCancelEvent:
    def test_raises_when_event_is_set(self):
        event = threading.Event()
        event.set()
        with pytest.raises(baixar_audio.OperacaoCancelada):
            baixar_audio._check_cancel(event)

    def test_no_exception_when_event_not_set(self):
        event = threading.Event()
        baixar_audio._check_cancel(event)

    def test_no_exception_when_event_is_none(self):
        baixar_audio._check_cancel(None)

    def test_exception_message_is_descriptive(self):
        event = threading.Event()
        event.set()
        with pytest.raises(baixar_audio.OperacaoCancelada, match="cancelad"):
            baixar_audio._check_cancel(event)


# ---------------------------------------------------------------------------
# get_drive_service — credenciais embutidas + token corrompido
# ---------------------------------------------------------------------------

class TestGetDriveServiceToken:
    def _make_mock_flow(self):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds
        return mock_flow, mock_creds

    def test_usa_from_client_config_nao_arquivo(self, tmp_path):
        """Credenciais OAuth são embutidas — não deve ler nenhum arquivo externo."""
        token_file = tmp_path / "token.pkl"
        mock_flow, mock_creds = self._make_mock_flow()

        with patch.object(baixar_audio, "TOKEN_FILE", str(token_file)), \
             patch("infrastructure.drive.gdrive_storage.InstalledAppFlow") as MockFlow, \
             patch("infrastructure.drive.gdrive_storage.build"), \
             patch("pickle.dump"):
            MockFlow.from_client_config.return_value = mock_flow
            baixar_audio.get_drive_service()

        MockFlow.from_client_config.assert_called_once()
        # Nunca deve tentar ler de arquivo externo
        MockFlow.from_client_secrets_file.assert_not_called()

    def test_logs_and_recovers_from_corrupted_token(self, tmp_path):
        token_file = tmp_path / "token.pkl"
        token_file.write_bytes(b"dados corrompidos aqui!!!")

        mock_flow, _ = self._make_mock_flow()
        logs = []

        with patch.object(baixar_audio, "TOKEN_FILE", str(token_file)), \
             patch("infrastructure.drive.gdrive_storage.InstalledAppFlow") as MockFlow, \
             patch("infrastructure.drive.gdrive_storage.build"), \
             patch("pickle.dump"):
            MockFlow.from_client_config.return_value = mock_flow
            baixar_audio.get_drive_service(on_log=logs.append)

        assert any(
            "corrompido" in m.lower() or "reautenticando" in m.lower()
            for m in logs
        ), f"Esperava log de corrompido/reautenticando, obteve: {logs}"

    def test_deletes_corrupted_token_and_reauths(self, tmp_path):
        token_file = tmp_path / "token.pkl"
        token_file.write_bytes(b"not a pickle")

        mock_flow, _ = self._make_mock_flow()

        with patch.object(baixar_audio, "TOKEN_FILE", str(token_file)), \
             patch("infrastructure.drive.gdrive_storage.InstalledAppFlow") as MockFlow, \
             patch("infrastructure.drive.gdrive_storage.build"), \
             patch("pickle.dump"):
            MockFlow.from_client_config.return_value = mock_flow
            baixar_audio.get_drive_service()

        MockFlow.from_client_config.assert_called_once()


# ---------------------------------------------------------------------------
# --socket-timeout e flags nos comandos yt-dlp
# ---------------------------------------------------------------------------

class TestSocketTimeout:
    """Verifica que --socket-timeout 30 está presente em todos os comandos yt-dlp."""

    def _capture_cmds(self, fn, *args, **kwargs):
        """
        Chama fn e retorna todos os cmds passados para start_process.

        Patcha tanto baixar_audio._start_process (download_selected legado)
        quanto infrastructure.youtube.ytdlp_source.start_process (funções
        refatoradas: list_videos, download_selected_sections).
        """
        captured = []

        def fake_start_process(cmd, cancel_event=None):
            captured.append(list(cmd))
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.wait = lambda: None
            return proc

        with patch.object(baixar_audio, "_start_process", side_effect=fake_start_process), \
             patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=fake_start_process), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            try:
                fn(*args, **kwargs)
            except Exception:
                pass

        assert captured, "Nenhum processo foi iniciado"
        return captured

    def test_list_videos_has_socket_timeout(self):
        cmds = self._capture_cmds(baixar_audio.list_videos, "19/04/2026")
        cmd = cmds[0]
        assert "--socket-timeout" in cmd
        assert cmd[cmd.index("--socket-timeout") + 1] == "30"

    def test_download_selected_has_socket_timeout(self, tmp_path):
        videos = [{"id": "abc123", "title": "Culto", "upload_date": "20260419"}]
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)):
            cmds = self._capture_cmds(baixar_audio.download_selected, videos)
        cmd = cmds[0]
        assert "--socket-timeout" in cmd
        assert cmd[cmd.index("--socket-timeout") + 1] == "30"

    def test_download_selected_sections_has_socket_timeout(self, tmp_path):
        videos = [{"id": "abc123", "title": "Culto", "start": None, "end": None}]
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)):
            cmds = self._capture_cmds(baixar_audio.download_selected_sections, videos)
        cmd = cmds[0]
        assert "--socket-timeout" in cmd
        assert cmd[cmd.index("--socket-timeout") + 1] == "30"

    def test_list_videos_uses_dateafter_not_date(self):
        cmds = self._capture_cmds(baixar_audio.list_videos, "19/04/2026")
        cmd = cmds[0]
        assert "--date" not in cmd
        assert "--dateafter" in cmd

    def test_list_videos_uses_break_on_reject(self):
        cmds = self._capture_cmds(baixar_audio.list_videos, "19/04/2026")
        assert "--break-on-reject" in cmds[0]


# ---------------------------------------------------------------------------
# download_selected_sections
# ---------------------------------------------------------------------------

class TestDownloadSelectedSections:
    """Testa a função de download com marcação de trecho."""

    def _capture_cmds(self, videos, tmp_path):
        captured = []

        def fake_start_process(cmd, cancel_event=None):
            captured.append(list(cmd))
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.wait = lambda: None
            return proc

        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)), \
             patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=fake_start_process), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            try:
                baixar_audio.download_selected_sections(videos)
            except Exception:
                pass

        return captured

    def test_inclui_download_sections_quando_start_end_presentes(self, tmp_path):
        videos = [{"id": "abc", "title": "Culto", "start": "00:15:00", "end": "01:10:00"}]
        cmds = self._capture_cmds(videos, tmp_path)
        assert len(cmds) == 1
        cmd = cmds[0]
        assert "--download-sections" in cmd
        idx = cmd.index("--download-sections")
        assert cmd[idx + 1] == "*00:15:00-01:10:00"

    def test_nao_inclui_download_sections_quando_start_end_nulos(self, tmp_path):
        videos = [{"id": "abc", "title": "Culto", "start": None, "end": None}]
        cmds = self._capture_cmds(videos, tmp_path)
        assert len(cmds) == 1
        assert "--download-sections" not in cmds[0]

    def test_um_subprocess_por_video(self, tmp_path):
        videos = [
            {"id": "abc", "title": "Culto 1", "start": "00:10:00", "end": "01:00:00"},
            {"id": "def", "title": "Culto 2", "start": None,        "end": None},
        ]
        cmds = self._capture_cmds(videos, tmp_path)
        assert len(cmds) == 2

    def test_url_correta_por_video(self, tmp_path):
        videos = [{"id": "xyz999", "title": "Culto", "start": None, "end": None}]
        cmds = self._capture_cmds(videos, tmp_path)
        assert any("xyz999" in arg for arg in cmds[0])

    def test_formato_da_secao_usa_asterisco(self, tmp_path):
        """yt-dlp exige '*HH:MM:SS-HH:MM:SS' — asterisco obrigatório."""
        videos = [{"id": "abc", "title": "Culto", "start": "00:30:00", "end": "01:30:00"}]
        cmds = self._capture_cmds(videos, tmp_path)
        idx = cmds[0].index("--download-sections")
        assert cmds[0][idx + 1].startswith("*")

    def test_cancela_entre_videos(self, tmp_path):
        """Operação deve ser cancelada entre vídeos quando cancel_event está setado."""
        cancel = threading.Event()
        call_count = 0

        def fake_start_process(cmd, cancel_event=None):
            nonlocal call_count
            call_count += 1
            cancel.set()   # sinaliza no primeiro vídeo
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.wait = lambda: None
            return proc

        videos = [
            {"id": "abc", "title": "Culto 1", "start": None, "end": None},
            {"id": "def", "title": "Culto 2", "start": None, "end": None},
        ]

        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)), \
             patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=fake_start_process), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            with pytest.raises(baixar_audio.OperacaoCancelada):
                baixar_audio.download_selected_sections(videos, cancel_event=cancel)

        assert call_count == 1   # segundo vídeo não deve ser iniciado


# ---------------------------------------------------------------------------
# Modo debug — arquivo mantido após upload quando não-frozen
# ---------------------------------------------------------------------------

class TestDebugMode:
    """
    Em modo script (sys.frozen ausente/False), upload_files() deve manter
    o arquivo local e logar [DEBUG].
    Em modo frozen (exe instalado), deve remover o arquivo.

    upload_files() delega para GoogleDriveStorage.upload() — patches em
    infrastructure.drive.gdrive_storage para evitar I/O real.
    """

    def _run(self, tmp_path, frozen: bool):
        fake_mp3 = tmp_path / "Culto.mp3"
        fake_mp3.write_bytes(b"ID3" + b"\x00" * 64)

        # Mock do serviço Drive (evita autenticação real)
        svc = MagicMock()
        svc.files().list.return_value.execute.side_effect = [
            {"files": []},   # pastas do mês → nenhuma → cria
            {"files": []},   # duplicatas → nenhuma → faz upload
        ]
        svc.files().create.return_value.execute.return_value = {"id": "folder1"}
        svc._http.credentials = MagicMock()

        # Mock da sessão HTTP de upload
        session = MagicMock()
        session.post.return_value.headers = {"Location": "https://upload.example.com"}
        session.put.return_value.json.return_value = {"id": "fileid", "webViewLink": ""}

        with patch("infrastructure.drive.gdrive_storage.GoogleDriveStorage.get_service",
                   return_value=svc), \
             patch("infrastructure.drive.gdrive_storage.AuthorizedSession",
                   return_value=session), \
             patch.object(sys, "frozen", frozen, create=True):
            logs = []
            baixar_audio.upload_files(
                "19/04/2026",
                [str(fake_mp3)],
                on_log=logs.append,
            )
        return fake_mp3, logs

    def test_arquivo_mantido_em_modo_debug(self, tmp_path):
        mp3, logs = self._run(tmp_path, frozen=False)
        assert mp3.exists(), "Arquivo não deveria ser removido em modo debug"

    def test_log_debug_emitido_em_modo_debug(self, tmp_path):
        _, logs = self._run(tmp_path, frozen=False)
        assert any("[DEBUG]" in m for m in logs), \
            f"Esperava mensagem [DEBUG] no log, obteve: {logs}"

    def test_arquivo_removido_em_modo_producao(self, tmp_path):
        mp3, _ = self._run(tmp_path, frozen=True)
        assert not mp3.exists(), "Arquivo deveria ser removido em modo produção"

    def test_sem_log_debug_em_modo_producao(self, tmp_path):
        _, logs = self._run(tmp_path, frozen=True)
        assert not any("[DEBUG]" in m for m in logs)
