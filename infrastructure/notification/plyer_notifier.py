"""
Adaptador de notificações desktop usando a biblioteca plyer.

Implementa o contrato INotifier (duck typing / Protocol).
Notificações são best-effort: qualquer falha (plyer não instalado, sem DBus
no Linux, sem permissão no Windows, etc.) é silenciada — a operação principal
do app não pode ser interrompida por uma notificação que não pôde ser exibida.
"""

from __future__ import annotations


class PlyerNotifier:
    """
    Notificador desktop que usa `plyer.notification.notify`.

    O import de `plyer` é lazy (dentro de `notify()`) por dois motivos:
      1. plyer é dependência opcional — em ambientes onde não está instalado,
         não queremos falhar no import do módulo principal.
      2. Em testes, permite mockar `plyer.notification.notify` ou remover
         o módulo de `sys.modules` sem precisar reimportar este adaptador.
    """

    def notify(
        self,
        title: str,
        message: str,
        *,
        app_name: str = "IPMadalena",
        timeout: int = 8,
    ) -> None:
        """
        Exibe uma notificação desktop.

        Falhas (plyer ausente, backend inacessível, sistema sem suporte) são
        silenciadas — o caller não precisa se preocupar com tratamento.

        Parameters
        ----------
        title:
            Título da notificação (linha em destaque).
        message:
            Corpo da mensagem.
        app_name:
            Nome do aplicativo exibido pela bandeja (default "IPMadalena").
        timeout:
            Tempo em segundos para a notificação desaparecer (default 8).
        """
        try:
            from plyer import notification
            notification.notify(
                title    = title,
                message  = message,
                app_name = app_name,
                timeout  = timeout,
            )
        except Exception:
            # plyer é opcional; ignorar qualquer falha (import, backend, etc.)
            pass
