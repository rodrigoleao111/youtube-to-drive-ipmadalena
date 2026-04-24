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
