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
    """
    Testa YtDlpAudioDownloader com subprocessos mockados.

    O novo fluxo é MP4-first:
      1. Cria subpasta  output_dir/{título sanitizado}/
      2. Baixa MP4 via yt-dlp (stdout mockado)
      3. Salva thumbnail e descrição (_save_extras — mockado por padrão)
      4. Converte MP4 → MP3 via subprocess.run (mockado por padrão)
      5. Se save_video=False: remove MP4

    A maioria dos testes usa tmp_path para ter um diretório real,
    cria um MP4 fake e inclui a linha [Merger] no stdout do proc.
    """

    def _dl(self, *, save_video=False, metadata_fetcher=None):
        return YtDlpAudioDownloader(save_video=save_video,
                                    metadata_fetcher=metadata_fetcher)

    def _seg(self, vid_id="abc", title="Culto", start=None, end=None):
        return Segment(video_id=vid_id, title=title, start=start, end=end)

    def _make_mp4(self, tmp_path, title="Culto"):
        """Cria subpasta + MP4 fake mimicking what yt-dlp would produce."""
        from infrastructure.youtube.ytdlp_source import sanitize_folder_name
        safe      = sanitize_folder_name(title)
        subfolder = tmp_path / safe
        subfolder.mkdir(parents=True, exist_ok=True)
        mp4       = subfolder / f"{title}.mp4"
        mp4.write_bytes(b"fake-mp4-data")
        return mp4, subfolder

    def _run_ok(self):
        """MagicMock que simula subprocess.run com returncode=0."""
        return MagicMock(returncode=0, stderr="")

    # -------------------------------------------------------------------
    # Comando gerado pelo yt-dlp
    # -------------------------------------------------------------------

    def test_video_completo_sem_download_sections(self, tmp_path):
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download([self._seg()], str(tmp_path))
        assert "--download-sections" not in captured_cmd

    def test_trecho_adiciona_download_sections(self, tmp_path):
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            seg = self._seg(start="00:10:00", end="01:00:00")
            self._dl().download([seg], str(tmp_path))
        assert "--download-sections" in captured_cmd
        idx = captured_cmd.index("--download-sections")
        assert captured_cmd[idx + 1] == "*00:10:00-01:00:00"

    def test_formato_asterisco_no_trecho(self, tmp_path):
        """O trecho DEVE ter o prefixo '*' para o yt-dlp."""
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            seg = self._seg(start="00:05:00", end="00:30:00")
            self._dl().download([seg], str(tmp_path))
        idx = captured_cmd.index("--download-sections")
        assert captured_cmd[idx + 1].startswith("*")

    def test_ffmpeg_location_adicionado_quando_disponivel(self, tmp_path):
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value="/usr/bin"), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download([self._seg()], str(tmp_path))
        assert "--ffmpeg-location" in captured_cmd
        idx = captured_cmd.index("--ffmpeg-location")
        assert captured_cmd[idx + 1] == "/usr/bin"

    def test_sem_ffmpeg_nao_adiciona_flag(self, tmp_path):
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download([self._seg()], str(tmp_path))
        assert "--ffmpeg-location" not in captured_cmd

    def test_usa_formato_mp4_na_flag_f(self, tmp_path):
        """yt-dlp deve usar bestvideo+bestaudio com merge-output-format mp4."""
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        captured_cmd = []
        def fake_start(cmd, *a, **kw):
            captured_cmd.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download([self._seg()], str(tmp_path))
        assert "--merge-output-format" in captured_cmd
        idx = captured_cmd.index("--merge-output-format")
        assert captured_cmd[idx + 1] == "mp4"

    # -------------------------------------------------------------------
    # Subprocessos por vídeo
    # -------------------------------------------------------------------

    def test_um_subprocess_por_segmento(self, tmp_path):
        segs   = [self._seg(vid_id=str(i), title=f"V{i}") for i in range(3)]
        procs  = []
        for seg in segs:
            mp4, _ = self._make_mp4(tmp_path, title=seg.title)
            procs.append(_make_process([f'[Merger] Merging formats into "{mp4}"']))

        call_count = []
        proc_iter  = iter(procs)
        def fake_start(cmd, *a, **kw):
            call_count.append(1)
            return next(proc_iter)

        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download(segs, str(tmp_path))
        assert len(call_count) == 3

    # -------------------------------------------------------------------
    # Progresso
    # -------------------------------------------------------------------

    def test_progresso_intermediario_reportado(self, tmp_path):
        mp4, _ = self._make_mp4(tmp_path)
        lines  = [
            "[download]  50.0% of 100MB",
            f'[Merger] Merging formats into "{mp4}"',
        ]
        proc = _make_process(lines)
        progress_vals = []
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download(
                [self._seg()], str(tmp_path),
                on_progress=progress_vals.append,
            )
        assert any(0.0 < v < 1.0 for v in progress_vals)

    def test_progresso_completo_apos_conversao(self, tmp_path):
        """Após a conversão MP4→MP3, progresso deve atingir 1.0."""
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        progress_vals = []
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download(
                [self._seg()], str(tmp_path),
                on_progress=progress_vals.append,
            )
        assert 1.0 in progress_vals

    # -------------------------------------------------------------------
    # Erros e cancelamento
    # -------------------------------------------------------------------

    def test_levanta_runtime_error_quando_returncode_diferente_de_zero(self, tmp_path):
        proc = _make_process([], returncode=1)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"):
            with pytest.raises(RuntimeError, match="yt-dlp"):
                self._dl().download([self._seg()], str(tmp_path))

    def test_levanta_runtime_error_quando_mp4_nao_encontrado(self, tmp_path):
        """Se nenhum MP4 é encontrado após download, levanta RuntimeError."""
        proc = _make_process([])  # nenhuma linha [Merger] nem Destination
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"):
            with pytest.raises(RuntimeError, match="MP4"):
                self._dl().download([self._seg()], str(tmp_path))

    def test_cancela_entre_segmentos(self, tmp_path):
        import threading
        ev = threading.Event()

        procs = [_make_process([]), _make_process([])]
        call_count = []
        proc_iter  = iter(procs)
        def fake_start(cmd, *a, **kw):
            ev.set()    # sinaliza após o primeiro subprocess ser iniciado
            call_count.append(1)
            return next(proc_iter)

        segs = [self._seg(vid_id="a"), self._seg(vid_id="b")]
        with patch("infrastructure.youtube.ytdlp_source.start_process", side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None):
            with pytest.raises(OperacaoCancelada):
                self._dl().download(segs, str(tmp_path), cancel_event=ev)

    # -------------------------------------------------------------------
    # Retorno de AudioFile e subfolder
    # -------------------------------------------------------------------

    def test_retorna_audio_file_com_path_mp3(self, tmp_path):
        """AudioFile retornado aponta para o MP3 derivado do MP4."""
        mp4, _   = self._make_mp4(tmp_path, "Culto")
        mp3_path = mp4.with_suffix(".mp3")
        proc     = _make_process([f'[Merger] Merging formats into "{mp4}"'])

        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = self._dl().download(
                [self._seg(vid_id="abc123", title="Culto")],
                str(tmp_path),
            )

        assert len(result) == 1
        assert result[0].path == str(mp3_path)
        assert result[0].video_id == "abc123"

    def test_audio_file_tem_subfolder_preenchido(self, tmp_path):
        """AudioFile.subfolder aponta para a subpasta criada para o segmento."""
        mp4, subfolder = self._make_mp4(tmp_path, "Culto")
        proc           = _make_process([f'[Merger] Merging formats into "{mp4}"'])

        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = self._dl().download(
                [self._seg(vid_id="abc123", title="Culto")],
                str(tmp_path),
            )

        assert result[0].subfolder == str(subfolder)

    def test_video_id_preservado_para_cada_segment(self, tmp_path):
        """Multi-segment: cada AudioFile traz o video_id do seu Segment."""
        mp4_a, _ = self._make_mp4(tmp_path, "CultoA")
        mp4_b, _ = self._make_mp4(tmp_path, "CultoB")

        procs = [
            _make_process([f'[Merger] Merging formats into "{mp4_a}"']),
            _make_process([f'[Merger] Merging formats into "{mp4_b}"']),
        ]
        proc_iter = iter(procs)

        segs = [self._seg(vid_id="aaa", title="CultoA"),
                self._seg(vid_id="bbb", title="CultoB")]

        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=lambda *a, **k: next(proc_iter)), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = self._dl().download(segs, str(tmp_path))

        assert [r.video_id for r in result] == ["aaa", "bbb"]

    def test_ordem_de_retorno_segue_ordem_dos_segments(self, tmp_path):
        """Ordem do retorno segue a ordem dos segments fornecidos."""
        mp4_z, _ = self._make_mp4(tmp_path, "Z_primeiro")
        mp4_a, _ = self._make_mp4(tmp_path, "A_segundo")

        procs = [
            _make_process([f'[Merger] Merging formats into "{mp4_z}"']),
            _make_process([f'[Merger] Merging formats into "{mp4_a}"']),
        ]
        proc_iter = iter(procs)

        segs = [self._seg(vid_id="primeiro", title="Z_primeiro"),
                self._seg(vid_id="segundo",  title="A_segundo")]

        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=lambda *a, **k: next(proc_iter)), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = self._dl().download(segs, str(tmp_path))

        # Z primeiro, A segundo — ordem dos segments, não ordem alfabética
        assert [r.video_id for r in result] == ["primeiro", "segundo"]

    def test_nao_pega_arquivos_preexistentes_de_outros_segmentos(self, tmp_path):
        """
        Regressão B1 (updated): com subpastas por segmento, arquivos de outros
        segmentos NÃO afetam a resolução do MP4 atual (cada um tem sua própria pasta).
        """
        # Pré-existentes em root (de runs anteriores sem subpasta)
        (tmp_path / "antigo.mp3").write_bytes(b"velho")

        mp4, _ = self._make_mp4(tmp_path, "Culto novo")
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])

        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = self._dl().download(
                [self._seg(title="Culto novo")],
                str(tmp_path),
            )

        assert len(result) == 1
        assert result[0].path.endswith(".mp3")
        # Resultado está dentro da subpasta, não na raiz
        assert str(tmp_path / "antigo.mp3") != result[0].path

    # -------------------------------------------------------------------
    # Resolução de path MP4 (fallbacks)
    # -------------------------------------------------------------------

    def test_usa_destination_quando_merger_ausente(self, tmp_path):
        """Se não há linha [Merger], usa [download] Destination: *.mp4."""
        mp4, _ = self._make_mp4(tmp_path, "Culto")
        proc   = _make_process([f"[download] Destination: {mp4}"])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = self._dl().download([self._seg(title="Culto")], str(tmp_path))
        assert result[0].path.endswith(".mp3")

    def test_usa_glob_quando_merger_e_destination_ausentes(self, tmp_path):
        """Fallback para glob *.mp4 dentro da subpasta quando nenhuma linha de destino existe."""
        mp4, _ = self._make_mp4(tmp_path, "Culto")
        proc   = _make_process([])  # nenhuma linha de destino
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            result = self._dl().download([self._seg(title="Culto")], str(tmp_path))
        assert result[0].path.endswith(".mp3")

    # -------------------------------------------------------------------
    # save_video flag
    # -------------------------------------------------------------------

    def test_remove_mp4_quando_save_video_false(self, tmp_path):
        """Quando save_video=False (default), o MP4 deve ser removido."""
        mp4, _ = self._make_mp4(tmp_path, "Culto")
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl(save_video=False).download([self._seg(title="Culto")], str(tmp_path))
        assert not mp4.exists()

    def test_mantem_mp4_quando_save_video_true(self, tmp_path):
        """Quando save_video=True, o MP4 deve ser mantido."""
        mp4, _ = self._make_mp4(tmp_path, "Culto")
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl(save_video=True).download([self._seg(title="Culto")], str(tmp_path))
        assert mp4.exists()

    def test_save_video_false_por_padrao(self):
        """save_video=False é o padrão."""
        assert self._dl()._save_video is False

    # -------------------------------------------------------------------
    # Mudanças de sessão — progresso multi-segmento e status messages
    # -------------------------------------------------------------------

    def test_progresso_monotico_para_dois_segmentos(self, tmp_path):
        """
        Mudança de sessão: com N=2 segmentos o progresso nunca deve regredir —
        o slot de cada segmento é (idx + …) / total, garantindo monotonicidade.
        """
        mp4_a, _ = self._make_mp4(tmp_path, "CultoA")
        mp4_b, _ = self._make_mp4(tmp_path, "CultoB")

        lines_a = [
            "[download]  30.0% of 100MB",
            "[download]  80.0% of 100MB",
            f'[Merger] Merging formats into "{mp4_a}"',
        ]
        lines_b = [
            "[download]  50.0% of 100MB",
            f'[Merger] Merging formats into "{mp4_b}"',
        ]
        procs = [_make_process(lines_a), _make_process(lines_b)]
        proc_iter = iter(procs)

        progress_vals: list = []
        segs = [
            self._seg(vid_id="a", title="CultoA"),
            self._seg(vid_id="b", title="CultoB"),
        ]

        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=lambda *a, **k: next(proc_iter)), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download(segs, str(tmp_path),
                                on_progress=progress_vals.append)

        assert progress_vals, "Nenhum progresso reportado"
        # Monotonicidade: nenhum valor pode ser menor que o anterior
        for a, b in zip(progress_vals, progress_vals[1:]):
            assert a <= b, f"Progresso regrediu: {a:.3f} → {b:.3f}"
        # Deve terminar em 1.0
        assert progress_vals[-1] == pytest.approx(1.0)

    def test_status_convertendo_emitido_pelo_downloader(self, tmp_path):
        """
        Mudança de sessão: o downloader deve emitir status "Convertendo para MP3..."
        (usado pela GUI para iniciar a animação da convert_bar).
        """
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        statuses: list = []

        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download(
                [self._seg()], str(tmp_path),
                on_status=statuses.append,
            )

        assert any("Convertendo" in s for s in statuses), \
            f"Esperado status 'Convertendo...' entre: {statuses}"

    def test_status_salvando_metadados_emitido(self, tmp_path):
        """
        Mudança de sessão: o downloader deve emitir status "Salvando metadados..."
        antes de chamar _save_extras.
        """
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        statuses: list = []

        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir", return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download(
                [self._seg()], str(tmp_path),
                on_status=statuses.append,
            )

        assert any("metadados" in s.lower() for s in statuses), \
            f"Esperado status com 'metadados' entre: {statuses}"

    # ------------------------------------------------------------------
    # --write-description e captura de descricao.txt
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Qualidade do vídeo
    # ------------------------------------------------------------------

    def _captured_cmd(self, tmp_path, *, video_quality="alta"):
        """Retorna o comando yt-dlp capturado para o dado video_quality."""
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        captured: list = []
        def fake_start(cmd, *a, **kw):
            captured.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir",
                   return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            YtDlpAudioDownloader(video_quality=video_quality).download(
                [self._seg()], str(tmp_path)
            )
        return captured

    def test_qualidade_alta_usa_bestvideo(self, tmp_path):
        cmd = self._captured_cmd(tmp_path, video_quality="alta")
        idx = cmd.index("-f")
        assert "bestvideo" in cmd[idx + 1]

    def test_qualidade_baixa_usa_worstvideo(self, tmp_path):
        cmd = self._captured_cmd(tmp_path, video_quality="baixa")
        idx = cmd.index("-f")
        assert "worstvideo" in cmd[idx + 1]

    def test_qualidade_default_e_alta(self, tmp_path):
        cmd = self._captured_cmd(tmp_path)   # sem video_quality → default
        idx = cmd.index("-f")
        assert "bestvideo" in cmd[idx + 1]

    def test_write_description_no_comando_ytdlp(self, tmp_path):
        """Regressão: --write-description deve estar no comando de download."""
        mp4, _ = self._make_mp4(tmp_path)
        proc   = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        captured: list = []
        def fake_start(cmd, *a, **kw):
            captured.extend(cmd)
            return proc
        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=fake_start), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir",
                   return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download([self._seg()], str(tmp_path))
        assert "--write-description" in captured

    def test_description_file_renomeado_para_descricao_txt(self, tmp_path):
        """Arquivo .description gerado pelo yt-dlp deve virar descricao.txt."""
        mp4, subfolder = self._make_mp4(tmp_path)          # cria tmp_path/Culto/
        # Simula o arquivo .description criado pelo yt-dlp
        desc_file = subfolder / "Culto.description"
        desc_file.write_text("Descrição do culto.", encoding="utf-8")

        proc = _make_process([f'[Merger] Merging formats into "{mp4}"'])
        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   return_value=proc), \
             patch("infrastructure.youtube.ytdlp_source.ffmpeg_dir",
                   return_value=None), \
             patch.object(YtDlpAudioDownloader, "_save_extras"), \
             patch("subprocess.run", return_value=self._run_ok()):
            self._dl().download([self._seg()], str(tmp_path))

        txt = subfolder / "descricao.txt"
        assert txt.exists(), "descricao.txt deve ser criado após renomear .description"
        assert txt.read_text(encoding="utf-8") == "Descrição do culto."
        assert not desc_file.exists(), ".description deve ser removido após renomear"

    def test_save_extras_nao_chama_fetcher_quando_descricao_txt_existe(self, tmp_path):
        """_save_extras não deve chamar metadata_fetcher se descricao.txt já existir."""
        subfolder = tmp_path / "video"
        subfolder.mkdir()
        (subfolder / "descricao.txt").write_text("já existe", encoding="utf-8")

        fetcher = MagicMock(return_value={"description": "nova", "thumbnail_url": ""})
        dl = YtDlpAudioDownloader(metadata_fetcher=fetcher)
        # urllib é importado dentro do try da thumbnail — deixa falhar silenciosamente
        with patch("urllib.request.urlopen", side_effect=Exception("sem rede")):
            dl._save_extras("vid123", str(subfolder))

        fetcher.assert_not_called()
        assert (subfolder / "descricao.txt").read_text(encoding="utf-8") == "já existe"

    def test_save_extras_chama_fetcher_como_fallback_quando_sem_descricao(self, tmp_path):
        """_save_extras chama metadata_fetcher se descricao.txt não existe."""
        subfolder = tmp_path / "video"
        subfolder.mkdir()

        fetcher = MagicMock(return_value={"description": "descrição do fallback",
                                          "thumbnail_url": ""})
        dl = YtDlpAudioDownloader(metadata_fetcher=fetcher)
        with patch("urllib.request.urlopen", side_effect=Exception("sem rede")):
            dl._save_extras("vid123", str(subfolder))

        fetcher.assert_called_once_with("vid123")
        assert (subfolder / "descricao.txt").read_text(encoding="utf-8") \
            == "descrição do fallback"


