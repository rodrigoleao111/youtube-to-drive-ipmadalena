"""
Testes de infrastructure/spotify/session.py.

Cobre:
  - classify_url: o veredito de login lido da URL (inclusive a armadilha da
    página de marketing na raiz do Creators)
  - wizard_url / desktop_user_agent
  - SpotifyWebSession: leitura e persistência do estado, observe_url,
    logout (imediato e postergado) e a limpeza pendente na abertura

Estratégia: nenhum teste toca Qt ou rede. O perfil do QtWebEngine é criado
apenas em `profile()`, que não é exercitado aqui — os testes que precisam de um
perfil de verdade vivem em test_app.py.
"""

import os
from urllib.parse import quote

import pytest

from domain.ports import (
    ISpotifySession,
    SPOTIFY_LOGGED_IN,
    SPOTIFY_LOGGED_OUT,
    SPOTIFY_UNKNOWN,
)
from infrastructure.spotify.session import (
    ACCEPT_LANGUAGE,
    CREATORS_HOME_URL,
    LOGIN_URL_BASE,
    PROFILE_NAME,
    SpotifyWebSession,
    classify_url,
    desktop_user_agent,
    login_url,
    wizard_url,
)


class _FakeConfigRepo:
    """Repositório de configuração em memória (implementa IConfigRepository)."""

    def __init__(self, data=None):
        self.data = dict(data or {})
        self.saves = 0

    def load(self) -> dict:
        return dict(self.data)

    def save(self, config: dict) -> None:
        self.data = dict(config)
        self.saves += 1

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def update(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if v is not None:
                self.data[k] = v
        self.saves += 1


def _sessao(tmp_path, *, repo=None, criar_dir=True):
    storage = os.path.join(str(tmp_path), "credentials", "spotify")
    if criar_dir:
        os.makedirs(storage, exist_ok=True)
    return SpotifyWebSession(storage_dir=storage, config_repo=repo)


# ---------------------------------------------------------------------------
# classify_url
# ---------------------------------------------------------------------------

class TestClassifyUrl:
    def test_accounts_spotify_e_logged_out(self):
        url = (
            "https://accounts.spotify.com/pt-BR/login?continue="
            "https%3A%2F%2Faccounts.spotify.com%2Foauth2%2Fv2%2Fauth"
        )
        assert classify_url(url) == SPOTIFY_LOGGED_OUT

    def test_login_spotify_e_logged_out(self):
        assert classify_url("https://login.spotify.com/") == SPOTIFY_LOGGED_OUT

    def test_pagina_interna_do_creators_e_logged_in(self):
        assert classify_url(
            "https://creators.spotify.com/pod/dashboard"
        ) == SPOTIFY_LOGGED_IN

    def test_wizard_de_episodio_e_logged_in(self):
        assert classify_url(
            "https://creators.spotify.com/pod/show/abc123/episode/wizard"
        ) == SPOTIFY_LOGGED_IN

    def test_dominio_antigo_podcasters_tambem_conta(self):
        assert classify_url(
            "https://podcasters.spotify.com/pod/dashboard"
        ) == SPOTIFY_LOGGED_IN

    def test_raiz_do_creators_nao_prova_login(self):
        """
        Regressão: a raiz do Creators é a landing page de marketing e carrega
        normalmente mesmo deslogado (verificado ao vivo). Tratá-la como sessão
        válida daria falso positivo e liberaria a publicação sem login.
        """
        assert classify_url("https://creators.spotify.com/") == SPOTIFY_UNKNOWN
        assert classify_url("https://creators.spotify.com") == SPOTIFY_UNKNOWN

    def test_login_no_dominio_do_creators_e_logged_out(self):
        assert classify_url(
            "https://creators.spotify.com/login"
        ) == SPOTIFY_LOGGED_OUT

    def test_logout_no_dominio_do_creators_e_logged_out(self):
        assert classify_url(
            "https://creators.spotify.com/logout"
        ) == SPOTIFY_LOGGED_OUT

    def test_host_maiusculo_e_normalizado(self):
        assert classify_url(
            "https://Creators.Spotify.COM/pod/dashboard"
        ) == SPOTIFY_LOGGED_IN

    def test_dominio_de_terceiro_e_unknown(self):
        assert classify_url("https://www.google.com/") == SPOTIFY_UNKNOWN

    def test_dominio_parecido_nao_conta(self):
        """Evita casar por sufixo: 'creators.spotify.com.evil.com' não é a Spotify."""
        assert classify_url(
            "https://creators.spotify.com.evil.com/pod/dashboard"
        ) == SPOTIFY_UNKNOWN

    @pytest.mark.parametrize("valor", ["", None, "   ", "não é url", 42, []])
    def test_entradas_invalidas_sao_unknown(self, valor):
        assert classify_url(valor) == SPOTIFY_UNKNOWN

    def test_query_string_nao_confunde(self):
        assert classify_url(
            "https://creators.spotify.com/pod/dashboard?foo=/login"
        ) == SPOTIFY_LOGGED_IN


# ---------------------------------------------------------------------------
# wizard_url / desktop_user_agent
# ---------------------------------------------------------------------------

class TestWizardUrl:
    def test_monta_url_do_show(self):
        assert wizard_url("abc123") == (
            "https://creators.spotify.com/pod/show/abc123/episode/wizard"
        )

    def test_remove_espacos_ao_redor(self):
        assert wizard_url("  abc123  ") == (
            "https://creators.spotify.com/pod/show/abc123/episode/wizard"
        )

    def test_escapa_caracteres_de_path(self):
        """Um show_id colado errado não pode escapar do path da URL."""
        assert "/pod/show/a%2Fb/episode/wizard" in wizard_url("a/b")

    def test_show_id_vazio_nao_quebra(self):
        assert wizard_url("") == (
            "https://creators.spotify.com/pod/show//episode/wizard"
        )

    def test_wizard_url_e_classificada_como_logada(self):
        assert classify_url(wizard_url("abc")) == SPOTIFY_LOGGED_IN


class TestLoginUrl:
    """
    A entrada do login é a tela de credenciais, não a área autenticada.

    Regressão de campo: abrir `/pod/dashboard` deslogado deixa a janela
    carregando para sempre — o roteador do Creators falha a autenticação
    silenciosa (`[AuthRouter] auth error login_required`) e não segue para o
    login. A tela de credenciais renderiza de imediato.
    """

    def test_aponta_para_a_tela_de_credenciais(self):
        assert login_url().startswith(LOGIN_URL_BASE)
        assert "accounts.spotify.com" in login_url()

    def test_nao_entra_pela_area_autenticada(self):
        assert not login_url().startswith("https://creators.spotify.com")

    def test_e_classificada_como_deslogada(self):
        """Assim a janela registra `_viu_login` já na abertura."""
        assert classify_url(login_url()) == SPOTIFY_LOGGED_OUT

    def test_pede_retorno_ao_creators(self):
        """O `continue` é o que produz a transição que serve de prova."""
        assert quote(CREATORS_HOME_URL, safe="") in login_url()

    def test_o_destino_de_retorno_e_area_autenticada(self):
        assert classify_url(CREATORS_HOME_URL) == SPOTIFY_LOGGED_IN


class TestDesktopUserAgent:
    #: UA padrão real do Qt 6.11 (medido).
    UA_QT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) QtWebEngine/6.11.1 Chrome/140.0.0.0 Safari/537.36"
    )

    def test_remove_o_token_qtwebengine(self):
        assert "QtWebEngine" not in desktop_user_agent(self.UA_QT)

    def test_preserva_o_resto_do_user_agent(self):
        ua = desktop_user_agent(self.UA_QT)
        assert ua == (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
        )

    def test_e_idempotente(self):
        uma = desktop_user_agent(self.UA_QT)
        assert desktop_user_agent(uma) == uma

    def test_string_vazia_nao_quebra(self):
        assert desktop_user_agent("") == ""


