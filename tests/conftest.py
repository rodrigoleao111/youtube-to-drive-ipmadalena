"""
Configuração compartilhada dos testes.
Garante que o diretório raiz do projeto esteja no sys.path e provê
uma instância única do App (QMainWindow) para toda a sessão de testes.

PyQt6 exige que exista exatamente um QApplication antes de qualquer QWidget
ser criado. A instância é criada aqui, em escopo de módulo, antes de qualquer
fixture ou importação de app.py. A instância do App é compartilhada entre
todos os módulos de teste para evitar múltiplas instâncias de QMainWindow.
"""

import os
import sys
from unittest.mock import patch

import pytest

# Raiz do projeto (um nível acima de tests/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# QApplication deve existir antes de qualquer QWidget — criado em escopo global.
# AA_ShareOpenGLContexts deve ser setado ANTES de criar o QApplication para que
# QWebEngineWidgets possa ser importado em qualquer momento (test_player_window_qt).
from PyQt6.QtCore import Qt as _Qt
from PyQt6.QtWidgets import QApplication as _QApplication
_QApplication.setAttribute(_Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
_qapp = _QApplication.instance() or _QApplication(sys.argv)


@pytest.fixture(scope="session")
def shared_app():
    """
    Instância única do App para toda a sessão de testes.

    O patch de update_ytdlp/check_auth_status é mantido APENAS durante
    a construção do App. A thread daemon que dispara update_ytdlp captura
    a referência ao Mock no momento do __init__, então é seguro desfazer
    o patch após o App ser construído. Isso libera o nome real de
    update_ytdlp para testes específicos que precisam exercitar a função.
    """
    with patch("baixar_audio.update_ytdlp"), \
         patch("baixar_audio.check_auth_status", return_value=True):
        from app import App
        with patch.object(App, "_check_update_worker"):
            inst = App()
            inst.hide()

    yield inst

    try:
        inst.close()
    except Exception:
        pass
