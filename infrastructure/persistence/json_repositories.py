"""
Repositórios de persistência baseados em JSON.

Implementam os contratos IHistoryRepository e IConfigRepository do domínio.
Responsabilidade exclusiva: ler e gravar dados em disco; nenhuma lógica de negócio.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Optional


def _noop(*_a, **_kw):
    pass


# ---------------------------------------------------------------------------
# JsonHistoryRepository — IHistoryRepository
# ---------------------------------------------------------------------------

class JsonHistoryRepository:
    """
    Persiste o histórico de datas já processadas em um arquivo JSON.

    Formato do arquivo:
        {
          "19/04/2026": {
            "processado_em": "2026-04-19T14:30:00",
            "videos": ["Título 1", "Título 2"]
          },
          ...
        }

    Implementa o contrato IHistoryRepository (duck typing / Protocol).
    """

    def __init__(self, file_path: str):
        """
        Parameters
        ----------
        file_path:
            Caminho absoluto do arquivo JSON de histórico.
        """
        self._path = file_path

    # -------------------------------------------------------------------
    # IHistoryRepository
    # -------------------------------------------------------------------

    def load(self) -> dict:
        """
        Retorna o dicionário completo de histórico.
        Retorna {} se o arquivo não existir ou estiver corrompido.
        """
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save(self, history: dict) -> None:
        """
        Persiste o dicionário de histórico no arquivo JSON.
        Silencia erros de I/O (não deve interromper o fluxo principal).
        """
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def is_processed(self, date_str: str) -> bool:
        """Retorna True se a data (formato DD/MM/AAAA) já foi processada."""
        return date_str in self.load()

    # -------------------------------------------------------------------
    # API de conveniência (compatibilidade com baixar_audio.py)
    # -------------------------------------------------------------------

    def record(self, date_str: str, video_titles: list) -> None:
        """
        Registra uma data como processada, com a lista de títulos e timestamp.

        Equivale ao save_history() legado de baixar_audio.py.
        """
        history = self.load()
        history[date_str] = {
            "processado_em": datetime.now().isoformat(),
            "videos": list(video_titles),
        }
        self.save(history)


# ---------------------------------------------------------------------------
# JsonConfigRepository — IConfigRepository
# ---------------------------------------------------------------------------

class JsonConfigRepository:
    """
    Persiste as configurações do app (canal YouTube, pasta Drive, etc.) em JSON.

    Implementa o contrato IConfigRepository (duck typing / Protocol).
    """

    def __init__(self, file_path: str, defaults: Optional[dict] = None):
        """
        Parameters
        ----------
        file_path:
            Caminho absoluto do arquivo JSON de configuração.
        defaults:
            Valores padrão para chaves ausentes no arquivo.
        """
        self._path     = file_path
        self._defaults = defaults or {}

    # -------------------------------------------------------------------
    # IConfigRepository
    # -------------------------------------------------------------------

    def load(self) -> dict:
        """
        Retorna o dicionário de configuração com defaults preenchidos.
        Retorna os defaults se o arquivo não existir ou estiver corrompido.
        """
        result = dict(self._defaults)
        if not os.path.exists(self._path):
            return result
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Garante que todas as chaves de default existam
            for k, v in self._defaults.items():
                data.setdefault(k, v)
            return data
        except Exception:
            return result

    def save(self, config: dict) -> None:
        """
        Persiste o dicionário de configuração no arquivo JSON.
        Lança exceção de I/O se a escrita falhar (diferente do histórico,
        onde erros são silenciosos — aqui o usuário espera confirmação).
        """
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default=None):
        """Retorna o valor de uma chave de configuração."""
        return self.load().get(key, default)

    # -------------------------------------------------------------------
    # API de conveniência (compatibilidade com baixar_audio.py)
    # -------------------------------------------------------------------

    def update(self, **kwargs) -> None:
        """
        Atualiza campos individuais sem sobrescrever os demais.

        Equivale ao save_config(channel_url=..., drive_folder_id=...) legado.
        Ignora kwargs cujo valor seja None.
        """
        cfg = self.load()
        for k, v in kwargs.items():
            if v is not None:
                cfg[k] = v.strip() if isinstance(v, str) else v
        self.save(cfg)
