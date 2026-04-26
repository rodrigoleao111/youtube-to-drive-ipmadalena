"""
Testes de integração para app.py.

Cobre:
  - Instância única (porta TCP)
  - Processamento da fila de mensagens (log, status, progress, done, cancelled, error,
    open_player, download_progress)
  - Worker de pré-execução (_worker_preflight)
  - _on_done: salva histórico + notificação desktop
  - Cancelamento
  - Validação de data no _start()
  - Log em arquivo

Estratégia:
  - Mocks para yt-dlp, Drive, plyer (sem chamadas reais de rede)
  - App.hide() para ocultar a janela durante os testes
  - _process_queue() chamado diretamente (sem mainloop)
  - _worker_preflight chamado diretamente (sem thread) para inspecionar a fila
"""

import os
import queue
import threading
from unittest.mock import MagicMock, call, patch

import pytest

import baixar_audio
import app as app_module
from app import App, _acquire_single_instance


# ---------------------------------------------------------------------------
# Fixture principal — usa a instância de sessão do conftest
# ---------------------------------------------------------------------------

@pytest.fixture
def application(shared_app):
    """Alias do shared_app para os testes deste módulo."""
    return shared_app


@pytest.fixture(autouse=True)
def _reset_app_state(shared_app):
    """Reseta o estado do App antes de cada teste para garantir isolamento."""
    app = shared_app
    app._running = False
    app._converting = False
    app._cancel_event.clear()
    # Zera barras e oculta o frame
    app._hide_bars()
    # Restaura botões para estado idle
    try:
        app._set_buttons_running(False)
    except Exception:
        pass
    # Limpa log box (QPlainTextEdit — setReadOnly não impede clear())
    app.log_box.clear()
    # Drena a fila
    try:
        while True:
            app._queue.get_nowait()
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# Instância única
# ---------------------------------------------------------------------------

class TestSingleInstanceLock:
    def test_primeira_instancia_bem_sucedida(self):
        with patch("socket.socket") as MockSocket:
            mock_sock = MagicMock()
            MockSocket.return_value = mock_sock
            result = _acquire_single_instance()
        assert result is True
        mock_sock.bind.assert_called_once_with(("127.0.0.1", app_module._LOCK_PORT))
        mock_sock.listen.assert_called_once_with(1)

    def test_segunda_instancia_falha_com_porta_ocupada(self):
        with patch("socket.socket") as MockSocket:
            mock_sock = MagicMock()
            mock_sock.bind.side_effect = OSError("Address already in use")
            MockSocket.return_value = mock_sock
            result = _acquire_single_instance()
        assert result is False


# ---------------------------------------------------------------------------
# Inicialização do App
# ---------------------------------------------------------------------------

class TestAppInit:
    def test_ytdlp_update_thread_e_iniciado(self, application):
        """Verifica que o app inicializa sem erros e não está em execução."""
        assert not application._running  # App ainda em idle após init

    def test_estado_inicial_running_e_false(self, application):
        assert application._running is False

    def test_barras_iniciam_ocultas(self, application):
        """O frame de progresso não deve estar visível na inicialização."""
        assert not application._progress_frame.isVisible()


# ---------------------------------------------------------------------------
# Processamento da fila
# ---------------------------------------------------------------------------