# ===========================================================================
# YtDlpVideoSource — get_chapters / _seconds_to_hms
# ===========================================================================

class TestYtDlpVideoSourceGetChapters:
    """Testa get_chapters com stdout mockado (sem rede)."""

    def _source(self):
        return YtDlpVideoSource()

    def _make_dump_json(self, chapters=None, duration=3600):
        import json as _json
        data = {"duration": duration, "chapters": chapters or []}
        proc = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.read = MagicMock(return_value=_json.dumps(data))
        proc.returncode = 0
        proc.wait = MagicMock(return_value=0)
        return proc

    def test_retorna_lista_com_capitulos(self):
        proc = self._make_dump_json(chapters=[
            {"title": "Introdução", "start_time": 0.0,    "end_time": 600.0},
            {"title": "Sermão",     "start_time": 600.0,  "end_time": 3600.0},
        ])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            chapters = self._source().get_chapters("abc123")
        assert len(chapters) == 2
        assert chapters[0]["title"] == "Introdução"
        assert chapters[0]["start"] == "00:00:00"
        assert chapters[0]["end"]   == "00:10:00"
        assert chapters[1]["title"] == "Sermão"
        assert chapters[1]["start"] == "00:10:00"
        assert chapters[1]["end"]   == "01:00:00"

    def test_retorna_lista_vazia_sem_capitulos(self):
        proc = self._make_dump_json(chapters=[])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            chapters = self._source().get_chapters("abc123")
        assert chapters == []

    def test_retorna_lista_vazia_quando_ytdlp_falha(self):
        proc = self._make_dump_json()
        proc.returncode = 1
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            chapters = self._source().get_chapters("abc123")
        assert chapters == []

    def test_retorna_lista_vazia_quando_json_invalido(self):
        proc = MagicMock()
        proc.stdout.read = MagicMock(return_value="nao e json")
        proc.returncode = 0
        proc.wait = MagicMock(return_value=0)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            chapters = self._source().get_chapters("abc123")
        assert chapters == []

    def test_end_time_ausente_usa_start_do_proximo(self):
        proc = self._make_dump_json(chapters=[
            {"title": "A", "start_time": 0.0},
            {"title": "B", "start_time": 300.0},
        ], duration=600)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            chapters = self._source().get_chapters("abc123")
        assert chapters[0]["end"] == "00:05:00"

    def test_end_time_ultimo_capitulo_usa_duracao_total(self):
        proc = self._make_dump_json(chapters=[
            {"title": "A", "start_time": 0.0},
        ], duration=1800)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            chapters = self._source().get_chapters("abc123")
        assert chapters[0]["end"] == "00:30:00"

    def test_repassa_cancel_event_para_start_process(self):
        import threading
        ev = threading.Event()
        proc = self._make_dump_json(chapters=[])
        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   return_value=proc) as mock_sp:
            self._source().get_chapters("abc123", cancel_event=ev)
        mock_sp.assert_called_once()
        assert mock_sp.call_args.args[1] is ev

    def test_on_log_chamado_com_mensagem(self):
        proc = self._make_dump_json(chapters=[])
        logs = []
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            self._source().get_chapters("abc123", on_log=logs.append)
        assert any("abc123" in m for m in logs)


