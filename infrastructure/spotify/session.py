"""
Sessão web do Spotify for Creators — perfil persistente do navegador embutido.

Por que este módulo existe
--------------------------
A publicação de episódios acontece num ``QWebEngineView`` que abre o formulário
do Spotify for Creators. Até a v3.5.0 a view era criada sem perfil explícito e
caía no perfil padrão do Qt — que no Qt 6 é *off-the-record*
(``isOffTheRecord() == True``, ``NoPersistentCookies``, medido no Qt 6.11).
Consequência: o login era descartado ao fechar a janela e o usuário precisava
autenticar de novo em CADA publicação.

Um perfil NOMEADO com ``persistentStoragePath`` grava os cookies em disco
(arquivo ``Cookies``, SQLite, com ``is_persistent=1``) e a sessão sobrevive ao
fechamento do app.

Como o login é detectado
------------------------
Sem inspecionar cookies. O nome do cookie de sessão é detalhe interno da
Spotify — se ele mudar, o app passaria a achar que ninguém está logado, sem
nenhum sinal.

A classificação vem da URL (``classify_url``), mas ela **sozinha não prova
sessão**. Três medições ao vivo delimitam o que é confiável:

1. A área autenticada do Creators exige login: deslogado, o site manda para
   ``accounts.spotify.com/<idioma>/login?...``. Esse veredito negativo é
   conclusivo — se o Spotify pediu credenciais, não há sessão. (Ainda assim ela
   não serve de porta de entrada; ver ``LOGIN_URL_BASE``.)
2. O desvio é feito pelo próprio site, não por um 302. Então ``urlChanged`` e o
   primeiro ``loadFinished`` chegam com a URL interna ainda no lugar: medido,
   deslogado, os dois entregam ``logged_in`` antes de o desvio acontecer.
3. Pior: com o banner de consentimento de cookies na tela, a página **fica** na
   URL interna indefinidamente (medido: 20 s parada em ``/pod/dashboard``,
   exibindo "We and our partners use cookies..."). Não existe tempo de espera
   que transforme "continuo na URL interna" em prova de sessão.

Por isso o veredito positivo exige uma **transição observada**: quem decide é a
janela de login, e só depois de ter visto a tela de credenciais e a página sair
dela. É o que ``classify`` serve — o veredito cru, sem gravar nada; gravar é
decisão de quem tem o contexto da navegação.

Uma armadilha adicional na classificação: a RAIZ ``creators.spotify.com/``
carrega normalmente mesmo deslogado (é a página de marketing, "Make your show
the next big thing"). Por isso só conta como interna uma URL com path além de
"/".

O estado fica em ``spotify.logged_in`` (config.json) para que a UI saiba o
estado na abertura do app sem tocar a rede. Ele pode ficar desatualizado quando
o cookie expira do lado da Spotify — a janela de publicação classifica a página
que recebeu e corrige o flag ao ver a tela de login, então a divergência se
resolve na primeira tentativa de publicar.
"""

from __future__ import annotations

import os
import re
import shutil
from urllib.parse import quote, urlsplit

from domain.ports import SPOTIFY_LOGGED_IN, SPOTIFY_LOGGED_OUT, SPOTIFY_UNKNOWN

# ---------------------------------------------------------------------------
# URLs e vereditos
# ---------------------------------------------------------------------------

#: Entrada do login: a tela de credenciais, direto.
#:
#: NÃO use a área autenticada do Creators como porta de entrada. Deslogado, o
#: roteador dela falha a autenticação silenciosa e **não** segue para o login —
#: a página fica carregando indefinidamente. Reproduzido a partir do log de um
#: usuário e confirmado aqui: console com ``[AuthRouter] auth error
#: {"error": "login_required"}`` + ``requestStorageAccess: Permission denied``,
#: 25 s parado em ``/pod/dashboard`` com a página em branco e, depois, só o
#: banner de consentimento de cookies. A tela de credenciais, ao contrário,
#: renderiza de imediato e fica estável.
LOGIN_URL_BASE = "https://accounts.spotify.com/login"

#: Para onde o Spotify deve voltar depois do login bem-sucedido. É o que produz
#: a transição ``logged_out → logged_in`` que a janela de login exige como prova.
CREATORS_HOME_URL = "https://creators.spotify.com/pod/dashboard"

#: Formulário de novo episódio (o ``{show_id}`` vem da configuração do usuário).
WIZARD_URL_TEMPLATE = "https://creators.spotify.com/pod/show/{show_id}/episode/wizard"

#: Hosts onde a Spotify pede credenciais.
LOGIN_HOSTS = ("accounts.spotify.com", "login.spotify.com")

#: Hosts da área autenticada do Creators (``podcasters`` é o domínio antigo,
#: que ainda redireciona para ``creators``).
APP_HOSTS = ("creators.spotify.com", "podcasters.spotify.com")

