"""
Portas (interfaces) do domínio — contratos que as camadas externas devem implementar.

Usa typing.Protocol (structural subtyping) para que as implementações não
precisem herdar explicitamente da interface, seguindo o princípio da
inversão de dependência (DIP) sem acoplamento de herança.

Convenções:
  - Cada Protocol define UMA responsabilidade (SRP)
  - Nomes começam com "I" (de Interface) para distinguir de implementações
  - Parâmetros e retornos usam apenas tipos do domínio ou stdlib
"""

from __future__ import annotations

from typing import Callable, List, Optional, Protocol, runtime_checkable

from domain.entities import AudioFile, ProcessingResult, Segment, Video


# ---------------------------------------------------------------------------
# Fonte de vídeos (YouTube ou outro provedor)
# ---------------------------------------------------------------------------

@runtime_checkable
class IVideoSource(Protocol):
    """
    Consulta o provedor de vídeos e lista os disponíveis para uma data.

    Implementações: YtDlpVideoSource (infraestrutura/youtube)
    """

    def list_videos(
        self,
        date_str: str,
        channel_url: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> List[Video]:
        """
        Retorna a lista de vídeos publicados na data informada.

        Parameters
        ----------
        date_str:
            Data no formato DD/MM/AAAA.
        channel_url:
            URL do canal no YouTube.
        cancel_event:
            threading.Event opcional — lança OperacaoCancelada se sinalizado.
        on_log:
            Callback chamado com mensagens de log (textos informativos).
        on_status:
            Callback chamado com mensagens de status (texto exibido na UI).

        Returns
        -------
        List[Video]
            Lista ordenada cronologicamente; pode ser vazia.
        """
        ...


# ---------------------------------------------------------------------------
# Downloader de áudio
# ---------------------------------------------------------------------------

@runtime_checkable
class IAudioDownloader(Protocol):
    """
    Baixa o áudio de segmentos de vídeo e retorna os arquivos resultantes.

    Implementações: YtDlpAudioDownloader (infraestrutura/youtube)
    """

    def download(
        self,
        segments: List[Segment],
        output_dir: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> List[AudioFile]:
        """
        Baixa os segmentos e retorna a lista de arquivos de áudio gerados.

        Parameters
        ----------
        segments:
            Segmentos a baixar (cada um pode ser trecho ou vídeo completo).
        output_dir:
            Pasta de destino dos arquivos MP3.
        cancel_event:
            threading.Event opcional.
        on_log / on_status / on_progress:
            Callbacks de feedback para a UI.

        Returns
        -------
        List[AudioFile]
            Um AudioFile por segmento processado com sucesso.
        """
        ...


# ---------------------------------------------------------------------------
# Armazenamento na nuvem (Google Drive ou similar)
# ---------------------------------------------------------------------------

@runtime_checkable
class ICloudStorage(Protocol):
    """
    Faz upload de arquivos de áudio para a nuvem e organiza por pasta.

    Implementações: GoogleDriveStorage (infraestrutura/drive) — futuro
    """

    def upload(
        self,
        files: List[AudioFile],
        date_str: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> ProcessingResult:
        """
        Envia os arquivos para a nuvem.

        Verifica duplicatas antes de enviar; arquivos já existentes
        são contabilizados em ProcessingResult.skipped_files.
        """
        ...


# ---------------------------------------------------------------------------
# Repositório de histórico
# ---------------------------------------------------------------------------

@runtime_checkable
class IHistoryRepository(Protocol):
    """
    Persiste e consulta o histórico de datas já processadas.

    Implementações: JsonHistoryRepository (infraestrutura/persistence) — futuro
    """

    def load(self) -> dict:
        """Retorna o dicionário de histórico (date_str → metadados)."""
        ...

    def save(self, history: dict) -> None:
        """Persiste o dicionário de histórico."""
        ...

    def is_processed(self, date_str: str) -> bool:
        """Retorna True se a data já foi processada com sucesso."""
        ...


# ---------------------------------------------------------------------------
# Repositório de configuração
# ---------------------------------------------------------------------------

@runtime_checkable
class IConfigRepository(Protocol):
    """
    Persiste e expõe as configurações do app (canal, pasta Drive, etc.).

    Implementações: JsonConfigRepository (infraestrutura/persistence) — futuro
    """

    def load(self) -> dict:
        """Retorna o dicionário de configuração."""
        ...

    def save(self, config: dict) -> None:
        """Persiste o dicionário de configuração."""
        ...

    def get(self, key: str, default=None):
        """Retorna o valor de uma chave de configuração."""
        ...


# ---------------------------------------------------------------------------
# Notificador (plyer ou outro)
# ---------------------------------------------------------------------------

@runtime_checkable
class INotifier(Protocol):
    """
    Envia notificações ao usuário fora da interface principal.

    Implementações: PlyerNotifier (infraestrutura/notification) — futuro
    """

    def notify(
        self,
        title: str,
        message: str,
        *,
        app_name: str = "IPMadalena",
        timeout: int = 8,
    ) -> None:
        """Exibe uma notificação desktop (best-effort; ignora erros silenciosamente)."""
        ...