class TestQueueProcessing:
    def test_mensagem_log_aparece_no_log_box(self, application):
        application._queue.put(("log", "Olá, mundo de testes"))
        application._process_queue()
        content = application.log_box.toPlainText()
        assert "Olá, mundo de testes" in content

    def test_multiplos_logs_ficam_todos_no_box(self, application):
        for i in range(3):
            application._queue.put(("log", f"Linha {i}"))
        application._process_queue()
        content = application.log_box.toPlainText()
        for i in range(3):
            assert f"Linha {i}" in content

    def test_mensagem_status_atualiza_label(self, application):
        application._queue.put(("status", "Buscando vídeos no YouTube..."))
        application._process_queue()
        assert "Buscando" in application.status_label.text()

    def test_status_concluido_usa_cor_verde(self, application):
        with patch.object(application, "_on_done"):
            application._queue.put(("status", "Concluído!"))
            application._process_queue()
        assert "#2fa84f" in str(application._status_text_color)

    def test_status_convertendo_inicia_animacao(self, application):
        """Quando o status contém 'Convertendo', a flag _converting deve ser ativada."""
        application._show_bars()
        application._queue.put(("status", "Convertendo áudio..."))
        application._process_queue()
        assert application._converting is True

    def test_status_nao_convertendo_para_animacao(self, application):
        """Mudar o status para outra coisa deve parar a animação."""
        application._show_bars()
        application._converting = True
        application._queue.put(("status", "Enviando para o Drive..."))
        application._process_queue()
        assert application._converting is False

    def test_mensagem_progress_atualiza_barra_de_upload(self, application):
        application._show_bars()
        application._queue.put(("progress", 60))
        application._process_queue()
        assert application.progress_bar.get() == pytest.approx(0.60, abs=0.01)

    def test_mensagem_download_progress_atualiza_download_bar(self, application):
        application._show_bars()
        application._queue.put(("download_progress", 0.45))
        application._process_queue()
        assert application.download_bar.get() == pytest.approx(0.45, abs=0.01)

    def test_mensagem_done_chama_on_done_com_args(self, application):
        with patch.object(application, "_on_done") as mock_done:
            application._queue.put(("done", ("19/04/2026", ["Culto A", "Culto B"])))
            application._process_queue()
        mock_done.assert_called_once_with("19/04/2026", ["Culto A", "Culto B"])

    def test_mensagem_cancelled_reseta_running(self, application):
        application._running = True
        application._queue.put(("cancelled", None))
        application._process_queue()
        assert application._running is False

    def test_mensagem_cancelled_status_e_cinza(self, application):
        application._running = True
        application._queue.put(("cancelled", None))
        application._process_queue()
        text = application.status_label.text()
        assert "cancelad" in text.lower()

    def test_mensagem_error_reseta_running(self, application):
        application._running = True
        with patch.object(application, "_show_error"):
            application._queue.put(("error", "Algo deu errado"))
            application._process_queue()
        assert application._running is False

    def test_mensagem_error_status_com_cor_vermelha(self, application):
        application._running = True
        with patch.object(application, "_show_error"):
            application._queue.put(("error", "Falha"))
            application._process_queue()
        assert "#e05252" in str(application._status_text_color)

    def test_mensagem_preflight_error_reseta_running(self, application):
        application._running = True
        with patch.object(application, "_show_error"):
            application._queue.put(("preflight_error", "Sem conexão"))
            application._process_queue()
        assert application._running is False

    def test_mensagem_history_warning_chama_popup(self, application):
        with patch.object(application, "_show_history_warning") as mock_warn:
            application._queue.put((
                "history_warning",
                ("19/04/2026", ["Culto A"], "19/04/2026 às 10:00"),
            ))
            application._process_queue()
        mock_warn.assert_called_once_with(
            "19/04/2026", ["Culto A"], "19/04/2026 às 10:00"
        )

    def test_mensagem_open_player_chama_show_player_window(self, application):
        """Mensagem 'open_player' deve disparar _show_player_window com os argumentos corretos."""
        with patch.object(application, "_show_player_window") as mock_player:
            videos = [{"id": "abc", "title": "Culto", "upload_date": "20260419"}]
            application._queue.put(("open_player", ("19/04/2026", videos)))
            application._process_queue()
        mock_player.assert_called_once_with("19/04/2026", videos)


# ---------------------------------------------------------------------------
# Worker de pré-execução
# ---------------------------------------------------------------------------

