"""
Testes para player_window_qt.py e utilitários de player_subprocess_qt.py.

Cobre:
  - _seconds_to_hms e _hms_to_seconds (importados do subprocess qt)
  - _build_cmd: modo script vs frozen
  - PlayerWindowQt: subprocess lançado, vídeos enviados via stdin,
    on_complete chamado com segmentos, on_cancel chamado em cancelamento,
    on_cancel chamado em falha do subprocess

Dispatch cross-thread
---------------------
_monitor emite sinais Qt (_Dispatcher.complete / .cancel) de uma thread de
background. No test, não há event loop rodando, então os sinais são entregues
via QueuedConnection assim que processamos eventos com processEvents().
O helper _run_with_mock_proc aguarda a thread _monitor terminar (via Event)
e em seguida drena os eventos pendentes do Qt.
"""

import json
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication

from player_subprocess_qt import _seconds_to_hms, _hms_to_seconds
from player_window_qt import PlayerWindowQt, _build_cmd


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
        assert _seconds_to_hms(7384) == "02:03:04"

    def test_trunca_casas_decimais(self):
        assert _seconds_to_hms(90.9) == "00:01:30"

    def test_formato_dois_digitos(self):
        assert _seconds_to_hms(65) == "00:01:05"


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

    def test_formato_invalido_sem_dois_pontos(self):
        assert _hms_to_seconds("9000") is None

    def test_formato_invalido_partes_insuficientes(self):
        assert _hms_to_seconds("01:30") is None

    def test_minutos_fora_do_range(self):
        assert _hms_to_seconds("00:60:00") is None

    def test_segundos_fora_do_range(self):
        assert _hms_to_seconds("00:00:60") is None

    def test_valor_nao_numerico(self):
        assert _hms_to_seconds("ab:cd:ef") is None

    def test_espacos_sao_ignorados(self):
        assert _hms_to_seconds("  00:01:00  ") == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# _build_cmd
# ---------------------------------------------------------------------------

class TestBuildCmd:
    def test_modo_script_usa_python_e_arquivo(self):
        with patch.object(sys, "frozen", False, create=True):
            cmd = _build_cmd()
        assert cmd[0] == sys.executable
        assert cmd[1].endswith("player_subprocess_qt.py")

    def test_modo_frozen_usa_player_mode_qt(self):
        with patch.object(sys, "frozen", True, create=True):
            cmd = _build_cmd()
        assert cmd[0] == sys.executable
        assert "--player-mode-qt" in cmd


# ---------------------------------------------------------------------------
# PlayerWindowQt — helper para simular subprocess
# ---------------------------------------------------------------------------

def _make_mock_proc(stdout_lines: list[str], stdin_ok: bool = True):
    """Cria um mock de subprocess.Popen com stdout simulado."""
    proc = MagicMock()
    proc.stdout = iter(stdout_lines)
    proc.stdin.write = MagicMock()
    proc.stdin.flush = MagicMock()
    if not stdin_ok:
        proc.stdin.write.side_effect = OSError("broken pipe")
    proc.wait = MagicMock(return_value=0)
    proc.terminate = MagicMock()
    proc.poll = MagicMock(return_value=0)
    return proc


def _run_with_mock_proc(videos, stdout_lines, stdin_ok=True):
    """
    Instancia PlayerWindowQt com subprocess mockado e espera o callback.
    Retorna (tipo, payload): tipo = 'complete'|'cancel'.

    Estratégia de entrega de sinal:
      - _monitor roda em thread daemon e emite sinais Qt.
      - No ambiente de teste não há event loop rodando; usamos um
        threading.Event para saber quando _monitor terminou, depois
        chamamos processEvents() para entregar os sinais pendentes.
    """
    monitor_done = threading.Event()

    # Instrumenta _monitor para sinalizar quando terminar
    original_monitor = PlayerWindowQt._monitor

    def patched_monitor(self):
        try:
            original_monitor(self)
        finally:
            monitor_done.set()

    result = {}

    def on_complete(segs):
        result["type"] = "complete"
        result["segments"] = segs

    def on_cancel():
        result["type"] = "cancel"

    mock_proc = _make_mock_proc(stdout_lines, stdin_ok)

    with patch.object(PlayerWindowQt, "_monitor", patched_monitor), \
         patch("player_window_qt._build_cmd", return_value=["python", "-c", ""]), \
         patch("subprocess.Popen", return_value=mock_proc):
        PlayerWindowQt(None, videos, on_complete, on_cancel)

    # Aguarda _monitor terminar (emit dos sinais foi chamado)
    monitor_done.wait(timeout=3)
    # Processa eventos Qt pendentes para entregar os sinais (QueuedConnection)
    QApplication.instance().processEvents()

    return result


# ---------------------------------------------------------------------------
# PlayerWindowQt — testes
# ---------------------------------------------------------------------------

VIDEOS = [
    {"id": "abc123", "title": "Culto Manhã", "upload_date": "20260419"},
    {"id": "def456", "title": "Culto Noite", "upload_date": "20260419"},
]

