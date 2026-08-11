"""
ZipArchiver — implementação do contrato `IArchiver` (domain.ports).

Empacota os artefatos de um episódio (MP3 + capa.jpg + descricao.txt) em um
único `.zip` que é o que sobe para o Drive.

Stateless: todo o estado vem dos argumentos de `create()`.
"""

from __future__ import annotations

import logging
import os
import zipfile
from typing import Callable, List, Optional


def _noop(*_a, **_kw):
    pass


# Mesmo logger do pipeline de edição — vai para `logs/DD-MM-YYYY.log`.
_log = logging.getLogger("audio_edit")


class ZipArchiver:
    """
    Cria pacotes `.zip` com compressão deflate.

    Implementa o contrato IArchiver (duck typing / Protocol).
    """

    def create(
        self,
        files: List[str],
        dest_path: str,
        *,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Escreve ``dest_path`` com os arquivos informados na raiz do zip.

        O zip é montado em `<dest_path>.tmp` e movido com `os.replace` ao
        final: um zip pela metade nunca chega a existir com o nome final (o
        upload varre a subpasta e enviaria um arquivo corrompido).

        Arquivos inexistentes são ignorados; se nenhum existir, levanta
        ValueError sem criar arquivo nenhum.
        """
        log = on_log if callable(on_log) else _noop

        presentes = [f for f in files if f and os.path.isfile(f)]
        ausentes  = [f for f in files if f not in presentes]

        for f in ausentes:
            _log.warning("zip: arquivo ignorado (nao existe): %s", f)

        if not presentes:
            raise ValueError(
                f"Nenhum arquivo disponível para compactar em {dest_path}."
            )

        tmp_path = dest_path + ".tmp"
        try:
            with zipfile.ZipFile(
                tmp_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                for caminho in presentes:
                    # arcname = basename → zip sem estrutura de diretórios
                    zf.write(caminho, arcname=os.path.basename(caminho))

            os.replace(tmp_path, dest_path)
        except Exception:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise

        tamanho_mb = os.path.getsize(dest_path) / (1024 * 1024)
        nomes = ", ".join(os.path.basename(f) for f in presentes)
        log(
            f"[Pacote] {os.path.basename(dest_path)} "
            f"({tamanho_mb:.1f} MB) — {len(presentes)} arquivo(s): {nomes}"
        )
        _log.info(
            "zip criado: %s (%.2f MB, %d arquivos)",
            dest_path, tamanho_mb, len(presentes),
        )
        return dest_path