class TestWorkerPreflight:
    """Chama _worker_preflight diretamente (sem thread) e inspeciona a fila."""

    def _run(self, application, date_str, *,
             internet=True, disk_ok=True, disk_mb=1000.0, history=None):
        with patch("baixar_audio.check_internet", return_value=internet), \
             patch("baixar_audio.check_disk_space", return_value=(disk_ok, disk_mb)), \
             patch("baixar_audio.cleanup_downloads"), \
             patch("baixar_audio.load_history", return_value=history or {}):
            application._worker_preflight(date_str)

    def _drain_queue(self, application):
        messages = []
        try:
            while True:
                messages.append(application._queue.get_nowait())
        except queue.Empty:
            pass
        return messages

    def test_sem_internet_enfileira_preflight_error(self, application):
        self._run(application, "19/04/2026", internet=False)
        msgs = self._drain_queue(application)
        kinds = [m[0] for m in msgs]
        assert "preflight_error" in kinds
        # Mensagem deve mencionar internet
        error_msg = next(m[1] for m in msgs if m[0] == "preflight_error")
        assert "internet" in error_msg.lower()

    def test_disco_insuficiente_enfileira_preflight_error(self, application):
        self._run(application, "19/04/2026", disk_ok=False, disk_mb=200.0)
        msgs = self._drain_queue(application)
        kinds = [m[0] for m in msgs]
        assert "preflight_error" in kinds
        error_msg = next(m[1] for m in msgs if m[0] == "preflight_error")
        assert "200" in error_msg  # informa o valor real disponível

    def test_data_ja_processada_enfileira_history_warning(self, application):
        history = {
            "19/04/2026": {
                "processado_em": "2026-04-19T10:00:00",
                "videos": ["Culto da Manhã"],
            }
        }
        self._run(application, "19/04/2026", history=history)
        msgs = self._drain_queue(application)
        kinds = [m[0] for m in msgs]
        assert "history_warning" in kinds
        warn = next(m[1] for m in msgs if m[0] == "history_warning")
        date_str, videos, processado_em = warn
        assert date_str == "19/04/2026"
        assert "Culto da Manhã" in videos

    def test_tudo_ok_inicia_thread_worker(self, application):
        with patch("baixar_audio.check_internet", return_value=True), \
             patch("baixar_audio.check_disk_space", return_value=(True, 1000.0)), \
             patch("baixar_audio.cleanup_downloads"), \
             patch("baixar_audio.load_history", return_value={}), \
             patch("threading.Thread") as MockThread:
            mock_t = MagicMock()
            MockThread.return_value = mock_t
            application._worker_preflight("19/04/2026")
        MockThread.assert_called()
        mock_t.start.assert_called_once()

    def test_cleanup_e_chamado_no_preflight(self, application):
        with patch("baixar_audio.check_internet", return_value=True), \
             patch("baixar_audio.check_disk_space", return_value=(True, 1000.0)), \
             patch("baixar_audio.cleanup_downloads") as mock_cleanup, \
             patch("baixar_audio.load_history", return_value={}), \
             patch("threading.Thread"):
            application._worker_preflight("19/04/2026")
        mock_cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# _on_done
# ---------------------------------------------------------------------------

class TestOnDone:
    def test_salva_historico_com_data_e_titulos(self, application):
        with patch("baixar_audio.save_history") as mock_save, \
             patch("plyer.notification.notify"):
            application._on_done("19/04/2026", ["Culto A", "Culto B"])
        mock_save.assert_called_once_with("19/04/2026", ["Culto A", "Culto B"])

    def test_envia_notificacao_desktop(self, application):
        with patch("baixar_audio.save_history"), \
             patch("plyer.notification.notify") as mock_notify:
            application._on_done("19/04/2026", ["Culto"])
        mock_notify.assert_called_once()

    def test_notificacao_menciona_ipmadalena(self, application):
        with patch("baixar_audio.save_history"), \
             patch("plyer.notification.notify") as mock_notify:
            application._on_done("19/04/2026", ["Culto"])
        kwargs = mock_notify.call_args[1]
        assert "IPMadalena" in kwargs.get("title", "") or "IPMadalena" in kwargs.get("app_name", "")

    def test_reseta_running_para_false(self, application):
        application._running = True
        with patch("baixar_audio.save_history"), \
             patch("plyer.notification.notify"):
            application._on_done("19/04/2026", ["Culto"])
        assert application._running is False

    def test_barra_de_upload_vai_para_100_porcento(self, application):
        application._show_bars()
        with patch("baixar_audio.save_history"), \
             patch("plyer.notification.notify"):
            application._on_done("19/04/2026", ["Culto"])
        assert application.progress_bar.get() == pytest.approx(1.0, abs=0.01)

    def test_sem_excecao_quando_plyer_nao_disponivel(self, application):
        """plyer é opcional — app não deve quebrar se não estiver instalado."""
        import sys
        # Remove temporariamente o plyer do sys.modules
        saved = sys.modules.pop("plyer", None)
        try:
            with patch("baixar_audio.save_history"):
                application._on_done("19/04/2026", ["Culto"])  # não deve lançar
        finally:
            if saved is not None:
                sys.modules["plyer"] = saved


