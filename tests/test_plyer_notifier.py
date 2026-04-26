"""
Testes para infrastructure/notification/plyer_notifier.py.

Cobre o adaptador PlyerNotifier (implementação concreta de INotifier):
  - delegação correta para plyer.notification.notify
  - silenciamento de erros (plyer ausente, backend inacessível, etc.)
  - defaults de app_name e timeout
  - conformidade com o Protocol INotifier
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from domain.ports import INotifier
from infrastructure.notification.plyer_notifier import PlyerNotifier


# ===========================================================================
# Conformidade com o Protocol
# ===========================================================================

class TestProtocolConformance:

    def test_implementa_inotifier(self):
        """PlyerNotifier deve passar isinstance(INotifier)."""
        assert isinstance(PlyerNotifier(), INotifier)


# ===========================================================================
# Delegação correta a plyer.notification.notify
# ===========================================================================

class TestNotifyDelegation:

    def test_chama_plyer_notification_notify(self):
        with patch("plyer.notification.notify") as mock_notify:
            PlyerNotifier().notify(title="Pronto", message="Concluído")
        mock_notify.assert_called_once()

    def test_repassa_title_e_message(self):
        with patch("plyer.notification.notify") as mock_notify:
            PlyerNotifier().notify(title="Tudo OK", message="3 vídeos enviados")
        kwargs = mock_notify.call_args.kwargs
        assert kwargs["title"]   == "Tudo OK"
        assert kwargs["message"] == "3 vídeos enviados"

    def test_app_name_default_e_ipmadalena(self):
        with patch("plyer.notification.notify") as mock_notify:
            PlyerNotifier().notify(title="x", message="y")
        assert mock_notify.call_args.kwargs["app_name"] == "IPMadalena"

    def test_timeout_default_e_8(self):
        with patch("plyer.notification.notify") as mock_notify:
            PlyerNotifier().notify(title="x", message="y")
        assert mock_notify.call_args.kwargs["timeout"] == 8

    def test_app_name_customizavel(self):
        with patch("plyer.notification.notify") as mock_notify:
            PlyerNotifier().notify(
                title="x", message="y", app_name="OutroApp"
            )
        assert mock_notify.call_args.kwargs["app_name"] == "OutroApp"

    def test_timeout_customizavel(self):
        with patch("plyer.notification.notify") as mock_notify:
            PlyerNotifier().notify(title="x", message="y", timeout=30)
        assert mock_notify.call_args.kwargs["timeout"] == 30


# ===========================================================================
# Silenciamento de erros — notificação é best-effort
# ===========================================================================

class TestSilencingErrors:

    def test_silencia_excecao_do_plyer(self):
        """Se plyer.notification.notify lança, não propaga."""
        with patch("plyer.notification.notify",
                   side_effect=Exception("D-Bus indisponível")):
            # Não deve levantar
            PlyerNotifier().notify(title="x", message="y")

    def test_silencia_quando_plyer_nao_instalado(self):
        """Se plyer não está em sys.modules, ImportError é silenciado."""
        saved = sys.modules.pop("plyer", None)
        # Também remove o submódulo se estiver carregado
        saved_notif = sys.modules.pop("plyer.notification", None)
        try:
            with patch.dict(sys.modules, {"plyer": None}):
                # Não deve levantar mesmo com plyer ausente
                PlyerNotifier().notify(title="x", message="y")
        finally:
            if saved is not None:
                sys.modules["plyer"] = saved
            if saved_notif is not None:
                sys.modules["plyer.notification"] = saved_notif

    def test_retorna_none(self):
        """notify() retorna None mesmo em caso de sucesso."""
        with patch("plyer.notification.notify"):
            result = PlyerNotifier().notify(title="x", message="y")
        assert result is None