# ---------------------------------------------------------------------------
# Estado de login
# ---------------------------------------------------------------------------

class TestEstadoDeLogin:
    def test_sem_repo_nunca_esta_logado(self, tmp_path):
        s = _sessao(tmp_path)
        assert s.is_logged_in() is False

    def test_flag_ligado_com_diretorio_presente_e_logado(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo)
        assert s.is_logged_in() is True

    def test_flag_ligado_sem_diretorio_nao_e_logado(self, tmp_path):
        """
        Se o usuário apagou credentials/, não existe sessão — o flag estaria
        mentindo e a publicação abriria na tela de login.
        """
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo, criar_dir=False)
        assert s.is_logged_in() is False

    def test_config_antiga_sem_a_chave_nao_quebra(self, tmp_path):
        """O merge de defaults é raso: configs antigas chegam sem 'logged_in'."""
        repo = _FakeConfigRepo({"spotify": {"show_id": "abc"}})
        s = _sessao(tmp_path, repo=repo)
        assert s.is_logged_in() is False

    def test_spotify_ausente_no_config_nao_quebra(self, tmp_path):
        s = _sessao(tmp_path, repo=_FakeConfigRepo({}))
        assert s.is_logged_in() is False

    def test_spotify_none_no_config_nao_quebra(self, tmp_path):
        s = _sessao(tmp_path, repo=_FakeConfigRepo({"spotify": None}))
        assert s.is_logged_in() is False

    def test_mark_logged_in_persiste(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"show_id": "abc"}})
        s = _sessao(tmp_path, repo=repo)
        s.mark_logged_in(True)
        assert repo.data["spotify"]["logged_in"] is True
        assert s.is_logged_in() is True

    def test_mark_logged_in_preserva_os_outros_campos(self, tmp_path):
        repo = _FakeConfigRepo(
            {"spotify": {"show_id": "abc", "title_prefix": "IPM ", "default_tags": "t"}}
        )
        s = _sessao(tmp_path, repo=repo)
        s.mark_logged_in(True)
        sp = repo.data["spotify"]
        assert sp["show_id"] == "abc"
        assert sp["title_prefix"] == "IPM "
        assert sp["default_tags"] == "t"

    def test_mark_logged_in_false_desliga(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo)
        s.mark_logged_in(False)
        assert repo.data["spotify"]["logged_in"] is False

    def test_mark_logged_in_sem_repo_e_noop(self, tmp_path):
        s = _sessao(tmp_path)
        s.mark_logged_in(True)   # não deve levantar
        assert s.is_logged_in() is False

    def test_falha_do_repo_nao_propaga(self, tmp_path):
        class _RepoQuebrado:
            def load(self):
                raise RuntimeError("disco cheio")

            def update(self, **kw):
                raise RuntimeError("disco cheio")

        s = _sessao(tmp_path, repo=_RepoQuebrado())
        s.mark_logged_in(True)          # não deve levantar
        assert s.is_logged_in() is False


