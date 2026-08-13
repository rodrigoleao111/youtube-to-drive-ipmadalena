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

from domain.entities import AudioEditConfig, AudioFile, ProcessingResult, Segment, Video


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
# Busca de um vídeo específico (por link)
# ---------------------------------------------------------------------------

@runtime_checkable
class IVideoFetcher(Protocol):
    """
    Obtém os metadados de UM vídeo a partir do seu link.

    Complementa IVideoSource: em vez de varrer o canal por data, resolve
    diretamente o vídeo informado pelo usuário. Usado pelo modo "link" da
    tela de processamento, que pula a etapa de busca.

    Implementações: YtDlpVideoSource (infraestrutura/youtube)
    """

    def fetch_video(
        self,
        url: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> Video:
        """
        Retorna o vídeo correspondente ao link informado.

        Parameters
        ----------
        url:
            Link do vídeo no YouTube (watch, youtu.be, live, shorts, embed)
            ou o próprio ID de 11 caracteres.
        cancel_event:
            threading.Event opcional — lança OperacaoCancelada se sinalizado.
        on_log:
            Callback chamado com mensagens de log (textos informativos).
        on_status:
            Callback chamado com mensagens de status (texto exibido na UI).

        Returns
        -------
        Video
            Vídeo com ``id``, ``title`` e ``upload_date`` preenchidos.
            ``upload_date`` pode vir vazio quando o provedor não informa.

        Raises
        ------
        VideoNaoEncontrado
            Se o link for inválido ou o vídeo não puder ser resolvido.
        """
        ...


# ---------------------------------------------------------------------------
# Fonte de capítulos de vídeo
# ---------------------------------------------------------------------------

@runtime_checkable
class IChapterSource(Protocol):
    """
    Extrai os capítulos de um vídeo do YouTube.

    Implementações: YtDlpVideoSource (infraestrutura/youtube)
    """

    def get_chapters(
        self,
        video_id: str,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> List[dict]:
        """
        Retorna os capítulos do vídeo como lista de dicts.

        Cada dict tem as chaves:
            ``title`` (str), ``start`` (str HH:MM:SS), ``end`` (str HH:MM:SS)

        Retorna lista vazia se o vídeo não tiver capítulos.

        Parameters
        ----------
        video_id:
            ID do vídeo no YouTube.
        cancel_event:
            threading.Event opcional — lança OperacaoCancelada se sinalizado.
        on_log:
            Callback chamado com mensagens de log.
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
# Compactador de arquivos
# ---------------------------------------------------------------------------

@runtime_checkable
class IArchiver(Protocol):
    """
    Empacota vários arquivos locais em um único arquivo compactado.

    Usado antes do upload: o episódio sobe para a nuvem como um pacote único
    (áudio + capa + descrição) em vez de arquivos soltos.

    Implementações: ZipArchiver (infraestrutura/archive)
    """

    def create(
        self,
        files: List[str],
        dest_path: str,
        *,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Cria o pacote em ``dest_path`` com os arquivos informados.

        Os arquivos entram na raiz do pacote (sem estrutura de diretórios) e
        na ordem recebida. Caminhos inexistentes são ignorados.

        Parameters
        ----------
        files:
            Caminhos absolutos dos arquivos a incluir.
        dest_path:
            Caminho do pacote a criar (sobrescrito se já existir).
        on_log:
            Callback chamado com mensagens de log.

        Returns
        -------
        str
            O próprio ``dest_path``.

        Raises
        ------
        ValueError
            Se nenhum dos arquivos informados existir.
        OSError
            Se a escrita do pacote falhar.
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


# ---------------------------------------------------------------------------
# Sessão do Spotify for Creators
# ---------------------------------------------------------------------------

# Vocabulário dos vereditos de ``ISpotifySession.observe_url``. Fica no domínio
# porque faz parte do contrato: tanto o adaptador que classifica quanto a UI que
# reage precisam concordar sobre os nomes.
SPOTIFY_LOGGED_IN  = "logged_in"
SPOTIFY_LOGGED_OUT = "logged_out"
SPOTIFY_UNKNOWN    = "unknown"


@runtime_checkable
class ISpotifySession(Protocol):
    """
    Guarda a sessão do usuário no Spotify for Creators entre execuções.

    Implementações: SpotifyWebSession (infraestrutura/spotify)

    A publicação do episódio é feita pelo próprio usuário num navegador
    embutido, então "estar logado" é uma propriedade do navegador — não há
    token que o domínio possa manipular. Este contrato expõe apenas o que a
    apresentação precisa saber (está logado? deslogue; qual perfil usar), sem
    revelar como a sessão é guardada.
    """

    def is_logged_in(self) -> bool:
        """Retorna True se existe sessão guardada do Spotify."""
        ...

    def mark_logged_in(self, value: bool) -> None:
        """Registra o estado de login (persistido entre execuções)."""
        ...

    def classify(self, url: str) -> str:
        """
        Veredito cru de uma URL do fluxo do Spotify, sem gravar nada.

        Retorna 'logged_in', 'logged_out' ou 'unknown'. O negativo é conclusivo;
        o positivo não prova sessão por si (ver a implementação), então persistir
        é decisão de quem acompanha a navegação.
        """
        ...

    def logout(self) -> None:
        """Descarta a sessão guardada."""
        ...

    def profile(self):
        """
        Perfil do navegador embutido a ser usado pelas janelas do Spotify.

        Objeto opaco para o domínio: quem o recebe apenas repassa à view. É o
        que faz o login sobreviver ao fechamento da janela.
        """
        ...

    def login_url(self) -> str:
        """URL de entrada do login (a tela de credenciais)."""
        ...

    def wizard_url(self, show_id: str) -> str:
        """URL do formulário de novo episódio do show informado."""
        ...


# ---------------------------------------------------------------------------
# Editor de áudio (pós-processamento: vinhetas, fade, EQ, denoise)
# ---------------------------------------------------------------------------

@runtime_checkable
class IAudioEditor(Protocol):
    """
    Aplica filtros de pós-processamento em um AudioFile baixado, gerando o
    arquivo final pronto para upload.

    Pipeline (na ordem): redução de ruído → equalização → fade in/out →
    concatenação com vinhetas. Quando `config.has_any_filter_enabled` é
    False, o editor retorna o AudioFile de entrada sem modificação (no-op).

    Implementações: FfmpegAudioEditor (infraestrutura/audio) — futuro PR
    """

    def process(
        self,
        audio: AudioFile,
        config: AudioEditConfig,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> AudioFile:
        """
        Processa o áudio aplicando o pipeline configurado.

        Parameters
        ----------
        audio:
            AudioFile de entrada (caminho local de um MP3 já baixado).
        config:
            Configuração do pipeline (vinhetas, fade, EQ, denoise).
        cancel_event:
            threading.Event opcional — lança OperacaoCancelada se sinalizado.
        on_log:
            Callback chamado uma vez por etapa do pipeline (ex.:
            "Aplicando equalização (5 bandas)...").
        on_progress:
            Callback chamado com progresso normalizado em [0.0, 1.0].

        Returns
        -------
        AudioFile
            Arquivo final. Substitui o original no caminho de entrada
            (mesmo `path` do AudioFile recebido).
        """
        ...