SEGMENTS_PAYLOAD = [
    {"id": "abc123", "title": "Culto Manhã", "start": "00:10:00", "end": "01:00:00"},
    {"id": "def456", "title": "Culto Noite", "start": None,       "end": None},
]


class TestPlayerWindowQtSubprocessLancado:
    def _make(self, stdout_lines):
        """Instancia PlayerWindowQt com proc mockado e aguarda _monitor concluir."""
        monitor_done = threading.Event()
        original_monitor = PlayerWindowQt._monitor

        def patched_monitor(self):
            try:
                original_monitor(self)
            finally:
                monitor_done.set()

        mock_proc = _make_mock_proc(stdout_lines)
        with patch.object(PlayerWindowQt, "_monitor", patched_monitor), \
             patch("player_window_qt._build_cmd", return_value=["python", "-c", ""]), \
             patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            PlayerWindowQt(None, VIDEOS, MagicMock(), MagicMock())
            monitor_done.wait(timeout=3)
            QApplication.instance().processEvents()

        return mock_proc, mock_popen

    def test_popen_chamado_ao_instanciar(self):
        _, mock_popen = self._make(['{"type":"cancelled"}\n'])
        assert mock_popen.called

    def test_lista_de_videos_enviada_via_stdin(self):
        mock_proc, _ = self._make(['{"type":"cancelled"}\n'])
        written = mock_proc.stdin.write.call_args[0][0]
        data = json.loads(written.strip())
        assert "videos" in data
        assert data["videos"] == VIDEOS


class TestPlayerWindowQtCallbacks:
    def test_on_complete_chamado_com_segmentos(self):
        line = json.dumps({"type": "segments", "segments": SEGMENTS_PAYLOAD}) + "\n"
        result = _run_with_mock_proc(VIDEOS, [line])
        assert result.get("type") == "complete"
        assert result.get("segments") == SEGMENTS_PAYLOAD

    def test_on_cancel_chamado_quando_cancelado(self):
        line = json.dumps({"type": "cancelled"}) + "\n"
        result = _run_with_mock_proc(VIDEOS, [line])
        assert result.get("type") == "cancel"

    def test_on_cancel_chamado_quando_subprocess_nao_envia_nada(self):
        result = _run_with_mock_proc(VIDEOS, [])
        assert result.get("type") == "cancel"

    def test_on_cancel_chamado_quando_json_invalido(self):
        result = _run_with_mock_proc(VIDEOS, ["not valid json\n"])
        assert result.get("type") == "cancel"

    def test_on_cancel_chamado_quando_stdin_quebra(self):
        """Erro no __init__ (thread principal) → on_cancel via QTimer.singleShot."""
        cancel_called = threading.Event()

        def on_cancel():
            cancel_called.set()

        mock_proc = _make_mock_proc([], stdin_ok=False)

        def _immediate(delay, fn):
            fn()

        with patch("player_window_qt._build_cmd", return_value=["python", "-c", ""]), \
             patch("subprocess.Popen", return_value=mock_proc), \
             patch("player_window_qt.QTimer") as mock_timer:
            mock_timer.singleShot.side_effect = _immediate
            PlayerWindowQt(None, VIDEOS, MagicMock(), on_cancel)

        assert cancel_called.is_set()

    def test_segmentos_completos_preservados(self):
        segs = [{"id": "x", "title": "T", "start": None, "end": None}]
        line = json.dumps({"type": "segments", "segments": segs}) + "\n"
        result = _run_with_mock_proc(VIDEOS, [line])
        assert result["segments"] == segs


class TestPlayerWindowQtDispatcher:
    def test_dispatcher_emite_complete_com_segmentos(self):
        """_monitor emite dispatcher.complete — entregue no thread principal via processEvents."""
        line = json.dumps({"type": "segments", "segments": SEGMENTS_PAYLOAD}) + "\n"
        result = _run_with_mock_proc(VIDEOS, [line])
        assert result.get("type") == "complete"

    def test_dispatcher_emite_cancel_em_falha(self):
        """_monitor emite dispatcher.cancel em qualquer falha ou cancelamento."""
        result = _run_with_mock_proc(VIDEOS, [])
        assert result.get("type") == "cancel"

    def test_dispatcher_criado_no_thread_principal(self):
        """_Dispatcher deve ser instanciado no __init__ (thread principal)."""
        monitor_done = threading.Event()
        original_monitor = PlayerWindowQt._monitor

        def patched_monitor(self):
            try:
                original_monitor(self)
            finally:
                monitor_done.set()

        mock_proc = _make_mock_proc(['{"type":"cancelled"}\n'])
        pw = None

        with patch.object(PlayerWindowQt, "_monitor", patched_monitor), \
             patch("player_window_qt._build_cmd", return_value=["python", "-c", ""]), \
             patch("subprocess.Popen", return_value=mock_proc):
            pw = PlayerWindowQt(None, VIDEOS, MagicMock(), MagicMock())
            monitor_done.wait(timeout=3)
            QApplication.instance().processEvents()

        from player_window_qt import _Dispatcher
        assert isinstance(pw._dispatcher, _Dispatcher)