class TestClassifySemPersistir:
    """
    `classify` existe para navegações intermediárias, que mentem sobre a sessão.

    Medido ao vivo: abrir a sonda deslogado produz o veredito `logged_in`
    primeiro (a URL interna do Creators, antes do desvio feito pelo próprio
    site) e só depois `logged_out`. Quem observa navegação em curso precisa do
    veredito sem gravar nada.
    """

    def test_devolve_o_mesmo_veredito_da_funcao(self, tmp_path):
        s = _sessao(tmp_path, repo=_FakeConfigRepo({"spotify": {}}))
        url = "https://creators.spotify.com/pod/dashboard"
        assert s.classify(url) == classify_url(url) == SPOTIFY_LOGGED_IN

    def test_nao_liga_o_flag(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {}})
        s = _sessao(tmp_path, repo=repo)
        s.classify("https://creators.spotify.com/pod/dashboard")
        assert s.is_logged_in() is False
        assert repo.saves == 0

    def test_nao_desliga_o_flag(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo)
        s.classify("https://accounts.spotify.com/pt-BR/login")
        assert s.is_logged_in() is True
        assert repo.saves == 0


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_sem_perfil_instanciado_apaga_na_hora(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo)
        marca = os.path.join(s.storage_dir, "Cookies")
        with open(marca, "w") as fh:
            fh.write("x")

        s.logout()

        assert not os.path.isdir(s.storage_dir)
        assert s.is_logged_in() is False

    def test_com_perfil_vivo_limpa_cookies_e_agenda_wipe(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo)

        class _Store:
            def __init__(self):
                self.apagou = False

            def deleteAllCookies(self):
                self.apagou = True

        class _Perfil:
            def __init__(self):
                self._store = _Store()

            def cookieStore(self):
                return self._store

        perfil = _Perfil()
        s._profile = perfil

        s.logout()

        assert perfil._store.apagou, "cookies não foram limpos"
        assert s.is_logged_in() is False
        # O diretório continua (o Chromium o mantém aberto), mas fica marcado
        assert os.path.exists(s.storage_dir + ".wipe")

    def test_erro_ao_limpar_cookies_nao_propaga(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo)

        class _PerfilQuebrado:
            def cookieStore(self):
                raise RuntimeError("perfil já destruído")

        s._profile = _PerfilQuebrado()
        s.logout()                      # não deve levantar
        assert s.is_logged_in() is False

    def test_wipe_pendente_e_executado_na_proxima_abertura(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo)
        s._profile = object()           # simula perfil vivo (sem cookieStore)
        s.logout()
        assert os.path.isdir(s.storage_dir), "diretório deveria sobreviver ao logout"

        # Próxima execução do app: mesma pasta, sessão nova
        s2 = SpotifyWebSession(storage_dir=s.storage_dir, config_repo=repo)

        assert not os.path.isdir(s2.storage_dir), "wipe pendente não foi aplicado"
        assert not os.path.exists(s2.storage_dir + ".wipe"), "marcador não foi removido"
        assert s2.is_logged_in() is False

    def test_sem_wipe_pendente_o_perfil_sobrevive(self, tmp_path):
        repo = _FakeConfigRepo({"spotify": {"logged_in": True}})
        s = _sessao(tmp_path, repo=repo)
        with open(os.path.join(s.storage_dir, "Cookies"), "w") as fh:
            fh.write("x")

        s2 = SpotifyWebSession(storage_dir=s.storage_dir, config_repo=repo)

        assert os.path.isfile(os.path.join(s2.storage_dir, "Cookies"))
        assert s2.is_logged_in() is True


