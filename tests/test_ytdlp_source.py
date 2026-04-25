"""
Testes para infrastructure/youtube/ytdlp_source.py e _utils.py.

Todos os subprocessos são mockados — nenhum acesso real à rede.
"""

from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, call, patch

import pytest

from domain.entities import Segment, Video
from domain.exceptions import OperacaoCancelada, VideoNaoEncontrado
from infrastructure.youtube._utils import check_cancel, ffmpeg_dir, ytdlp_exe
from infrastructure.youtube.ytdlp_source import YtDlpAudioDownloader, YtDlpVideoSource


# ===========================================================================
# _utils — ytdlp_exe
# ===========================================================================

class TestYtdlpExe:
    def test_modo_script_retorna_yt_dlp(self):
        with patch.object(sys, "frozen", False, create=True):
            result = ytdlp_exe()
        assert result == "yt-dlp"

    def test_modo_frozen_sem_bundled_retorna_yt_dlp(self):
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", "/fake/meipass", create=True), \
             patch("os.path.exists", return_value=False):
            result = ytdlp_exe()
        assert result == "yt-dlp"

    def test_modo_frozen_com_bundled_retorna_caminho(self):
        import os
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "_MEIPASS", "/fake/meipass", create=True), \
             patch("os.path.exists", return_value=True):
            result = ytdlp_exe()
        expected = os.path.join("/fake/meipass", "yt-dlp.exe")
        assert result == expected


# ===========================================================================
# _utils — check_cancel
# ===========================================================================

class TestCheckCancel:
    def test_sem_evento_nao_levanta(self):
        check_cancel(None)  # deve passar sem erro

    def test_evento_nao_sinalizado_nao_levanta(self):
        import threading
        ev = threading.Event()
        check_cancel(ev)    # deve passar sem erro

    def test_evento_sinalizado_levanta_operacao_cancelada(self):
        import threading
        ev = threading.Event()
        ev.set()
        with pytest.raises(OperacaoCancelada):
            check_cancel(ev)


# ===========================================================================
# _utils — ffmpeg_dir
# ===========================================================================

class TestFfmpegDir:
    def test_retorna_none_quando_nao_encontrado(self):
        with patch("os.path.exists", return_value=False):
            result = ffmpeg_dir()
        assert result is None

    def test_retorna_diretorio_quando_encontrado(self):
        with patch("os.path.exists", return_value=True):
            result = ffmpeg_dir()
        assert result is not None
        assert "ffmpeg" in result.lower()


# ===========================================================================
# Helpers de teste
# ===========================================================================

def _make_process(lines: list[str], returncode: int = 0) -> MagicMock:
    """Cria um mock de subprocess.Popen com stdout simulado."""
    proc = MagicMock()
    proc.stdout = iter(line + "\n" for line in lines)
    proc.returncode = returncode
    proc.wait = MagicMock(return_value=returncode)
    return proc


# ===========================================================================
# YtDlpVideoSource
# ===========================================================================

class TestYtDlpVideoSource:
    """Testa YtDlpVideoSource com subprocess mockado."""

    def _source(self):
        return YtDlpVideoSource()

    # -------------------------------------------------------------------
    # Listagem normal
    # -------------------------------------------------------------------

    def test_retorna_lista_de_videos(self):
        lines = [
            "abc123|||Culto Domingo|||20260419",
            "def456|||Culto Extra|||20260420",
        ]
        proc = _make_process(lines)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            videos = self._source().list_videos(
                "19/04/2026",
                "https://www.youtube.com/@IPMadalena/streams",
            )
        assert len(videos) == 2
        assert all(isinstance(v, Video) for v in videos)
        assert videos[0].id == "abc123"
        assert videos[0].title == "Culto Domingo"

    def test_filtra_datas_fora_do_intervalo(self):
        # Somente upload_date == target ou target+1 são aceitos
        lines = [
            "abc123|||Culto Domingo|||20260419",   # target
            "xyz999|||Video Antigo|||20260301",     # ignorado
            "def456|||Culto Extra|||20260420",      # target+1
            "zzz000|||Amanha Demais|||20260421",    # ignorado
        ]
        proc = _make_process(lines)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            videos = self._source().list_videos("19/04/2026", "https://x")
        assert len(videos) == 2
        assert {v.id for v in videos} == {"abc123", "def456"}

    def test_ignora_linhas_sem_separador(self):
        lines = [
            "[youtube] canal: Downloading page",
            "abc123|||Culto|||20260419",
            "lixo sem pipe",
        ]
        proc = _make_process(lines)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            videos = self._source().list_videos("19/04/2026", "https://x")
        assert len(videos) == 1

    def test_levanta_video_nao_encontrado_quando_lista_vazia(self):
        proc = _make_process([])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            with pytest.raises(VideoNaoEncontrado):
                self._source().list_videos("19/04/2026", "https://x")

    def test_chama_on_log_e_on_status(self):
        lines = ["abc123|||Culto|||20260419"]
        proc = _make_process(lines)
        log_msgs = []
        status_msgs = []
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            self._source().list_videos(
                "19/04/2026", "https://x",
                on_log=log_msgs.append,
                on_status=status_msgs.append,
            )
        assert any("Buscando" in m for m in status_msgs)
        assert any("Canal" in m for m in log_msgs)
        assert any("Culto" in m for m in log_msgs)

    def test_usa_dateafter_correto(self):
        """dateafter deve ser 1 dia antes da data alvo."""
        proc = _make_process(["abc|||T|||20260419"])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start):
            self._source().list_videos("19/04/2026", "https://x")
        idx = captured_cmd.index("--dateafter")
        assert captured_cmd[idx + 1] == "20260418"   # 19/04 - 1 dia = 18/04

    def test_cancela_durante_leitura(self):
        import threading
        ev = threading.Event()

        def _lines():
            yield "abc|||Culto|||20260419\n"
            ev.set()                  # sinaliza cancelamento
            yield "def|||Culto2|||20260419\n"

        proc = MagicMock()
        proc.stdout = _lines()
        proc.returncode = 0
        proc.wait = MagicMock()

        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            with pytest.raises(OperacaoCancelada):
                self._source().list_videos(
                    "19/04/2026", "https://x", cancel_event=ev
                )