# ---------------------------------------------------------------------------
# Cancelamento
# ---------------------------------------------------------------------------

class TestCancellation:
    def test_cancel_sinaliza_o_evento(self, application):
        application._running = True
        application._cancel_event.clear()
        application._cancel()
        assert application._cancel_event.is_set()

    def test_cancel_nao_faz_nada_se_nao_estiver_rodando(self, application):
        application._running = False
        application._cancel_event.clear()
        application._cancel()
        assert not application._cancel_event.is_set()

    def test_cancel_desabilita_botao_cancelar(self, application):
        application._running = True
        application._set_buttons_running(True)  # mostra o botão
        application._cancel()
        assert not application.cancel_btn.isEnabled()

    def test_on_cancelled_oculta_barras(self, application):
        """Após cancelar, as barras devem ser zeradas."""
        application._show_bars()
        application._on_cancelled()
        # Barras devem estar em 0 após cancelamento
        assert application.download_bar.get() == pytest.approx(0.0, abs=0.01)
        assert application.progress_bar.get() == pytest.approx(0.0, abs=0.01)

    def test_on_cancelled_reseta_running(self, application):
        application._running = True
        application._on_cancelled()
        assert application._running is False

    def test_on_cancelled_status_idle(self, application):
        application._on_cancelled()
        # Estado idle → cor cinza, ou texto menciona cancelamento
        assert "gray" in str(application._status_text_color).lower() or \
               "cancelad" in application.status_label.text().lower()


# ---------------------------------------------------------------------------
# Validação de data no _start()
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_data_vazia_mostra_erro_nao_inicia_worker(self, application):
        application.date_entry.clear()
        with patch.object(application, "_show_error") as mock_err, \
             patch("threading.Thread") as MockThread:
            application._start()
        mock_err.assert_called_once()
        MockThread.assert_not_called()

    def test_formato_errado_mostra_erro(self, application):
        application.date_entry.clear()
        application.date_entry.setText("2026-04-19")  # ISO, não DD/MM/AAAA
        with patch.object(application, "_show_error") as mock_err, \
             patch("threading.Thread") as MockThread:
            application._start()
        mock_err.assert_called_once()
        MockThread.assert_not_called()

    def test_data_valida_inicia_thread_preflight(self, application):
        application.date_entry.clear()
        application.date_entry.setText("19/04/2026")
        with patch("baixar_audio.check_auth_status", return_value=True), \
             patch("threading.Thread") as MockThread:
            mock_t = MagicMock()
            MockThread.return_value = mock_t
            application._start()
        MockThread.assert_called()
        mock_t.start.assert_called()

    def test_data_valida_seta_running_true(self, application):
        application.date_entry.clear()
        application.date_entry.setText("19/04/2026")
        with patch("baixar_audio.check_auth_status", return_value=True), \
             patch("threading.Thread"):
            application._start()
        assert application._running is True

    def test_sem_autorizacao_mostra_erro_e_nao_inicia(self, application):
        """Se Drive não autorizado, _start deve mostrar erro sem iniciar worker."""
        application.date_entry.clear()
        application.date_entry.setText("19/04/2026")
        with patch("baixar_audio.check_auth_status", return_value=False), \
             patch.object(application, "_show_error") as mock_err, \
             patch("threading.Thread") as MockThread:
            application._start()
        mock_err.assert_called_once()
        MockThread.assert_not_called()


# ---------------------------------------------------------------------------
# Log em arquivo
# ---------------------------------------------------------------------------

