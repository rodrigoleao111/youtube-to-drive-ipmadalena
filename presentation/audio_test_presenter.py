"""
AudioTestPresenter — orquestra a geração de um preview de áudio editado.

Recebe:
  - sample_path: arquivo de exemplo escolhido pelo usuário
  - preview_output_path: onde gravar o resultado (ex.: downloads/_test_preview.mp3)
  - config: AudioEditConfig montado a partir do estado ATUAL da UI (ainda não
    persistido em config.json — usuário pode testar antes de salvar)

Estratégia:
  1. Copia sample_path → preview_output_path (preserva o original do usuário).
  2. Chama IAudioEditor.process() no preview, que substitui in-place.
  3. Quando `config.has_any_filter_enabled` é False, retorna a cópia sem
     filtros aplicados (com aviso no log).

Não conhece UI — a View chama `execute()` de uma thread e fornece callbacks.
A marshalling para a thread da UI é responsabilidade da View.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from dataclasses import dataclass
from typing import Callable, Optional

from domain.entities import AudioEditConfig, AudioFile
from domain.ports import IAudioEditor


def _noop(*_a, **_kw):
    pass


# Logger compartilhado com o FfmpegAudioEditor — mensagens vão para o
# arquivo `logs/DD-MM-YYYY.log` (configurado em app._setup_file_logging).
_log = logging.getLogger("audio_edit")


@dataclass
class AudioTestPresenter:
    """
    Compõe IAudioEditor para gerar um arquivo de preview a partir de um
    arquivo de exemplo do usuário, sem alterar o original.

    Uso típico:
        presenter = AudioTestPresenter(editor=FfmpegAudioEditor())
        presenter.execute(
            sample_path="C:/Users/me/Downloads/exemplo.mp3",
            preview_output_path="downloads/_test_preview.mp3",
            config=audio_edit_config,
            on_log=lambda m: ...,
            on_progress=lambda p: ...,
        )
    """

    editor: IAudioEditor

    def execute(
        self,
        sample_path: str,
        preview_output_path: str,
        config: AudioEditConfig,
        *,
        cancel_event=None,
        on_log: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> str:
        """
        Gera um preview MP3 aplicando `config` em uma cópia de `sample_path`.

        Returns
        -------
        str
            Caminho absoluto do arquivo de preview gerado (mesmo
            preview_output_path recebido).

        Raises
        ------
        FileNotFoundError
            Se sample_path não existir.
        OperacaoCancelada
            Se cancel_event for sinalizado durante a edição.
        Exception
            Erros do FfmpegAudioEditor são propagados sem alteração.
        """
        log      = on_log      if callable(on_log)      else _noop
        progress = on_progress if callable(on_progress) else _noop

        if not sample_path or not os.path.isfile(sample_path):
            raise FileNotFoundError(
                f"Arquivo de exemplo não encontrado: {sample_path}"
            )

        # Garante a pasta de destino
        out_dir = os.path.dirname(preview_output_path) or "."
        os.makedirs(out_dir, exist_ok=True)

        _log.info("preview iniciado — sample=%s", sample_path)
        t0 = time.monotonic()

        log("[Preview] Copiando arquivo de exemplo...")
        shutil.copy2(sample_path, preview_output_path)

        if not config.has_any_filter_enabled:
            log("[Preview] Nenhum filtro habilitado — preview = entrada.")
            progress(1.0)
            _log.info("preview concluido (no-op) em %.2fs", time.monotonic() - t0)
            return preview_output_path

        # Constrói AudioFile do preview. video_id "_test_" sinaliza que NÃO é
        # um áudio real — qualquer cleanup que veja esse prefixo pode descartar.
        audio = AudioFile(
            path=preview_output_path,
            title="_test_preview",
            video_id="_test_",
        )

        # FfmpegAudioEditor substitui o arquivo no caminho original (in-place).
        # Como o "original" aqui é o preview, a cópia do sample fica editada.
        self.editor.process(
            audio,
            config,
            cancel_event=cancel_event,
            on_log=on_log,
            on_progress=on_progress,
        )

        _log.info("preview concluido em %.2fs", time.monotonic() - t0)
        return preview_output_path