# ===========================================================================
# YtDlpAudioDownloader
# ===========================================================================

class TestYtDlpAudioDownloader:
    """Testa YtDlpAudioDownloader com subprocess e glob mockados."""

    def _dl(self):
        return YtDlpAudioDownloader()

    def _seg(self, vid_id="abc", title="Culto", start=None, end=None):
        return Segment(video_id=vid_id, title=title, start=start, end=end)

    # -------------------------------------------------------------------
    # Comando gerado
    # -------------------------------------------------------------------

    def test_video_completo_sem_download_sections(self):
        proc = _make_process([])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            self._dl().download([self._seg()], "/tmp/out")
        assert "--download-sections" not in captured_cmd

    def test_trecho_adiciona_download_sections(self):
        proc = _make_process([])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            seg = self._seg(start="00:10:00", end="01:00:00")
            self._dl().download([seg], "/tmp/out")
        assert "--download-sections" in captured_cmd
        idx = captured_cmd.index("--download-sections")
        assert captured_cmd[idx + 1] == "*00:10:00-01:00:00"

    def test_formato_asterisco_no_trecho(self):
        """O trecho DEVE ter o prefixo '*' para o yt-dlp."""
        proc = _make_process([])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            seg = self._seg(start="00:05:00", end="00:30:00")
            self._dl().download([seg], "/tmp/out")
        idx = captured_cmd.index("--download-sections")
        assert captured_cmd[idx + 1].startswith("*")

    def test_ffmpeg_location_adicionado_quando_disponivel(self):
        proc = _make_process([])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value="/usr/bin"), \
             patch("glob.glob", return_value=[]):
            self._dl().download([self._seg()], "/tmp/out")
        assert "--ffmpeg-location" in captured_cmd
        idx = captured_cmd.index("--ffmpeg-location")
        assert captured_cmd[idx + 1] == "/usr/bin"

    def test_sem_ffmpeg_nao_adiciona_flag(self):
        proc = _make_process([])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            self._dl().download([self._seg()], "/tmp/out")
        assert "--ffmpeg-location" not in captured_cmd

    # -------------------------------------------------------------------
    # Subprocessos por vídeo
    # -------------------------------------------------------------------

    def test_um_subprocess_por_segmento(self):
        procs = [_make_process([]) for _ in range(3)]
        call_count = []
        def fake_start(cmd, *a, **kw):
            p = procs[len(call_count)]
            call_count.append(1)
            return p
        segs = [self._seg(vid_id=str(i), title=f"V{i}") for i in range(3)]
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            self._dl().download(segs, "/tmp/out")
        assert len(call_count) == 3

    # -------------------------------------------------------------------
    # Progresso
    # -------------------------------------------------------------------

    def test_progresso_intermediario_reportado(self):
        lines = [
            "[download]  50.0% of 100MB",
        ]
        proc = _make_process(lines)
        progress_vals = []
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            self._dl().download(
                [self._seg()], "/tmp/out",
                on_progress=progress_vals.append,
            )
        assert any(0.0 < v < 1.0 for v in progress_vals)

    def test_progresso_completo_ao_extract_audio(self):
        lines = ["[ExtractAudio] Destination: culto.mp3"]
        proc = _make_process(lines)
        progress_vals = []
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            self._dl().download(
                [self._seg()], "/tmp/out",
                on_progress=progress_vals.append,
            )
        assert 1.0 in progress_vals

    # -------------------------------------------------------------------
    # Erros e cancelamento
    # -------------------------------------------------------------------

    def test_levanta_runtime_error_quando_returncode_diferente_de_zero(self):
        proc = _make_process([], returncode=1)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                self._dl().download([self._seg()], "/tmp/out")

    def test_cancela_entre_segmentos(self):
        import threading
        ev = threading.Event()

        procs = [_make_process([]), _make_process([])]
        call_count = []
        def fake_start(cmd, *a, **kw):
            ev.set()    # sinaliza após o primeiro subprocess ser iniciado
            p = procs[len(call_count)]
            call_count.append(1)
            return p

        segs = [self._seg(vid_id="a"), self._seg(vid_id="b")]
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=[]):
            with pytest.raises(OperacaoCancelada):
                self._dl().download(segs, "/tmp/out", cancel_event=ev)

    # -------------------------------------------------------------------
    # Retorno de AudioFile
    # -------------------------------------------------------------------

    def test_retorna_audio_files_encontrados(self):
        proc = _make_process([])
        mp3_files = ["/tmp/out/culto.mp3", "/tmp/out/culto2.mp3"]
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch("glob.glob", return_value=mp3_files):
            result = self._dl().download([self._seg()], "/tmp/out")
        assert len(result) == 2
        assert all(r.path in mp3_files for r in result)