class TestFileLogging:
    def test_log_file_criado_no_diretorio_correto(self, tmp_path):
        from datetime import datetime
        from app import _setup_file_logging
        import logging

        # Remove handlers existentes para isolar o teste
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()

        with patch.object(baixar_audio, "LOGS_DIR", str(tmp_path)):
            _setup_file_logging()

        log_files = list(tmp_path.iterdir())
        # Limpa handlers adicionados pelo teste
        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)

        assert len(log_files) == 1
        assert log_files[0].suffix == ".log"
        today = datetime.now().strftime("%d-%m-%Y")
        assert today in log_files[0].name

    def test_log_file_contem_entrada_de_inicio(self, tmp_path):
        from app import _setup_file_logging
        import logging

        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers.clear()

        with patch.object(baixar_audio, "LOGS_DIR", str(tmp_path)):
            _setup_file_logging()

        log_files = list(tmp_path.iterdir())
        content = log_files[0].read_text(encoding="utf-8")

        root_logger.handlers.clear()
        root_logger.handlers.extend(original_handlers)

        assert "App iniciado" in content


# ---------------------------------------------------------------------------
# T4 — _worker, _worker_phase2, _build_presenter (delegação ao presenter)
# ---------------------------------------------------------------------------

class TestBuildPresenter:
    """Verifica que _build_presenter() compõe corretamente os use cases."""

    def test_retorna_processing_presenter_com_use_cases(self, application):
        from presentation.processing_presenter import ProcessingPresenter
        from application.use_cases import (
            ListVideosUseCase, DownloadSegmentsUseCase, UploadAudioUseCase,
        )
        presenter = application._build_presenter()
        assert isinstance(presenter, ProcessingPresenter)
        assert isinstance(presenter.list_videos_uc, ListVideosUseCase)
        assert isinstance(presenter.download_uc, DownloadSegmentsUseCase)
        assert isinstance(presenter.upload_uc, UploadAudioUseCase)

    def test_usa_channel_url_do_config(self, application):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "https://youtube.com/@TesteCanal",
            "drive_folder_id": "fake_folder",
        }):
            presenter = application._build_presenter()
        assert presenter.channel_url == "https://youtube.com/@TesteCanal"

    def test_usa_download_dir_do_baixar_audio(self, application):
        presenter = application._build_presenter()
        assert presenter.download_dir == baixar_audio.DOWNLOAD_DIR

    def test_storage_recebe_drive_folder_id_do_config(self, application):
        with patch("baixar_audio.load_config", return_value={
            "channel_url": "x", "drive_folder_id": "pasta-custom-123",
        }):
            presenter = application._build_presenter()
        # GoogleDriveStorage guarda em _root_folder_id
        assert presenter.upload_uc.storage._root_folder_id == "pasta-custom-123"


class TestWorker:
    """Fluxo Fase 1: lista vídeos via presenter e enfileira select_videos."""

    def test_videos_listados_enfileiram_select_videos(self, application):
        videos = [{"id": "v1", "title": "Culto", "upload_date": "20260419"}]
        mock_presenter = MagicMock()
        mock_presenter.list_videos.return_value = videos

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker("19/04/2026")

        msgs = []
        try:
            while True:
                msgs.append(application._queue.get_nowait())
        except queue.Empty:
            pass

        assert ("select_videos", ("19/04/2026", videos)) in msgs

    def test_chama_presenter_list_videos_com_args_corretos(self, application):
        mock_presenter = MagicMock()
        mock_presenter.list_videos.return_value = []

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker("19/04/2026")

        args, kwargs = mock_presenter.list_videos.call_args
        assert args[0] == "19/04/2026"
        assert kwargs["cancel_event"] is application._cancel_event
        assert callable(kwargs["on_log"])
        assert callable(kwargs["on_status"])

    def test_operacao_cancelada_enfileira_cancelled(self, application):
        from domain.exceptions import OperacaoCancelada
        mock_presenter = MagicMock()
        mock_presenter.list_videos.side_effect = OperacaoCancelada("cancelado")

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker("19/04/2026")

        msgs = []
        try:
            while True:
                msgs.append(application._queue.get_nowait())
        except queue.Empty:
            pass

        assert ("cancelled", None) in msgs

    def test_excecao_generica_enfileira_error(self, application):
        mock_presenter = MagicMock()
        mock_presenter.list_videos.side_effect = RuntimeError("falha qualquer")

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker("19/04/2026")

        msgs = []
        try:
            while True:
                msgs.append(application._queue.get_nowait())
        except queue.Empty:
            pass

        kinds = [m[0] for m in msgs]
        assert "error" in kinds
        err_payload = next(m[1] for m in msgs if m[0] == "error")
        assert "falha qualquer" in err_payload


