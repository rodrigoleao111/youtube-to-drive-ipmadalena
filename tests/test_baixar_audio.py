"""
Testes unitários para baixar_audio.py.

Após a Fase 7 (Clean Architecture), o módulo expõe apenas wrappers finos
sobre as camadas application/infrastructure. Os testes aqui cobrem:

  - check_internet, check_disk_space, cleanup_downloads (utilidades de robustez)
  - load_history / save_history (delegam para JsonHistoryRepository)
  - get_drive_service (delegam para GoogleDriveStorage; token corrompido + credenciais embutidas)

Comportamento de cancelamento, comandos yt-dlp, download de trechos e modo debug
está coberto em test_ytdlp_source.py, test_gdrive_storage.py, test_use_cases.py
e test_presenter.py.
"""

import json
import os
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

    def test_loga_falhas_individuais_sem_interromper(self, tmp_path):
        """B7: arquivos que falham ao remover são logados, demais continuam."""
        for name in ["a.mp3", "b.mp3", "c.mp3"]:
            (tmp_path / name).write_text("x")

        original_remove = os.remove
        def fake_remove(path):
            if path.endswith("b.mp3"):
                raise PermissionError("arquivo em uso")
            original_remove(path)

        with patch.object(baixar_audio, "DOWNLOAD_DIR", str(tmp_path)), \
             patch("os.remove", side_effect=fake_remove):
            logs = []
            baixar_audio.cleanup_downloads(on_log=logs.append)

        assert any("Aviso" in m and "b.mp3" in m for m in logs), \
            f"Esperava aviso sobre b.mp3, obteve: {logs}"
        assert any("2 arquivo" in m for m in logs)   # a.mp3 e c.mp3 removidos


# ---------------------------------------------------------------------------
# update_ytdlp (T3)
# ---------------------------------------------------------------------------

class TestUpdateYtdlp:
    """
    update_ytdlp() tem dois caminhos:
      - frozen=True  → roda 'yt-dlp -U' (auto-update do standalone)
      - frozen=False → roda 'pip install --upgrade yt-dlp' + 'yt-dlp --version'

    Os testes mockam baixar_audio._ytdlp_cmd para evitar dependência de
    sys._MEIPASS (que só existe quando rodando como exe PyInstaller).
    """

    def _result(self, returncode=0, stdout="", stderr=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def _patch_frozen(self, frozen: bool):
        """Helper para mockar sys.frozen e _ytdlp_cmd juntos."""
        import sys as _sys
        return [
            patch.object(_sys, "frozen", frozen, create=True),
            patch.object(baixar_audio, "_ytdlp_cmd", return_value="yt-dlp"),
        ]

    def test_modo_frozen_chama_yt_dlp_U(self):
        patches = self._patch_frozen(True)
        for p in patches: p.start()
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = self._result(0, "Updated to 2026.04.19")
                logs = []
                baixar_audio.update_ytdlp(on_log=logs.append)
                cmd = mock_run.call_args[0][0]
        finally:
            for p in patches: p.stop()

        assert cmd[1] == "-U"
        assert any("2026.04.19" in m for m in logs)

    def test_modo_script_chama_pip_install_e_version(self):
        patches = self._patch_frozen(False)
        for p in patches: p.start()
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = [
                    self._result(0, ""),                # pip install OK
                    self._result(0, "2026.04.19\n"),    # yt-dlp --version
                ]
                logs = []
                baixar_audio.update_ytdlp(on_log=logs.append)
                first_cmd = mock_run.call_args_list[0][0][0]
        finally:
            for p in patches: p.stop()

        assert "pip" in first_cmd
        assert "install" in first_cmd
        assert "yt-dlp" in first_cmd
        assert any("2026.04.19" in m for m in logs)

    def test_aviso_quando_pip_falha(self):
        patches = self._patch_frozen(False)
        for p in patches: p.start()
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = self._result(returncode=1, stderr="erro")
                logs = []
                baixar_audio.update_ytdlp(on_log=logs.append)
        finally:
            for p in patches: p.stop()

        assert any("Aviso" in m for m in logs)

    def test_aviso_quando_subprocess_levanta_excecao(self):
        patches = self._patch_frozen(False)
        for p in patches: p.start()
        try:
            with patch("subprocess.run", side_effect=OSError("yt-dlp não encontrado")):
                logs = []
                baixar_audio.update_ytdlp(on_log=logs.append)
        finally:
            for p in patches: p.stop()

        assert any("Aviso" in m and "yt-dlp" in m.lower() for m in logs)

    def test_extrai_versao_do_output_no_modo_frozen(self):
        patches = self._patch_frozen(True)
        for p in patches: p.start()
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = self._result(0, "yt-dlp 2026.01.15 is up to date")
                logs = []
                baixar_audio.update_ytdlp(on_log=logs.append)
        finally:
            for p in patches: p.stop()

        assert any("2026.01.15" in m for m in logs)

    def test_versao_indeterminada_quando_regex_nao_bate(self):
        patches = self._patch_frozen(True)
        for p in patches: p.start()
        try:
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = self._result(0, "output sem versao reconhecivel")
                logs = []
                baixar_audio.update_ytdlp(on_log=logs.append)
        finally:
            for p in patches: p.stop()

        assert any("?" in m for m in logs)


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


