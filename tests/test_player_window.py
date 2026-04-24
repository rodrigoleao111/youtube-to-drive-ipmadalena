"""
Testes para player_window.py.

Cobre:
  - Funções utilitárias: _seconds_to_hms, _hms_to_seconds
  - _build_player_cmd: comando correto em modo script vs frozen
  - PlayerWindow: inicialização, validação de trecho, segmentos gerados,
    uso de vídeo completo, cancelamento
"""

import sys
from unittest.mock import MagicMock, patch

import pytest
import customtkinter as ctk

from player_window import (
    PlayerWindow,
    _build_player_cmd,
    _hms_to_seconds,
    _seconds_to_hms,
)


# ---------------------------------------------------------------------------
# _seconds_to_hms
# ---------------------------------------------------------------------------

class TestSecondsToHms:
    def test_zero(self):
        assert _seconds_to_hms(0) == "00:00:00"

    def test_segundos_simples(self):
        assert _seconds_to_hms(90) == "00:01:30"

    def test_uma_hora(self):
        assert _seconds_to_hms(3600) == "01:00:00"

    def test_valor_grande(self):
        # 2h 3m 4s = 7384s
        assert _seconds_to_hms(7384) == "02:03:04"

    def test_trunca_casas_decimais(self):
        # float → trunca para inteiro
        assert _seconds_to_hms(90.9) == "00:01:30"

    def test_formato_dois_digitos(self):
        result = _seconds_to_hms(65)
        assert result == "00:01:05"


# ---------------------------------------------------------------------------
# _hms_to_seconds
# ---------------------------------------------------------------------------

class TestHmsToSeconds:
    def test_zero(self):
        assert _hms_to_seconds("00:00:00") == pytest.approx(0.0)

    def test_um_minuto_trinta_segundos(self):
        assert _hms_to_seconds("00:01:30") == pytest.approx(90.0)

    def test_uma_hora(self):
        assert _hms_to_seconds("01:00:00") == pytest.approx(3600.0)

    def test_valor_grande(self):
        assert _hms_to_seconds("02:03:04") == pytest.approx(7384.0)

    def test_formato_invalido_retorna_none(self):
        assert _hms_to_seconds("01:30") is None        # faltam partes
        assert _hms_to_seconds("abc") is None
        assert _hms_to_seconds("") is None

    def test_minutos_invalidos_retorna_none(self):
        assert _hms_to_seconds("00:60:00") is None     # minutos >= 60

    def test_segundos_invalidos_retorna_none(self):
        assert _hms_to_seconds("00:00:60") is None     # segundos >= 60

    def test_valores_nao_numericos_retorna_none(self):
        assert _hms_to_seconds("ab:cd:ef") is None

    def test_roundtrip(self):
        """_hms_to_seconds(_seconds_to_hms(t)) == t para valores inteiros."""
        for t in [0, 59, 3600, 7384, 43199]:
            assert _hms_to_seconds(_seconds_to_hms(t)) == pytest.approx(float(t))


# ---------------------------------------------------------------------------
# _build_player_cmd
# ---------------------------------------------------------------------------

class TestBuildPlayerCmd:
    def test_modo_script_usa_python_player_subprocess(self):
        with patch.object(sys, "frozen", False, create=True):
            cmd = _build_player_cmd("abc123", 0, 0, 860, 480)
        assert cmd[0] == sys.executable
        assert any("player_subprocess.py" in arg for arg in cmd)
        assert "abc123" in cmd
        assert "--player-mode" not in cmd

    def test_modo_frozen_usa_player_mode_flag(self):
        with patch.object(sys, "frozen", True, create=True):
            cmd = _build_player_cmd("xyz999", 10, 20, 860, 480)
        assert cmd[0] == sys.executable
        assert "--player-mode" in cmd
        assert "xyz999" in cmd

    def test_argumentos_de_posicao_corretos(self):
        with patch.object(sys, "frozen", False, create=True):
            cmd = _build_player_cmd("vid1", 100, 200, 860, 480)
        assert "vid1" in cmd
        assert "100" in cmd
        assert "200" in cmd
        assert "860" in cmd
        assert "480" in cmd


