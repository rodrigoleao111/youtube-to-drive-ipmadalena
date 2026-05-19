"""
Verificação e download de atualizações via GitHub Releases API.

Funções públicas:
    check_latest_version(repo, current) -> dict | None
    download_release(url, dest, on_progress)

Usa apenas stdlib (urllib, json) — sem dependências extras.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Callable

GITHUB_API = "https://api.github.com/repos"


def _version_tuple(v: str) -> tuple[int, ...]:
    """Converte 'v3.2.0' ou '3.2.0' em (3, 2, 0) para comparação numérica."""
    return tuple(int(x) for x in v.lstrip("v").split("."))


def check_latest_version(repo: str, current: str) -> dict | None:
    """
    Consulta a release mais recente do repositório GitHub.

    Retorna dict com 'version' (str) e 'download_url' (str) se houver uma
    versão mais nova que `current`, ou None caso contrário.

    Propaga qualquer exceção de rede/HTTP para o chamador lidar (tipicamente
    descartando silenciosamente em uma thread daemon de startup).

    Args:
        repo:    'dono/repositorio', ex: 'rodrigoleao111/youtube-to-drive-ipmadalena'
        current: versão atual no formato 'v3.2.0'
    """
    url = f"{GITHUB_API}/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "IPMadalena"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    tag = data.get("tag_name", "")
    if not tag:
        return None

    if _version_tuple(tag) <= _version_tuple(current):
        return None

    # Localiza o asset .exe do release (IPMadalena_Setup.exe)
    download_url = next(
        (
            a["browser_download_url"]
            for a in data.get("assets", [])
            if a["name"].lower().endswith(".exe")
        ),
        None,
    )
    if not download_url:
        return None

    return {"version": tag, "download_url": download_url}


def download_release(
    url: str,
    dest: str,
    on_progress: Callable[[float], None],
) -> None:
    """
    Faz download de `url` para o arquivo `dest` com progresso.

    Args:
        url:         URL direta do asset (browser_download_url do GitHub).
        dest:        Caminho local de destino para o arquivo baixado.
        on_progress: Callback chamado com float em [0.0, 1.0].
    """

    def reporthook(block_count: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            on_progress(min(block_count * block_size / total_size, 1.0))

    urllib.request.urlretrieve(url, dest, reporthook)