# Vereditos: o vocabulário vive no domínio (contrato compartilhado com a UI);
# aqui ficam apenas apelidos curtos.
LOGGED_IN = SPOTIFY_LOGGED_IN
LOGGED_OUT = SPOTIFY_LOGGED_OUT
UNKNOWN = SPOTIFY_UNKNOWN

#: Nome do perfil do QtWebEngine. Precisa ser estável entre execuções — é ele
#: que amarra o perfil ao diretório de storage.
PROFILE_NAME = "ipmadalena_spotify"

#: Idioma pedido ao Spotify, no formato do cabeçalho HTTP ``Accept-Language``.
#:
#: Por que fixar isto: o ``QWebEngineProfile`` nasce com ``httpAcceptLanguage``
#: **vazio** (medido aqui no Qt 6.11 — string vazia, não o locale do Windows),
#: então o navegador embutido não pedia idioma nenhum e o Spotify for Creators
#: respondia em inglês. Medição na raiz pública do Creators, mesmo perfil e
#: mesmo user agent, só variando este cabeçalho:
#:
#: - vazio: "Make your show the next big thing"
#: - ``pt-BR``: "Faça seu programa se destacar"
#:
#: O ``en`` no fim é fallback: se uma tela não tiver tradução, ela aparece em
#: inglês em vez de quebrar. A tela de login já vinha em português por conta
#: própria (o Spotify redireciona para ``accounts.spotify.com/pt-BR/login``),
#: então quem dependia disto era só a área do Creators.
ACCEPT_LANGUAGE = "pt-BR,pt;q=0.9,en;q=0.8"


def classify_url(url: str) -> str:
    """
    Diz o que uma URL do fluxo do Spotify revela sobre a sessão.

    Retorna ``LOGGED_OUT`` para as telas de credencial, ``LOGGED_IN`` para as
    páginas internas do Creators e ``UNKNOWN`` para qualquer outra coisa
    (inclusive a raiz de marketing e URLs vazias/inválidas).
    """
    if not url or not isinstance(url, str):
        return UNKNOWN
    try:
        parts = urlsplit(url.strip())
    except Exception:
        return UNKNOWN

    host = (parts.hostname or "").lower()
    path = parts.path or ""

    if host in LOGIN_HOSTS:
        return LOGGED_OUT
    if host in APP_HOSTS:
        # /login e /logout no próprio domínio do Creators também são telas
        # de credencial — não valem como sessão ativa.
        if re.search(r"/log(in|out)\b", path):
            return LOGGED_OUT
        # A raiz é a landing page pública; só um path interno prova sessão.
        if path.strip("/"):
            return LOGGED_IN
    return UNKNOWN


def login_url() -> str:
    """
    URL de entrada do login, já pedindo o retorno ao Creators.

    O ``continue`` é o mesmo mecanismo que o próprio site do Creators usa. Se a
    Spotify ignorá-lo, o usuário termina o login noutra página do spotify.com e
    a transição não acontece — para isso existe o botão "Concluí o login".
    """
    return f"{LOGIN_URL_BASE}?continue={quote(CREATORS_HOME_URL, safe='')}"


def wizard_url(show_id: str) -> str:
    """URL do formulário de novo episódio para o show informado."""
    return WIZARD_URL_TEMPLATE.format(show_id=quote((show_id or "").strip(), safe=""))


def desktop_user_agent(default_ua: str) -> str:
    """
    Remove o token ``QtWebEngine/<versão>`` do user agent padrão.

    O que sobra é um user agent de Chrome legítimo, na mesma versão do Chromium
    embarcado — sem o marcador que anuncia "navegador embutido" para os
    provedores de login. Derivar do padrão (em vez de fixar uma string) evita
    que o UA envelheça a cada atualização do Qt.
    """
    if not default_ua:
        return default_ua
    return re.sub(r"\s*QtWebEngine/\S+", "", default_ua).strip()


# ---------------------------------------------------------------------------
# Sessão
# ---------------------------------------------------------------------------

