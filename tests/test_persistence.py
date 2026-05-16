"""
Testes para infrastructure/persistence/json_repositories.py.

Usa tmp_path (pytest fixture) — sem mocks de disco; testa I/O real
em diretório temporário isolado. Sem dependências externas.
"""

from __future__ import annotations

import json
import os

import pytest

from infrastructure.persistence.json_repositories import (
    JsonConfigRepository,
    JsonHistoryRepository,
)


# ===========================================================================
# JsonHistoryRepository
# ===========================================================================

class TestJsonHistoryRepository:

    def _repo(self, tmp_path, filename="history.json") -> JsonHistoryRepository:
        return JsonHistoryRepository(file_path=str(tmp_path / filename))

    # -----------------------------------------------------------------------
    # load()
    # -----------------------------------------------------------------------

    def test_load_retorna_vazio_quando_arquivo_nao_existe(self, tmp_path):
        repo = self._repo(tmp_path)
        assert repo.load() == {}

    def test_load_retorna_vazio_quando_json_invalido(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("nao-e-json!!!", encoding="utf-8")
        repo = JsonHistoryRepository(str(path))
        assert repo.load() == {}

    def test_load_retorna_conteudo_correto(self, tmp_path):
        path = tmp_path / "history.json"
        data = {"19/04/2026": {"processado_em": "2026-04-19", "videos": ["Culto"]}}
        path.write_text(json.dumps(data), encoding="utf-8")
        repo = JsonHistoryRepository(str(path))
        assert repo.load() == data

    # -----------------------------------------------------------------------
    # save()
    # -----------------------------------------------------------------------

    def test_save_cria_arquivo(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"19/04/2026": {"processado_em": "2026-04-19", "videos": []}})
        assert (tmp_path / "history.json").exists()

    def test_save_load_roundtrip(self, tmp_path):
        repo = self._repo(tmp_path)
        original = {
            "19/04/2026": {"processado_em": "2026-04-19T10:00:00", "videos": ["Culto A"]},
            "26/04/2026": {"processado_em": "2026-04-26T11:00:00", "videos": ["Culto B"]},
        }
        repo.save(original)
        assert repo.load() == original

    def test_save_sobrescreve_entrada_existente(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"19/04/2026": {"processado_em": "2026-04-19", "videos": ["V1"]}})
        repo.save({"19/04/2026": {"processado_em": "2026-04-19", "videos": ["V2"]}})
        result = repo.load()
        assert result["19/04/2026"]["videos"] == ["V2"]

    def test_save_silencia_erros_de_io(self, tmp_path):
        """Não deve levantar exceção se o arquivo não puder ser escrito."""
        repo = JsonHistoryRepository(file_path="/diretorio/inexistente/history.json")
        repo.save({"data": "valor"})   # deve passar sem levantar

    def test_arquivo_json_e_valido_apos_save(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"19/04/2026": {"processado_em": "2026-04-19", "videos": ["Culto"]}})
        content = (tmp_path / "history.json").read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert "19/04/2026" in parsed

    # -----------------------------------------------------------------------
    # is_processed()
    # -----------------------------------------------------------------------

    def test_is_processed_retorna_false_para_data_nova(self, tmp_path):
        repo = self._repo(tmp_path)
        assert repo.is_processed("19/04/2026") is False

    def test_is_processed_retorna_true_para_data_gravada(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"19/04/2026": {"processado_em": "2026-04-19", "videos": []}})
        assert repo.is_processed("19/04/2026") is True

    def test_is_processed_retorna_false_para_data_diferente(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"19/04/2026": {"processado_em": "2026-04-19", "videos": []}})
        assert repo.is_processed("26/04/2026") is False

    # -----------------------------------------------------------------------
    # record()
    # -----------------------------------------------------------------------

    def test_record_adiciona_entrada_com_timestamp(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.record("19/04/2026", ["Culto A", "Culto B"])
        data = repo.load()
        assert "19/04/2026" in data
        assert data["19/04/2026"]["videos"] == ["Culto A", "Culto B"]
        assert "processado_em" in data["19/04/2026"]

    def test_record_preserva_outras_entradas(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.record("12/04/2026", ["Culto Antigo"])
        repo.record("19/04/2026", ["Culto Novo"])
        data = repo.load()
        assert "12/04/2026" in data
        assert "19/04/2026" in data

    def test_record_sobrescreve_entrada_da_mesma_data(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.record("19/04/2026", ["Versão 1"])
        repo.record("19/04/2026", ["Versão 2"])
        data = repo.load()
        assert data["19/04/2026"]["videos"] == ["Versão 2"]

    def test_record_aceita_lista_vazia(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.record("19/04/2026", [])
        assert repo.load()["19/04/2026"]["videos"] == []


# ===========================================================================
# JsonConfigRepository
# ===========================================================================

_DEFAULTS = {
    "channel_url":     "https://www.youtube.com/@IPMadalena/streams",
    "drive_folder_id": "1KfsI5zCDL4HZ2pdAWPFfAD3TugplzBez",
}


class TestJsonConfigRepository:

    def _repo(self, tmp_path, filename="config.json") -> JsonConfigRepository:
        return JsonConfigRepository(
            file_path=str(tmp_path / filename),
            defaults=_DEFAULTS,
        )

    # -----------------------------------------------------------------------
    # load()
    # -----------------------------------------------------------------------

    def test_load_retorna_defaults_quando_arquivo_nao_existe(self, tmp_path):
        repo = self._repo(tmp_path)
        cfg = repo.load()
        assert cfg["channel_url"]     == _DEFAULTS["channel_url"]
        assert cfg["drive_folder_id"] == _DEFAULTS["drive_folder_id"]

    def test_load_retorna_defaults_quando_json_invalido(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("{ invalido }", encoding="utf-8")
        repo = JsonConfigRepository(str(path), defaults=_DEFAULTS)
        cfg = repo.load()
        assert cfg["channel_url"] == _DEFAULTS["channel_url"]

    def test_load_preenche_chaves_faltantes_com_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        # Salva arquivo com apenas uma chave
        path.write_text(json.dumps({"channel_url": "https://outro.canal"}), encoding="utf-8")
        repo = JsonConfigRepository(str(path), defaults=_DEFAULTS)
        cfg = repo.load()
        assert cfg["channel_url"]     == "https://outro.canal"        # mantém valor do arquivo
        assert cfg["drive_folder_id"] == _DEFAULTS["drive_folder_id"] # preenche default

    def test_load_retorna_valores_do_arquivo(self, tmp_path):
        path = tmp_path / "config.json"
        data = {"channel_url": "https://novo.canal", "drive_folder_id": "pasta123"}
        path.write_text(json.dumps(data), encoding="utf-8")
        repo = JsonConfigRepository(str(path), defaults=_DEFAULTS)
        cfg = repo.load()
        assert cfg["channel_url"]     == "https://novo.canal"
        assert cfg["drive_folder_id"] == "pasta123"

    # -----------------------------------------------------------------------
    # save()
    # -----------------------------------------------------------------------

    def test_save_cria_arquivo(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"channel_url": "https://x", "drive_folder_id": "abc"})
        assert (tmp_path / "config.json").exists()

    def test_save_load_roundtrip(self, tmp_path):
        repo = self._repo(tmp_path)
        original = {"channel_url": "https://meu.canal", "drive_folder_id": "pasta456"}
        repo.save(original)
        assert repo.load()["channel_url"]     == "https://meu.canal"
        assert repo.load()["drive_folder_id"] == "pasta456"

    def test_save_levanta_excecao_em_path_invalido(self, tmp_path):
        """Diferente do histórico — erros de config devem chegar ao caller."""
        repo = JsonConfigRepository(
            file_path="/caminho/que/nao/existe/config.json",
            defaults=_DEFAULTS,
        )
        with pytest.raises(Exception):
            repo.save({"channel_url": "x"})

    # -----------------------------------------------------------------------
    # get()
    # -----------------------------------------------------------------------

    def test_get_retorna_valor_existente(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"channel_url": "https://canal.teste", "drive_folder_id": "abc"})
        assert repo.get("channel_url") == "https://canal.teste"

    def test_get_retorna_default_para_chave_ausente(self, tmp_path):
        repo = self._repo(tmp_path)
        assert repo.get("chave_inexistente", "valor_default") == "valor_default"

    def test_get_retorna_none_sem_default_especificado(self, tmp_path):
        repo = self._repo(tmp_path)
        assert repo.get("chave_inexistente") is None

    # -----------------------------------------------------------------------
    # update()
    # -----------------------------------------------------------------------

    def test_update_modifica_apenas_campos_fornecidos(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"channel_url": "https://original.canal", "drive_folder_id": "original_id"})
        repo.update(channel_url="https://novo.canal")
        cfg = repo.load()
        assert cfg["channel_url"]     == "https://novo.canal"
        assert cfg["drive_folder_id"] == "original_id"   # não alterado

    def test_update_ignora_valores_none(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save({"channel_url": "https://original", "drive_folder_id": "id123"})
        repo.update(channel_url=None, drive_folder_id="novo_id")
        cfg = repo.load()
        assert cfg["channel_url"]     == "https://original"  # não alterado
        assert cfg["drive_folder_id"] == "novo_id"

    def test_update_strip_em_strings(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.update(channel_url="  https://canal.com  ")
        assert repo.get("channel_url") == "https://canal.com"

    def test_update_cria_arquivo_se_nao_existir(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.update(channel_url="https://novo.canal")
        assert (tmp_path / "config.json").exists()
        assert repo.get("channel_url") == "https://novo.canal"


# ===========================================================================
# JsonConfigRepository — chave 'audio_edit' (PR 1 do plano de edição de áudio)
# ===========================================================================

class TestJsonConfigRepositoryAudioEdit:
    """
    Verifica que a chave 'audio_edit' do config.json:
      - é preenchida com o default de AudioEditConfig().to_dict() em arquivos
        legados que não a possuem (backwards compatibility);
      - sobrevive a round-trip JSON sem perda de informação;
      - reconstrói corretamente um AudioEditConfig via from_dict().
    """

    def _repo(self, tmp_path, with_audio_default=True):
        from domain.entities import AudioEditConfig
        defaults = {
            "channel_url":     "https://example.com",
            "drive_folder_id": "FOLDER",
        }
        if with_audio_default:
            defaults["audio_edit"] = AudioEditConfig().to_dict()
        return JsonConfigRepository(
            file_path=str(tmp_path / "config.json"),
            defaults=defaults,
        )

    def test_load_aplica_default_em_arquivo_legado_sem_chave(self, tmp_path):
        # Simula um config.json antigo (pré-edição-de-áudio)
        legacy = {"channel_url": "https://canal.legado", "drive_folder_id": "LEG"}
        (tmp_path / "config.json").write_text(json.dumps(legacy), encoding="utf-8")

        cfg = self._repo(tmp_path).load()

        assert "audio_edit" in cfg
        assert cfg["audio_edit"]["fade_in_enabled"] is False
        assert cfg["audio_edit"]["eq_enabled"]     is False
        assert cfg["audio_edit"]["noise_reduction_enabled"] is False

    def test_load_sem_arquivo_retorna_default(self, tmp_path):
        cfg = self._repo(tmp_path).load()
        assert cfg["audio_edit"]["fade_in_enabled"] is False

    def test_save_load_roundtrip_preserva_audio_edit(self, tmp_path):
        from domain.entities import AudioEditConfig
        repo = self._repo(tmp_path)

        custom = AudioEditConfig(
            fade_in_enabled=True,
            fade_in_secs=4.0,
            eq_enabled=True,
            noise_reduction_enabled=True,
            noise_reduction_intensity="alta",
        )
        cfg = repo.load()
        cfg["audio_edit"] = custom.to_dict()
        repo.save(cfg)

        cfg_loaded = repo.load()
        recovered = AudioEditConfig.from_dict(cfg_loaded["audio_edit"])
        assert recovered == custom

    def test_audio_edit_serializa_em_json_no_disco(self, tmp_path):
        repo = self._repo(tmp_path)
        repo.save(repo.load())  # grava com audio_edit nos defaults

        raw = (tmp_path / "config.json").read_text(encoding="utf-8")
        data = json.loads(raw)
        assert "audio_edit" in data
        assert isinstance(data["audio_edit"]["eq_bands"], list)
        assert len(data["audio_edit"]["eq_bands"]) == 5
