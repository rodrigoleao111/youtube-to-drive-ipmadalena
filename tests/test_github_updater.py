"""
Testes para infrastructure/updater/github_updater.py

Cobre:
  - _version_tuple: conversão de string para tupla
  - check_latest_version: comparação de versões, extração de download_url,
    tratamento de resposta sem asset .exe, falha de rede
  - download_release: chamada a urlretrieve com reporthook correto
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, call, patch

import pytest

from infrastructure.updater.github_updater import (
    _version_tuple,
    check_latest_version,
    download_release,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO = "dono/repo"
_CURRENT = "v3.2.0"


def _make_response(tag: str, assets: list[dict] | None = None) -> MagicMock:
    """Simula urllib.request.urlopen context manager com payload GitHub."""
    payload = {
        "tag_name": tag,
        "assets": assets
        if assets is not None
        else [
            {
                "name": "IPMadalena_Setup.exe",
                "browser_download_url": f"https://github.com/releases/{tag}/IPMadalena_Setup.exe",
            }
        ],
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode()
    mock_ctx = MagicMock()
    mock_ctx.__enter__ = MagicMock(return_value=mock_resp)
    mock_ctx.__exit__ = MagicMock(return_value=False)
    return mock_ctx


# ===========================================================================
# _version_tuple
# ===========================================================================


class TestVersionTuple:

    def test_converte_com_prefixo_v(self):
        assert _version_tuple("v3.2.0") == (3, 2, 0)

    def test_converte_sem_prefixo_v(self):
        assert _version_tuple("3.2.0") == (3, 2, 0)

    def test_comparacao_numerica_correta(self):
        # "v3.10.0" deve ser maior que "v3.9.0"
        assert _version_tuple("v3.10.0") > _version_tuple("v3.9.0")

    def test_versoes_iguais(self):
        assert _version_tuple("v3.2.0") == _version_tuple("v3.2.0")

    def test_versao_maior_no_patch(self):
        assert _version_tuple("v3.2.1") > _version_tuple("v3.2.0")

    def test_versao_maior_no_minor(self):
        assert _version_tuple("v3.3.0") > _version_tuple("v3.2.0")

    def test_versao_maior_no_major(self):
        assert _version_tuple("v4.0.0") > _version_tuple("v3.2.0")


# ===========================================================================
# check_latest_version
# ===========================================================================


class TestCheckLatestVersion:

    def test_retorna_none_quando_versao_igual(self):
        with patch("urllib.request.urlopen", return_value=_make_response("v3.2.0")):
            assert check_latest_version(_REPO, _CURRENT) is None

    def test_retorna_none_quando_versao_anterior(self):
        with patch("urllib.request.urlopen", return_value=_make_response("v3.1.0")):
            assert check_latest_version(_REPO, _CURRENT) is None

    def test_retorna_dict_quando_versao_nova(self):
        with patch("urllib.request.urlopen", return_value=_make_response("v3.3.0")):
            result = check_latest_version(_REPO, _CURRENT)
        assert result is not None
        assert result["version"] == "v3.3.0"

    def test_download_url_e_o_exe_do_release(self):
        with patch("urllib.request.urlopen", return_value=_make_response("v3.3.0")):
            result = check_latest_version(_REPO, _CURRENT)
        assert result["download_url"].endswith(".exe")

    def test_retorna_none_quando_sem_asset_exe(self):
        assets = [{"name": "source.zip", "browser_download_url": "https://example.com/source.zip"}]
        with patch("urllib.request.urlopen", return_value=_make_response("v3.3.0", assets=assets)):
            assert check_latest_version(_REPO, _CURRENT) is None

    def test_retorna_none_quando_tag_vazia(self):
        payload = {"tag_name": "", "assets": []}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_resp)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_ctx):
            assert check_latest_version(_REPO, _CURRENT) is None

    def test_propaga_erro_de_rede(self):
        with patch("urllib.request.urlopen", side_effect=OSError("sem rede")):
            with pytest.raises(OSError):
                check_latest_version(_REPO, _CURRENT)

    def test_ignora_assets_nao_exe(self):
        assets = [
            {"name": "checksums.txt", "browser_download_url": "https://example.com/checksums.txt"},
            {"name": "IPMadalena_Setup.exe", "browser_download_url": "https://example.com/setup.exe"},
        ]
        with patch("urllib.request.urlopen", return_value=_make_response("v3.3.0", assets=assets)):
            result = check_latest_version(_REPO, _CURRENT)
        assert result["download_url"] == "https://example.com/setup.exe"


# ===========================================================================
# download_release
# ===========================================================================


class TestDownloadRelease:

    def test_chama_urlretrieve_com_url_e_destino(self, tmp_path):
        dest = str(tmp_path / "update.exe")
        with patch("urllib.request.urlretrieve") as mock_retr:
            download_release("https://example.com/setup.exe", dest, lambda p: None)
        assert mock_retr.call_args[0][0] == "https://example.com/setup.exe"
        assert mock_retr.call_args[0][1] == dest

    def test_reporthook_chama_on_progress(self, tmp_path):
        dest = str(tmp_path / "update.exe")
        progress_values: list[float] = []

        def fake_urlretrieve(url, path, reporthook):
            reporthook(0, 1024, 4096)   # 0%
            reporthook(2, 1024, 4096)   # 50%
            reporthook(4, 1024, 4096)   # 100%

        with patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
            download_release("https://example.com/setup.exe", dest, progress_values.append)

        assert len(progress_values) == 3
        assert progress_values[0] == pytest.approx(0.0)
        assert progress_values[1] == pytest.approx(0.5)
        assert progress_values[2] == pytest.approx(1.0)

    def test_progresso_nao_excede_1_0(self, tmp_path):
        dest = str(tmp_path / "update.exe")
        progress_values: list[float] = []

        def fake_urlretrieve(url, path, reporthook):
            # bloco além do total (arredondamento)
            reporthook(5, 1024, 4096)

        with patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
            download_release("https://example.com/setup.exe", dest, progress_values.append)

        assert all(p <= 1.0 for p in progress_values)

    def test_sem_total_nao_chama_on_progress(self, tmp_path):
        dest = str(tmp_path / "update.exe")
        called = []

        def fake_urlretrieve(url, path, reporthook):
            reporthook(1, 1024, 0)  # total=0 → não deve chamar

        with patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
            download_release("https://example.com/setup.exe", dest, called.append)

        assert called == []