# ---------------------------------------------------------------------------
# Contrato e conveniências
# ---------------------------------------------------------------------------

class TestContrato:
    def test_implementa_i_spotify_session(self, tmp_path):
        assert isinstance(_sessao(tmp_path), ISpotifySession)

    def test_expoe_storage_dir(self, tmp_path):
        s = _sessao(tmp_path)
        assert s.storage_dir.endswith(os.path.join("credentials", "spotify"))

    def test_login_url_do_metodo_bate_com_a_funcao(self, tmp_path):
        assert _sessao(tmp_path).login_url() == login_url()

    def test_wizard_url_do_metodo_bate_com_a_funcao(self, tmp_path):
        s = _sessao(tmp_path)
        assert s.wizard_url("xyz") == wizard_url("xyz")

    def test_nome_do_perfil_e_estavel(self):
        """
        O nome amarra o perfil ao diretório de storage: mudá-lo entre versões
        faria o app perder o login já salvo dos usuários.
        """
        assert PROFILE_NAME == "ipmadalena_spotify"

    def test_perfil_nao_e_criado_no_construtor(self, tmp_path):
        """Instanciar o app não deve inicializar o QtWebEngine."""
        s = _sessao(tmp_path)
        assert s._profile is None


class TestAcceptLanguage:
    """
    Idioma pedido ao Spotify.

    O perfil do QtWebEngine nasce com ``httpAcceptLanguage`` vazio, e sem esse
    cabeçalho o Spotify for Creators respondia em inglês (medido na raiz
    pública: "Make your show the next big thing" com cabeçalho vazio ×
    "Faça seu programa se destacar" com pt-BR).

    O teste de que o perfil realmente aplica a constante vive em test_app.py —
    aqui nada toca Qt.
    """

    def test_pede_portugues_do_brasil_primeiro(self):
        assert ACCEPT_LANGUAGE.split(",")[0] == "pt-BR"

    def test_tem_ingles_como_ultimo_fallback(self):
        # Sem fallback, uma tela sem tradução ficaria sem idioma aceitável.
        idiomas = [t.split(";")[0] for t in ACCEPT_LANGUAGE.split(",")]
        assert idiomas[-1] == "en"

    def test_formato_de_cabecalho_http_valido(self):
        import re

        for token in ACCEPT_LANGUAGE.split(","):
            assert re.fullmatch(r"[A-Za-z-]+(;q=[01](\.\d+)?)?", token), token