# ===========================================================================
# extract_video_id
# ===========================================================================

class TestExtractVideoId:
    """Formatos de link aceitos pelo modo 'link do vídeo' da tela Processar."""

    def _extract(self, url):
        from infrastructure.youtube.ytdlp_source import extract_video_id
        return extract_video_id(url)

    def test_watch_url_padrao(self):
        assert self._extract(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_watch_url_com_parametros_extras(self):
        assert self._extract(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=120s&list=PL123"
        ) == "dQw4w9WgXcQ"

    def test_youtu_be_curto(self):
        assert self._extract("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_youtu_be_com_query_si(self):
        assert self._extract(
            "https://youtu.be/dQw4w9WgXcQ?si=AbCdEfGhIjK"
        ) == "dQw4w9WgXcQ"

    def test_url_de_live(self):
        # Formato usado pelas transmissões dos cultos
        assert self._extract(
            "https://www.youtube.com/live/dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_url_de_shorts(self):
        assert self._extract(
            "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_url_de_embed(self):
        assert self._extract(
            "https://www.youtube.com/embed/dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_sem_esquema(self):
        assert self._extract("youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_mobile_e_music(self):
        assert self._extract(
            "https://m.youtube.com/watch?v=dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"
        assert self._extract(
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
        ) == "dQw4w9WgXcQ"

    def test_id_cru_de_11_caracteres(self):
        assert self._extract("dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_espacos_em_volta_sao_ignorados(self):
        assert self._extract(
            "  https://www.youtube.com/watch?v=dQw4w9WgXcQ  "
        ) == "dQw4w9WgXcQ"

    def test_vazio_e_none_retornam_none(self):
        assert self._extract("") is None
        assert self._extract(None) is None

    def test_outro_dominio_retorna_none(self):
        assert self._extract("https://vimeo.com/watch?v=dQw4w9WgXcQ") is None

    def test_url_de_canal_retorna_none(self):
        assert self._extract("https://www.youtube.com/@IPMadalena/streams") is None

    def test_id_com_tamanho_errado_retorna_none(self):
        assert self._extract("https://www.youtube.com/watch?v=curto") is None

    def test_texto_arbitrario_retorna_none(self):
        assert self._extract("culto de domingo") is None


# ===========================================================================
# YtDlpVideoSource.fetch_video
# ===========================================================================

class TestYtDlpVideoSourceFetchVideo:
    """Busca de um vídeo específico por link (subprocess mockado)."""

    URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def _source(self):
        return YtDlpVideoSource()

    def test_retorna_video_com_dados_do_yt_dlp(self):
        proc = _make_process(["dQw4w9WgXcQ|||Culto de Domingo|||20260419"])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            video = self._source().fetch_video(self.URL)
        assert isinstance(video, Video)
        assert video.id == "dQw4w9WgXcQ"
        assert video.title == "Culto de Domingo"
        assert video.upload_date == "20260419"

    def test_link_invalido_levanta_video_nao_encontrado_sem_subprocess(self):
        with patch("infrastructure.youtube.ytdlp_source.start_process") as mock_sp:
            with pytest.raises(VideoNaoEncontrado):
                self._source().fetch_video("https://exemplo.com/nada")
        mock_sp.assert_not_called()

    def test_usa_no_playlist_e_url_canonica(self):
        proc = _make_process(["dQw4w9WgXcQ|||Culto|||20260419"])
        captured = []

        def fake_start(cmd, *a, **kw):
            captured.extend(cmd)
            return proc

        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=fake_start):
            # link com &list= — sem --no-playlist o yt-dlp baixaria a playlist
            self._source().fetch_video(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLabc"
            )
        assert "--no-playlist" in captured
        assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in captured

    def test_sem_saida_levanta_video_nao_encontrado(self):
        proc = _make_process([])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            with pytest.raises(VideoNaoEncontrado):
                self._source().fetch_video(self.URL)

    def test_returncode_diferente_de_zero_levanta(self):
        proc = _make_process(
            ["dQw4w9WgXcQ|||Culto|||20260419"], returncode=1
        )
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            with pytest.raises(VideoNaoEncontrado):
                self._source().fetch_video(self.URL)

    def test_upload_date_indisponivel_vira_string_vazia(self):
        # yt-dlp imprime "NA" quando o campo não existe
        proc = _make_process(["dQw4w9WgXcQ|||Culto|||NA"])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            video = self._source().fetch_video(self.URL)
        assert video.upload_date == ""

    def test_ignora_linhas_sem_separador(self):
        proc = _make_process([
            "[youtube] dQw4w9WgXcQ: Downloading webpage",
            "dQw4w9WgXcQ|||Culto|||20260419",
        ])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            video = self._source().fetch_video(self.URL)
        assert video.title == "Culto"

    def test_usa_a_primeira_linha_quando_ha_varias(self):
        proc = _make_process([
            "dQw4w9WgXcQ|||Primeiro|||20260419",
            "outro123456|||Segundo|||20260420",
        ])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            video = self._source().fetch_video(self.URL)
        assert video.title == "Primeiro"

    def test_chama_on_log_e_on_status(self):
        proc = _make_process(["dQw4w9WgXcQ|||Culto|||20260419"])
        logs, status = [], []
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            self._source().fetch_video(
                self.URL, on_log=logs.append, on_status=status.append
            )
        assert any("Buscando" in m for m in status)
        assert any("Culto" in m for m in logs)

    def test_repassa_cancel_event_ao_start_process(self):
        import threading
        ev = threading.Event()
        proc = _make_process(["dQw4w9WgXcQ|||Culto|||20260419"])
        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   return_value=proc) as mock_sp:
            self._source().fetch_video(self.URL, cancel_event=ev)
        assert mock_sp.call_args.args[1] is ev

    def test_cancelamento_levanta_operacao_cancelada(self):
        import threading
        ev = threading.Event()
        ev.set()
        proc = _make_process(["dQw4w9WgXcQ|||Culto|||20260419"])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            with pytest.raises(OperacaoCancelada):
                self._source().fetch_video(self.URL, cancel_event=ev)

    def test_aceita_id_cru(self):
        proc = _make_process(["dQw4w9WgXcQ|||Culto|||20260419"])
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            video = self._source().fetch_video("dQw4w9WgXcQ")
        assert video.id == "dQw4w9WgXcQ"


class TestSecondsToHms:
    def test_zero(self):
        from infrastructure.youtube.ytdlp_source import _seconds_to_hms
        assert _seconds_to_hms(0) == "00:00:00"

    def test_exato_uma_hora(self):
        from infrastructure.youtube.ytdlp_source import _seconds_to_hms
        assert _seconds_to_hms(3600) == "01:00:00"

    def test_valores_mistos(self):
        from infrastructure.youtube.ytdlp_source import _seconds_to_hms
        assert _seconds_to_hms(3661) == "01:01:01"

    def test_trunca_fracao_de_segundo(self):
        from infrastructure.youtube.ytdlp_source import _seconds_to_hms
        assert _seconds_to_hms(59.9) == "00:00:59"


# ===========================================================================
# fetch_video_metadata
# ===========================================================================

class TestFetchVideoMetadata:
    """Testa fetch_video_metadata com subprocess mockado."""

    def _make_proc(self, payload: str, returncode: int = 0) -> MagicMock:
        proc = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.read = MagicMock(return_value=payload)
        proc.returncode = returncode
        proc.wait = MagicMock(return_value=returncode)
        return proc

    def _valid_json(self, description="Descrição do culto.", thumbnail="https://img.yt/thumb.jpg"):
        import json as _json
        return _json.dumps({"description": description, "thumbnail": thumbnail})

    def test_retorna_description_do_json(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        proc = self._make_proc(self._valid_json(description="Texto da descrição."))
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            result = fetch_video_metadata("abc123")
        assert result["description"] == "Texto da descrição."

    def test_retorna_thumbnail_url_do_json(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        proc = self._make_proc(self._valid_json(thumbnail="https://img.yt/hq.jpg"))
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            result = fetch_video_metadata("abc123")
        assert result["thumbnail_url"] == "https://img.yt/hq.jpg"

    def test_retorna_dict_vazio_quando_returncode_nao_zero(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        proc = self._make_proc(self._valid_json(), returncode=1)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            result = fetch_video_metadata("abc123")
        assert result == {"description": "", "thumbnail_url": ""}

    def test_retorna_dict_vazio_quando_json_invalido(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        proc = self._make_proc("isso nao e json")
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            result = fetch_video_metadata("abc123")
        assert result == {"description": "", "thumbnail_url": ""}

    def test_parseia_json_mesmo_com_warnings_antes(self):
        """Regressão: warnings do yt-dlp misturados antes do JSON não devem
        quebrar o parsing (start_process redireciona stderr → stdout)."""
        import json as _json
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        json_line = _json.dumps({"description": "Culto da manhã.", "thumbnail": "http://t.jpg"})
        # Simula output real do yt-dlp: warnings/info antes do JSON
        mixed_output = (
            "[youtube] Extracting URL: https://www.youtube.com/watch?v=abc\n"
            "[youtube] abc: Downloading webpage\n"
            "WARNING: [youtube] Formato indisponível\n"
            f"{json_line}\n"
        )
        proc = self._make_proc(mixed_output)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            result = fetch_video_metadata("abc123")
        assert result["description"] == "Culto da manhã."
        assert result["thumbnail_url"] == "http://t.jpg"

    def test_retorna_dict_vazio_quando_subprocess_lanca_excecao(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=RuntimeError("erro de rede")):
            result = fetch_video_metadata("abc123")
        assert result == {"description": "", "thumbnail_url": ""}

    def test_usa_extractor_args_ios_android_web(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        proc = self._make_proc(self._valid_json())
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc) as sp:
            fetch_video_metadata("abc123")
        cmd = sp.call_args.args[0]
        assert "--extractor-args" in cmd
        idx = cmd.index("--extractor-args")
        assert "ios,android,web" in cmd[idx + 1]

    def test_usa_flag_j(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        proc = self._make_proc(self._valid_json())
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc) as sp:
            fetch_video_metadata("abc123")
        cmd = sp.call_args.args[0]
        assert "-j" in cmd

    def test_url_construida_com_video_id(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_metadata
        proc = self._make_proc(self._valid_json())
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc) as sp:
            fetch_video_metadata("MYVIDEOID")
        cmd = sp.call_args.args[0]
        assert "https://www.youtube.com/watch?v=MYVIDEOID" in cmd


# ===========================================================================
# fetch_video_description (compat wrapper)
# ===========================================================================

class TestFetchVideoDescription:
    """Testa o wrapper de compatibilidade fetch_video_description."""

    def _make_proc(self, payload: str, returncode: int = 0) -> MagicMock:
        import json as _json
        proc = MagicMock()
        proc.stdout = MagicMock()
        proc.stdout.read = MagicMock(return_value=payload)
        proc.returncode = returncode
        proc.wait = MagicMock(return_value=returncode)
        return proc

    def test_retorna_descricao_quando_sucesso(self):
        import json as _json
        from infrastructure.youtube.ytdlp_source import fetch_video_description
        payload = _json.dumps({"description": "Descrição do culto.\nSegunda linha.", "thumbnail": ""})
        proc = self._make_proc(payload)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            result = fetch_video_description("dQw4w9WgXcQ")
        assert result == "Descrição do culto.\nSegunda linha."

    def test_retorna_vazio_quando_returncode_diferente_de_zero(self):
        import json as _json
        from infrastructure.youtube.ytdlp_source import fetch_video_description
        payload = _json.dumps({"description": "qualquer coisa", "thumbnail": ""})
        proc = self._make_proc(payload, returncode=1)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc):
            result = fetch_video_description("abc123")
        assert result == ""

    def test_retorna_vazio_quando_subprocess_lanca_excecao(self):
        from infrastructure.youtube.ytdlp_source import fetch_video_description
        with patch("infrastructure.youtube.ytdlp_source.start_process",
                   side_effect=RuntimeError("erro de rede")):
            result = fetch_video_description("abc123")
        assert result == ""

    def test_usa_skip_download(self):
        import json as _json
        from infrastructure.youtube.ytdlp_source import fetch_video_description
        payload = _json.dumps({"description": "desc", "thumbnail": ""})
        proc = self._make_proc(payload)
        with patch("infrastructure.youtube.ytdlp_source.start_process", return_value=proc) as sp:
            fetch_video_description("xyz")
        cmd = sp.call_args.args[0]
        assert "--skip-download" in cmd


# ===========================================================================
# sanitize_folder_name
# ===========================================================================

class TestSanitizeFolderName:
    """Testa a função de sanitização de nomes de pasta."""

    def _s(self, title: str) -> str:
        from infrastructure.youtube.ytdlp_source import sanitize_folder_name
        return sanitize_folder_name(title)

    def test_remove_dois_pontos(self):
        assert ":" not in self._s("Culto: Domingo de Páscoa")

    def test_remove_barra(self):
        assert "/" not in self._s("a/b")

    def test_remove_barra_invertida(self):
        assert "\\" not in self._s("a\\b")

    def test_remove_asterisco(self):
        assert "*" not in self._s("culto * especial")

    def test_remove_interrogacao(self):
        assert "?" not in self._s("culto?")

    def test_remove_angulo(self):
        result = self._s("a<b>c")
        assert "<" not in result and ">" not in result

    def test_remove_pipe(self):
        assert "|" not in self._s("a|b")

    def test_remove_aspas(self):
        assert '"' not in self._s('diz "amém"')

    def test_colapsa_espacos_multiplos(self):
        assert "  " not in self._s("culto   domingo")

    def test_trunca_a_150_chars(self):
        long_title = "a" * 200
        assert len(self._s(long_title)) == 150

    def test_titulo_vazio_retorna_video(self):
        assert self._s("") == "video"

    def test_titulo_so_caracteres_proibidos_retorna_video(self):
        assert self._s("///:::***") == "video"

    def test_preserva_acentos_e_unicode(self):
        result = self._s("Culto de Páscoa 2026")
        assert "Páscoa" in result

    def test_remove_ponto_e_espaco_no_final(self):
        assert not self._s("culto.").endswith(".")
        assert not self._s("culto ").endswith(" ")

    def test_preserva_caracteres_permitidos(self):
        result = self._s("Culto Domingo 19-04-2026")
        assert "Domingo" in result
        assert "19-04-2026" in result


# ===========================================================================
# YtDlpAudioDownloader._save_extras
# ===========================================================================

class TestSaveExtras:
    """
    Testa _save_extras — operações best-effort de thumbnail e descrição.
    urllib.request.urlopen é mockado para evitar rede real.
    """

    def _dl(self, metadata_fetcher=None):
        return YtDlpAudioDownloader(metadata_fetcher=metadata_fetcher)

    def _fake_response(self, data: bytes):
        """Mock de resposta HTTP que devolve `data` em .read()."""
        resp = MagicMock()
        resp.read.return_value = data
        resp.__enter__ = lambda s: resp
        resp.__exit__  = MagicMock(return_value=False)
        return resp

    def test_salva_capa_jpg_quando_cdn_retorna_dados_validos(self, tmp_path):
        resp = self._fake_response(b"x" * 600)  # > 500 bytes
        with patch("urllib.request.urlopen", return_value=resp), \
             patch("ssl.create_default_context"):
            self._dl()._save_extras("abc123", str(tmp_path))
        assert (tmp_path / "capa.jpg").exists()
        assert len((tmp_path / "capa.jpg").read_bytes()) == 600

    def test_nao_salva_capa_quando_cdn_retorna_poucos_bytes(self, tmp_path):
        """Dados < 500 bytes são descartados (placeholder de 404)."""
        resp = self._fake_response(b"x" * 200)  # < 500 bytes
        with patch("urllib.request.urlopen", return_value=resp), \
             patch("ssl.create_default_context"):
            self._dl()._save_extras("abc123", str(tmp_path))
        assert not (tmp_path / "capa.jpg").exists()

    def test_salva_descricao_txt_quando_metadata_fetcher_disponivel(self, tmp_path):
        mock_fetcher = MagicMock(return_value={
            "description": "Culto de domingo 2026.", "thumbnail_url": ""
        })
        with patch("urllib.request.urlopen", side_effect=Exception("sem rede")):
            self._dl(metadata_fetcher=mock_fetcher)._save_extras("abc123", str(tmp_path))
        assert (tmp_path / "descricao.txt").exists()
        assert (tmp_path / "descricao.txt").read_text(encoding="utf-8") == "Culto de domingo 2026."

    def test_nao_salva_descricao_sem_metadata_fetcher(self, tmp_path):
        with patch("urllib.request.urlopen", side_effect=Exception("sem rede")):
            self._dl(metadata_fetcher=None)._save_extras("abc123", str(tmp_path))
        assert not (tmp_path / "descricao.txt").exists()

    def test_nao_lanca_excecao_em_falha_de_rede(self, tmp_path):
        """Falhas de rede são silenciadas (best-effort)."""
        mock_fetcher = MagicMock(side_effect=RuntimeError("sem rede"))
        with patch("urllib.request.urlopen", side_effect=RuntimeError("sem rede")):
            # Não deve lançar exceção
            self._dl(metadata_fetcher=mock_fetcher)._save_extras("abc123", str(tmp_path))

    def test_nao_salva_descricao_quando_texto_vazio(self, tmp_path):
        """Descrição vazia não gera arquivo."""
        mock_fetcher = MagicMock(return_value={"description": "", "thumbnail_url": ""})
        with patch("urllib.request.urlopen", side_effect=Exception("sem rede")):
            self._dl(metadata_fetcher=mock_fetcher)._save_extras("abc123", str(tmp_path))
        assert not (tmp_path / "descricao.txt").exists()


# ===========================================================================
# YtDlpAudioDownloader._convert_to_mp3
# ===========================================================================

class TestConvertToMp3:
    """Testa _convert_to_mp3 com subprocess.run mockado."""

    def test_chama_ffmpeg_com_flags_corretos(self, tmp_path):
        mp4 = tmp_path / "video.mp4"
        mp4.write_bytes(b"fake-mp4")
        mp3 = tmp_path / "video.mp3"

        dl = YtDlpAudioDownloader()
        captured = []
        def fake_run(cmd, **kwargs):
            captured.extend(cmd)
            return MagicMock(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            dl._convert_to_mp3(str(mp4), str(mp3))

        assert "-i"   in captured
        assert str(mp4) in captured
        assert "-vn"  in captured
        assert "-f"   in captured
        idx = captured.index("-f")
        assert captured[idx + 1] == "mp3"
        assert str(mp3) in captured

    def test_levanta_runtime_error_quando_ffmpeg_falha(self, tmp_path):
        mp4 = tmp_path / "video.mp4"
        mp4.write_bytes(b"fake-mp4")
        mp3 = tmp_path / "video.mp3"

        dl = YtDlpAudioDownloader()
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="ffmpeg error")):
            with pytest.raises(RuntimeError, match="ffmpeg"):
                dl._convert_to_mp3(str(mp4), str(mp3))

    def test_usa_ffdir_quando_disponivel(self, tmp_path):
        mp4 = tmp_path / "video.mp4"
        mp4.write_bytes(b"fake-mp4")
        mp3 = tmp_path / "video.mp3"

        dl = YtDlpAudioDownloader()
        captured = []
        def fake_run(cmd, **kwargs):
            captured.extend(cmd)
            return MagicMock(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=fake_run), \
             patch("os.path.exists", return_value=True):
            dl._convert_to_mp3(str(mp4), str(mp3), ffdir="/usr/bin")

        # O primeiro token do comando deve ser o caminho do ffmpeg com o ffdir
        assert "/usr/bin" in captured[0]

    def test_usa_ffmpeg_literal_sem_ffdir(self, tmp_path):
        mp4 = tmp_path / "video.mp4"
        mp4.write_bytes(b"fake-mp4")
        mp3 = tmp_path / "video.mp3"

        dl = YtDlpAudioDownloader()
        captured = []
        def fake_run(cmd, **kwargs):
            captured.extend(cmd)
            return MagicMock(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=fake_run):
            dl._convert_to_mp3(str(mp4), str(mp3))

        assert captured[0] == "ffmpeg"

    def test_on_log_chamado_com_mensagem_de_conversao(self, tmp_path):
        mp4 = tmp_path / "video.mp4"
        mp4.write_bytes(b"fake-mp4")
        mp3 = tmp_path / "video.mp3"

        dl   = YtDlpAudioDownloader()
        logs = []
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stderr="")):
            dl._convert_to_mp3(str(mp4), str(mp3), on_log=logs.append)

        assert any("MP3" in m or "Conver" in m for m in logs)
