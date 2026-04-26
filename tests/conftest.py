"""
Configuração compartilhada dos testes.
Garante que o diretório raiz do projeto esteja no sys.path e provê
uma instância única do Tk para toda a sessão de testes.

Tkinter/Tcl não suporta múltiplas janelas raiz Tk() criadas e destruídas
no mesmo processo — o intérprete Tcl entra em estado inválido.
A solução é uma única instância CTk (App) de escopo "session" compartilhada
entre todos os módulos de teste.
"""

import os
import sys
from unittest.mock import patch

import pytest

# Raiz do projeto (um nível acima de tests/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(scope="session")
def shared_app():
    """
    Instância única do App para toda a sessão de testes.
    Evita criar/destruir múltiplas janelas Tk no mesmo processo.

    O patch de update_ytdlp/check_auth_status é mantido APENAS durante
    a construção do App. A thread daemon que dispara update_ytdlp captura
    a referência ao Mock no momento do __init__, então é seguro desfazer
    o patch após o App ser construído. Isso libera o nome real de
    update_ytdlp para testes específicos que precisam exercitar a função.
    """
    with patch("baixar_audio.update_ytdlp"), \
         patch("baixar_audio.check_auth_status", return_value=True):
        from app import App
        inst = App()
        inst.withdraw()

    yield inst

    try:
        inst.destroy()
    except Exception:
        pass
