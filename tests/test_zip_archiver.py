"""
Testes para infrastructure/archive/zip_archiver.py.

I/O real em `tmp_path` (mesma convenção dos repositórios JSON): zipfile é
stdlib e barato, mockar aqui só esconderia bugs de escrita.
"""

from __future__ import annotations

import os
import zipfile
from unittest.mock import patch

import pytest

from domain.ports import IArchiver
from infrastructure.archive.zip_archiver import ZipArchiver


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def episodio(tmp_path):
    """Subpasta com os artefatos de um episódio."""
    sub = tmp_path / "Culto"
    sub.mkdir()
    (sub / "Culto.mp3").write_bytes(b"conteudo do mp3" * 100)
    (sub / "capa.jpg").write_bytes(b"jpg")
    (sub / "descricao.txt").write_text("descrição do culto", encoding="utf-8")
    return sub


def _arquivos(sub):
    return [str(sub / n) for n in ("Culto.mp3", "capa.jpg", "descricao.txt")]


# ===========================================================================
# Contrato
# ===========================================================================

class TestImplementaProtocol:
    def test_e_instance_de_iarchiver(self):
        assert isinstance(ZipArchiver(), IArchiver)


# ===========================================================================
# create()
# ===========================================================================

class TestCreate:

    def test_cria_o_zip_no_caminho_pedido(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        assert ZipArchiver().create(_arquivos(episodio), dest) == dest
        assert os.path.isfile(dest)

    def test_zip_contem_todos_os_arquivos(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        ZipArchiver().create(_arquivos(episodio), dest)
        with zipfile.ZipFile(dest) as zf:
            assert sorted(zf.namelist()) == [
                "Culto.mp3", "capa.jpg", "descricao.txt",
            ]

    def test_arquivos_entram_pelo_basename_sem_diretorios(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        ZipArchiver().create(_arquivos(episodio), dest)
        with zipfile.ZipFile(dest) as zf:
            assert all("/" not in n and "\\" not in n for n in zf.namelist())

    def test_conteudo_preservado(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        ZipArchiver().create(_arquivos(episodio), dest)
        with zipfile.ZipFile(dest) as zf:
            assert zf.read("descricao.txt").decode("utf-8") == "descrição do culto"

    def test_ordem_dos_arquivos_e_preservada(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        ordem = [str(episodio / "capa.jpg"), str(episodio / "Culto.mp3")]
        ZipArchiver().create(ordem, dest)
        with zipfile.ZipFile(dest) as zf:
            assert zf.namelist() == ["capa.jpg", "Culto.mp3"]

    def test_usa_compressao_deflate(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        ZipArchiver().create(_arquivos(episodio), dest)
        with zipfile.ZipFile(dest) as zf:
            info = zf.getinfo("Culto.mp3")
        assert info.compress_type == zipfile.ZIP_DEFLATED
        assert info.compress_size < info.file_size   # texto repetido comprime

    def test_zip_valido(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        ZipArchiver().create(_arquivos(episodio), dest)
        with zipfile.ZipFile(dest) as zf:
            assert zf.testzip() is None

    def test_sobrescreve_zip_existente(self, episodio, tmp_path):
        dest = tmp_path / "pacote.zip"
        dest.write_bytes(b"lixo anterior")
        ZipArchiver().create(_arquivos(episodio), str(dest))
        with zipfile.ZipFile(str(dest)) as zf:
            assert "Culto.mp3" in zf.namelist()

    # -- arquivos ausentes --------------------------------------------------

    def test_ignora_arquivos_inexistentes(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        arquivos = _arquivos(episodio) + [str(episodio / "nao_existe.txt")]
        ZipArchiver().create(arquivos, dest)
        with zipfile.ZipFile(dest) as zf:
            assert "nao_existe.txt" not in zf.namelist()
            assert len(zf.namelist()) == 3

    def test_levanta_value_error_quando_nada_existe(self, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        with pytest.raises(ValueError):
            ZipArchiver().create([str(tmp_path / "fantasma.mp3")], dest)
        assert not os.path.exists(dest)

    def test_lista_vazia_levanta_value_error(self, tmp_path):
        with pytest.raises(ValueError):
            ZipArchiver().create([], str(tmp_path / "pacote.zip"))

    def test_none_na_lista_e_ignorado(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        ZipArchiver().create([None] + _arquivos(episodio), dest)
        with zipfile.ZipFile(dest) as zf:
            assert len(zf.namelist()) == 3

    # -- escrita atômica ----------------------------------------------------

    def test_escreve_via_tmp_e_move_no_final(self, episodio, tmp_path):
        """
        O upload varre a subpasta: um zip incompleto com o nome final seria
        enviado corrompido. Por isso o arquivo só ganha o nome final ao fim.
        """
        dest = str(tmp_path / "pacote.zip")
        vistos = []

        real_replace = os.replace

        def _spy(src, dst):
            vistos.append((os.path.basename(src), os.path.basename(dst)))
            return real_replace(src, dst)

        with patch("os.replace", side_effect=_spy):
            ZipArchiver().create(_arquivos(episodio), dest)

        assert vistos == [("pacote.zip.tmp", "pacote.zip")]

    def test_tmp_removido_quando_a_escrita_falha(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        with patch("os.replace", side_effect=OSError("disco cheio")):
            with pytest.raises(OSError):
                ZipArchiver().create(_arquivos(episodio), dest)
        assert not os.path.exists(dest + ".tmp")
        assert not os.path.exists(dest)

    # -- log ----------------------------------------------------------------

    def test_log_informa_nome_tamanho_e_arquivos(self, episodio, tmp_path):
        dest = str(tmp_path / "pacote.zip")
        logs = []
        ZipArchiver().create(_arquivos(episodio), dest, on_log=logs.append)
        msg = " ".join(logs)
        assert "pacote.zip" in msg
        assert "MB" in msg
        assert "Culto.mp3" in msg

    def test_sem_on_log_nao_quebra(self, episodio, tmp_path):
        ZipArchiver().create(_arquivos(episodio), str(tmp_path / "p.zip"))
