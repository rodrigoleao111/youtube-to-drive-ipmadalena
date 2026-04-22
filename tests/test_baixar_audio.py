"""
Testes unitários para baixar_audio.py.

Cobre:
  - check_internet
  - check_disk_space
  - cleanup_downloads
  - load_history / save_history
  - _check_cancel / OperacaoCancelada
  - get_drive_service (token corrompido)
  - --socket-timeout nos comandos yt-dlp
"""

import json
import os
import pickle
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


# ---------------------------------------------------------------------------
# check_disk_space
# ---------------------------------------------------------------------------

class TestCheckDiskSpace:
    def test_ok_when_enough_space(self, tmp_path):
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)), \
             patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=1000 * 1024 * 1024)  # 1 GB
            ok, free_mb = baixar_audio.check_disk_space(min_mb=500)
        assert ok is True
        assert free_mb == pytest.approx(1000.0, abs=1)

    def test_fails_when_insufficient_space(self, tmp_path):
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)), \
             patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=100 * 1024 * 1024)  # 100 MB
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
            baixar_audio.cleanup_downloads()  # não deve lançar exceção

    def test_no_error_when_dir_does_not_exist(self, tmp_path):
        missing = str(tmp_path / "ghost_dir")
        with patch.object(baixar_audio, "DOWNLOAD_DIR", missing):
            baixar_audio.cleanup_downloads()  # não deve lançar exceção

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
        baixar_audio._check_cancel(event)  # não deve lançar

    def test_no_exception_when_event_is_none(self):
        baixar_audio._check_cancel(None)  # não deve lançar

    def test_exception_message_is_descriptive(self):
        event = threading.Event()
        event.set()
        with pytest.raises(baixar_audio.OperacaoCancelada, match="cancelad"):
            baixar_audio._check_cancel(event)


# ---------------------------------------------------------------------------
# get_drive_service — token corrompido
# ---------------------------------------------------------------------------

class TestGetDriveServiceToken:
    def _make_mock_flow(self):
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds
        return mock_flow, mock_creds

    def test_logs_and_recovers_from_corrupted_token(self, tmp_path):
        token_file = tmp_path / "token.pkl"
        creds_file = tmp_path / "client_secret.json"
        token_file.write_bytes(b"dados corrompidos aqui!!!")
        creds_file.write_text('{"installed": {}}')

        mock_flow, mock_creds = self._make_mock_flow()
        logs = []

        with patch.object(baixar_audio, "TOKEN_FILE", str(token_file)), \
             patch.object(baixar_audio, "CREDENTIALS_FILE", str(creds_file)), \
             patch("baixar_audio.InstalledAppFlow") as MockFlow, \
             patch("baixar_audio.build"), \
             patch("pickle.dump"):          # MagicMock não é serializável
            MockFlow.from_client_secrets_file.return_value = mock_flow
            baixar_audio.get_drive_service(on_log=logs.append)

        assert any("corrompido" in m.lower() or "reautenticando" in m.lower()
                   for m in logs), f"Esperava log de corrompido/reautenticando, mas obteve: {logs}"

    def test_deletes_corrupted_token_and_reauths(self, tmp_path):
        token_file = tmp_path / "token.pkl"
        creds_file = tmp_path / "client_secret.json"
        token_file.write_bytes(b"not a pickle")
        creds_file.write_text('{"installed": {}}')

        mock_flow, _ = self._make_mock_flow()

        with patch.object(baixar_audio, "TOKEN_FILE", str(token_file)), \
             patch.object(baixar_audio, "CREDENTIALS_FILE", str(creds_file)), \
             patch("baixar_audio.InstalledAppFlow") as MockFlow, \
             patch("baixar_audio.build"), \
             patch("pickle.dump"):          # MagicMock não é serializável
            MockFlow.from_client_secrets_file.return_value = mock_flow
            baixar_audio.get_drive_service()

        # O fluxo de reautenticação deve ter sido iniciado
        MockFlow.from_client_secrets_file.assert_called_once()

    def test_raises_if_credentials_file_missing(self, tmp_path):
        with patch.object(baixar_audio, "TOKEN_FILE", str(tmp_path / "token.pkl")), \
             patch.object(baixar_audio, "CREDENTIALS_FILE", str(tmp_path / "nao_existe.json")):
            with pytest.raises(FileNotFoundError, match="Credenciais"):
                baixar_audio.get_drive_service()


# ---------------------------------------------------------------------------
# --socket-timeout nos comandos yt-dlp
# ---------------------------------------------------------------------------

class TestSocketTimeout:
    """Verifica que --socket-timeout 30 está presente em todos os comandos yt-dlp."""

    def _capture_cmd(self, fn, *args, **kwargs):
        """Chama fn e captura o primeiro cmd passado para _start_process."""
        captured = []

        def fake_start_process(cmd, cancel_event=None):
            captured.append(list(cmd))
            proc = MagicMock()
            proc.stdout = iter([])
            proc.returncode = 0
            proc.wait = lambda: None
            return proc

        with patch.object(baixar_audio, "_start_process", side_effect=fake_start_process):
            try:
                fn(*args, **kwargs)
            except Exception:
                pass

        assert captured, "Nenhum processo foi iniciado"
        return captured[0]

    def test_list_videos_has_socket_timeout(self):
        cmd = self._capture_cmd(baixar_audio.list_videos, "19/04/2026")
        assert "--socket-timeout" in cmd
        idx = cmd.index("--socket-timeout")
        assert cmd[idx + 1] == "30"

    def test_download_selected_has_socket_timeout(self, tmp_path):
        videos = [{"id": "abc123", "title": "Culto", "upload_date": "20260419"}]
        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)):
            cmd = self._capture_cmd(baixar_audio.download_selected, videos)
        assert "--socket-timeout" in cmd
        idx = cmd.index("--socket-timeout")
        assert cmd[idx + 1] == "30"

    def test_list_videos_uses_dateafter_not_date(self):
        """Garante que --date não está no cmd (causaria conflito com --dateafter)."""
        cmd = self._capture_cmd(baixar_audio.list_videos, "19/04/2026")
        assert "--date" not in cmd
        assert "--dateafter" in cmd

    def test_list_videos_uses_break_on_reject(self):
        """Garante que --break-on-reject está presente para parar varredura cedo."""
        cmd = self._capture_cmd(baixar_audio.list_videos, "19/04/2026")
        assert "--break-on-reject" in cmd