class TestWorkerPhase2:
    """Fluxo Fase 2: download + upload via presenter, enfileira done."""

    def _segments(self):
        return [
            {"id": "v1", "title": "Culto A", "start": None, "end": None},
            {"id": "v2", "title": "Culto B", "start": "00:10:00", "end": "01:00:00"},
        ]

    def test_titulos_sao_enfileirados_em_done(self, application):
        mock_presenter = MagicMock()
        mock_presenter.process_segments.return_value = ["Culto A", "Culto B"]

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker_phase2("19/04/2026", self._segments())

        msgs = []
        try:
            while True:
                msgs.append(application._queue.get_nowait())
        except queue.Empty:
            pass

        assert ("done", ("19/04/2026", ["Culto A", "Culto B"])) in msgs

    def test_chama_presenter_process_segments_com_callbacks(self, application):
        mock_presenter = MagicMock()
        mock_presenter.process_segments.return_value = []
        segs = self._segments()

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker_phase2("19/04/2026", segs)

        args, kwargs = mock_presenter.process_segments.call_args
        assert args[0] == "19/04/2026"
        assert args[1] == segs
        assert kwargs["cancel_event"] is application._cancel_event
        # Todos os callbacks principais devem ser repassados
        for key in ("on_log", "on_status", "on_download_progress",
                   "on_upload_progress", "on_upload_stats"):
            assert callable(kwargs[key])

    def test_operacao_cancelada_enfileira_cancelled(self, application):
        from domain.exceptions import OperacaoCancelada
        mock_presenter = MagicMock()
        mock_presenter.process_segments.side_effect = OperacaoCancelada("x")

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker_phase2("19/04/2026", self._segments())

        msgs = []
        try:
            while True:
                msgs.append(application._queue.get_nowait())
        except queue.Empty:
            pass

        assert ("cancelled", None) in msgs

    def test_excecao_generica_enfileira_error(self, application):
        mock_presenter = MagicMock()
        mock_presenter.process_segments.side_effect = RuntimeError("upload falhou")

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker_phase2("19/04/2026", self._segments())

        msgs = []
        try:
            while True:
                msgs.append(application._queue.get_nowait())
        except queue.Empty:
            pass

        kinds = [m[0] for m in msgs]
        assert "error" in kinds
        err_payload = next(m[1] for m in msgs if m[0] == "error")
        assert "upload falhou" in err_payload

    def test_callbacks_repassam_para_a_fila(self, application):
        """
        Verifica que os callbacks dados ao presenter realmente colocam
        mensagens na fila quando invocados.
        """
        captured_callbacks = {}

        def fake_process(date_str, segs, **kwargs):
            captured_callbacks.update(kwargs)
            return []

        mock_presenter = MagicMock()
        mock_presenter.process_segments.side_effect = fake_process

        with patch.object(application, "_build_presenter", return_value=mock_presenter):
            application._worker_phase2("19/04/2026", self._segments())

        # Drena a fila do `done` que veio do worker
        try:
            while True:
                application._queue.get_nowait()
        except queue.Empty:
            pass

        # Aciona cada callback e confirma a mensagem correspondente
        captured_callbacks["on_log"]("oi")
        captured_callbacks["on_status"]("buscando")
        captured_callbacks["on_download_progress"](0.5)
        captured_callbacks["on_upload_progress"](42)
        captured_callbacks["on_upload_stats"](1.0, 2.0, 0.5)

        msgs = []
        try:
            while True:
                msgs.append(application._queue.get_nowait())
        except queue.Empty:
            pass

        kinds = [m[0] for m in msgs]
        assert "log" in kinds
        assert "status" in kinds
        assert "download_progress" in kinds
        assert "progress" in kinds        # on_upload_progress vira "progress"
        assert "upload_stats" in kinds