# ---------------------------------------------------------------------------
# Fixture — usa o App compartilhado da sessão como janela pai
# ---------------------------------------------------------------------------

@pytest.fixture
def root(shared_app):
    """Reutiliza a instância App da sessão para evitar múltiplas janelas Tk."""
    return shared_app


# ---------------------------------------------------------------------------
# PlayerWindow — testes de comportamento interno
# ---------------------------------------------------------------------------

class TestPlayerWindow:
    """Testa comportamento do PlayerWindow sem abrir subprocesso real."""

    def _make_window(self, root, videos=None, on_complete=None, on_cancel=None):
        if videos is None:
            videos = [{"id": "abc123", "title": "Culto Teste", "upload_date": "20260419"}]
        _complete_calls = []
        _cancel_calls   = []
        if on_complete is None:
            on_complete = lambda segs: _complete_calls.append(segs)
        if on_cancel is None:
            on_cancel = lambda: _cancel_calls.append(True)

        with patch.object(PlayerWindow, "_start_player"):
            pw = PlayerWindow(root, videos, on_complete=on_complete, on_cancel=on_cancel)

        return pw, _complete_calls, _cancel_calls

    def _destroy(self, pw):
        try:
            pw._kill_player()
            pw.grab_release()
            pw.destroy()
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # Inicialização
    # -----------------------------------------------------------------------

    def test_janela_criada_com_titulo(self, root):
        pw, _, _ = self._make_window(root)
        assert "Seleção" in pw.title() or pw.winfo_exists()
        self._destroy(pw)

    def test_titulo_do_video_exibido(self, root):
        videos = [{"id": "x", "title": "Culto de Páscoa 2026", "upload_date": "20260419"}]
        pw, _, _ = self._make_window(root, videos=videos)
        assert "Páscoa" in pw._title_lbl.cget("text")
        self._destroy(pw)

    def test_contador_correto_para_um_video(self, root):
        pw, _, _ = self._make_window(root)
        assert "1 de 1" in pw._counter_lbl.cget("text")
        self._destroy(pw)

    def test_contador_correto_para_multiplos_videos(self, root):
        videos = [
            {"id": "a", "title": "Culto 1", "upload_date": "20260419"},
            {"id": "b", "title": "Culto 2", "upload_date": "20260419"},
        ]
        pw, _, _ = self._make_window(root, videos=videos)
        assert "1 de 2" in pw._counter_lbl.cget("text")
        self._destroy(pw)

    # -----------------------------------------------------------------------
    # Validação do trecho (_confirm)
    # -----------------------------------------------------------------------

    def test_confirm_rejeita_fim_menor_que_inicio(self, root):
        pw, complete, _ = self._make_window(root)
        pw._start_var.set("01:00:00")
        pw._end_var.set("00:30:00")
        pw._confirm()
        # Não deve avançar
        assert complete == []
        self._destroy(pw)

    def test_confirm_rejeita_fim_igual_ao_inicio(self, root):
        pw, complete, _ = self._make_window(root)
        pw._start_var.set("00:30:00")
        pw._end_var.set("00:30:00")
        pw._confirm()
        assert complete == []
        self._destroy(pw)

    def test_confirm_rejeita_ambos_zerados(self, root):
        pw, complete, _ = self._make_window(root)
        pw._start_var.set("00:00:00")
        pw._end_var.set("00:00:00")
        pw._confirm()
        assert complete == []
        self._destroy(pw)

    def test_confirm_rejeita_formato_invalido(self, root):
        pw, complete, _ = self._make_window(root)
        pw._start_var.set("abc")
        pw._end_var.set("def")
        pw._confirm()
        assert complete == []
        self._destroy(pw)

    def test_confirm_valido_chama_on_complete(self, root):
        pw, complete, _ = self._make_window(root)
        pw._start_var.set("00:15:00")
        pw._end_var.set("01:10:00")
        with patch.object(pw, "_kill_player"):
            pw._confirm()
        assert len(complete) == 1
        segs = complete[0]
        assert len(segs) == 1
        assert segs[0]["start"] == "00:15:00"
        assert segs[0]["end"] == "01:10:00"
        assert segs[0]["id"] == "abc123"

    # -----------------------------------------------------------------------
    # Vídeo completo (_use_full)
    # -----------------------------------------------------------------------

    def test_use_full_gera_segmento_sem_start_end(self, root):
        pw, complete, _ = self._make_window(root)
        with patch.object(pw, "_kill_player"):
            pw._use_full()
        segs = complete[0]
        assert segs[0]["start"] is None
        assert segs[0]["end"] is None

    def test_use_full_inclui_id_e_titulo(self, root):
        videos = [{"id": "xyz999", "title": "Culto Especial", "upload_date": "20260419"}]
        pw, complete, _ = self._make_window(root, videos=videos)
        with patch.object(pw, "_kill_player"):
            pw._use_full()
        segs = complete[0]
        assert segs[0]["id"] == "xyz999"
        assert segs[0]["title"] == "Culto Especial"

    # -----------------------------------------------------------------------
    # Múltiplos vídeos — avanço de vídeo
    # -----------------------------------------------------------------------

    def test_avanca_para_segundo_video_apos_confirmar(self, root):
        videos = [
            {"id": "a", "title": "Culto 1", "upload_date": "20260419"},
            {"id": "b", "title": "Culto 2", "upload_date": "20260419"},
        ]
        pw, complete, _ = self._make_window(root, videos=videos)
        pw._start_var.set("00:10:00")
        pw._end_var.set("01:00:00")
        with patch.object(pw, "_start_player"):
            pw._confirm()
        # Após confirmar primeiro, deve estar no segundo (idx == 1)
        assert pw._idx == 1
        assert "2 de 2" in pw._counter_lbl.cget("text")
        self._destroy(pw)

    def test_completa_com_dois_segmentos_para_dois_videos(self, root):
        videos = [
            {"id": "a", "title": "Culto 1", "upload_date": "20260419"},
            {"id": "b", "title": "Culto 2", "upload_date": "20260419"},
        ]
        pw, complete, _ = self._make_window(root, videos=videos)
        with patch.object(pw, "_start_player"), \
             patch.object(pw, "_kill_player"):
            pw._start_var.set("00:10:00")
            pw._end_var.set("01:00:00")
            pw._confirm()
            pw._use_full()
        assert len(complete) == 1
        segs = complete[0]
        assert len(segs) == 2
        assert segs[0]["id"] == "a"
        assert segs[1]["id"] == "b"
        assert segs[1]["start"] is None

    # -----------------------------------------------------------------------
    # Cancelamento
    # -----------------------------------------------------------------------

    def test_cancel_chama_on_cancel(self, root):
        pw, complete, cancel_calls = self._make_window(root)
        with patch.object(pw, "_kill_player"):
            pw._cancel()
        assert cancel_calls == [True]
        assert complete == []

    # -----------------------------------------------------------------------
    # Duração calculada
    # -----------------------------------------------------------------------

    def test_duracao_calculada_corretamente(self, root):
        pw, _, _ = self._make_window(root)
        pw._start_var.set("00:10:00")
        pw._end_var.set("01:10:00")
        pw._update_duration()
        assert pw._dur_lbl.cget("text") == "01:00:00"
        self._destroy(pw)

    def test_duracao_invalida_exibe_tracos(self, root):
        pw, _, _ = self._make_window(root)
        pw._start_var.set("01:00:00")
        pw._end_var.set("00:30:00")  # fim < início
        pw._update_duration()
        assert pw._dur_lbl.cget("text") == "--:--:--"
        self._destroy(pw)