class SpotifyWebSession:
    """
    Dona do perfil persistente do navegador embutido e do estado de login.

    Implementa ``ISpotifySession`` (duck typing / Protocol).

    Uma instância por execução do app: dois ``QWebEngineProfile`` apontando para
    o mesmo diretório disputariam o banco de cookies.
    """

    def __init__(
        self,
        *,
        storage_dir: str,
        config_repo=None,
    ):
        """
        Parameters
        ----------
        storage_dir:
            Diretório do perfil (cookies, cache, histórico). Fica dentro de
            ``credentials/`` para acompanhar o token do Drive — e, como aquela
            pasta, sobrevive à desinstalação.
        config_repo:
            Repositório de configuração (IConfigRepository) onde o flag
            ``spotify.logged_in`` é persistido. Sem ele a sessão funciona, mas
            o estado não sobrevive ao fechamento do app.
        """
        self._storage_dir = storage_dir
        self._config_repo = config_repo
        self._profile = None
        self._wipe_marker = storage_dir.rstrip("\\/") + ".wipe"
        self._apply_pending_wipe()

    # -------------------------------------------------------------------
    # Estado de login
    # -------------------------------------------------------------------

    def is_logged_in(self) -> bool:
        """
        Diz se há sessão do Spotify guardada.

        Exige as duas coisas: o flag no config.json E o diretório do perfil em
        disco. Se o usuário apagou ``credentials/``, o flag estaria mentindo.
        """
        if not os.path.isdir(self._storage_dir):
            return False
        return bool(self._read_flag())

    def mark_logged_in(self, value: bool) -> None:
        """Persiste o estado de login em ``spotify.logged_in``."""
        if self._config_repo is None:
            return
        try:
            cfg = self._config_repo.load()
            sp = dict(cfg.get("spotify") or {})
            sp["logged_in"] = bool(value)
            self._config_repo.update(spotify=sp)
        except Exception:
            # Persistir o estado é conveniência: perder o flag faz a UI pedir
            # login de novo, o que é chato mas não quebra nada.
            pass

    def classify(self, url: str) -> str:
        """
        Devolve o veredito cru de uma URL, SEM gravar nada.

        Deliberadamente não persiste: uma URL isolada não prova sessão (ver o
        docstring do módulo). Quem tem o contexto da navegação — a janela de
        login, que sabe se a tela de credenciais já apareceu — é que decide
        chamar ``mark_logged_in``.
        """
        return classify_url(url)

    def _read_flag(self) -> bool:
        if self._config_repo is None:
            return False
        try:
            cfg = self._config_repo.load()
            return bool((cfg.get("spotify") or {}).get("logged_in", False))
        except Exception:
            return False

    # -------------------------------------------------------------------
    # Perfil do QtWebEngine
    # -------------------------------------------------------------------

    def profile(self):
        """
        Retorna o ``QWebEngineProfile`` persistente, criando-o na primeira vez.

        Criação tardia de propósito: instanciar um perfil inicializa parte do
        QtWebEngine, e o app não deve pagar esse custo em toda abertura — só
        quando o usuário for de fato ao Spotify.
        """
        if self._profile is None:
            self._profile = self._make_profile()
        return self._profile

    def _make_profile(self):
        from PyQt6.QtWebEngineCore import QWebEngineProfile

        os.makedirs(self._storage_dir, exist_ok=True)
        prof = QWebEngineProfile(PROFILE_NAME)
        prof.setPersistentStoragePath(self._storage_dir)
        prof.setCachePath(os.path.join(self._storage_dir, "cache"))
        prof.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        prof.setHttpUserAgent(desktop_user_agent(prof.httpUserAgent()))
        prof.setHttpAcceptLanguage(ACCEPT_LANGUAGE)
        return prof

    # -------------------------------------------------------------------
    # Logout
    # -------------------------------------------------------------------

    def logout(self) -> None:
        """
        Encerra a sessão local.

        Nenhuma das duas etapas basta sozinha, então fazemos as duas:

        - ``deleteAllCookies()`` só tem efeito se o perfil já carregou uma
          página nesta execução (o contexto de rede do Chromium nasce sob
          demanda — sem isso a chamada é silenciosamente ignorada);
        - apagar os arquivos do perfil só funciona se o Chromium ainda não os
          abriu: no Windows o banco de cookies fica travado enquanto o perfil
          vive. Quando está travado, deixamos um marcador e a limpeza acontece
          na próxima abertura do app, em ``_apply_pending_wipe``.

        O flag é zerado em qualquer caso — é ele que a UI consulta para liberar
        a publicação.
        """
        self.mark_logged_in(False)

        if self._profile is None:
            # Perfil nunca instanciado nesta execução: ninguém segura os
            # arquivos, dá para apagar agora e o logout é definitivo.
            shutil.rmtree(self._storage_dir, ignore_errors=True)
            return

        try:
            self._profile.cookieStore().deleteAllCookies()
        except Exception:
            pass
        self._request_wipe()

    def _request_wipe(self) -> None:
        """Marca o perfil para ser apagado na próxima abertura do app."""
        try:
            os.makedirs(os.path.dirname(self._wipe_marker) or ".", exist_ok=True)
            with open(self._wipe_marker, "w", encoding="utf-8") as fh:
                fh.write("logout pendente\n")
        except Exception:
            pass

    def _apply_pending_wipe(self) -> None:
        """Executa a limpeza deixada por um ``logout()`` da execução anterior."""
        if not os.path.exists(self._wipe_marker):
            return
        shutil.rmtree(self._storage_dir, ignore_errors=True)
        try:
            os.remove(self._wipe_marker)
        except Exception:
            pass

    # -------------------------------------------------------------------
    # Introspecção (usada pela UI e pelos testes)
    # -------------------------------------------------------------------

    @property
    def storage_dir(self) -> str:
        return self._storage_dir

    def login_url(self) -> str:
        return login_url()

    def wizard_url(self, show_id: str) -> str:
        return wizard_url(show_id)
