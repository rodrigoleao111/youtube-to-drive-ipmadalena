"""
Entidades do domínio — objetos imutáveis que representam conceitos de negócio.

Regras:
  - Sem importações de terceiros (apenas stdlib)
  - Imutáveis via frozen=True
  - Sem lógica de infraestrutura (rede, disco, UI)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Video:
    """Representa um vídeo listado no YouTube, antes do download."""

    id: str
    """ID do vídeo no YouTube (ex.: 'dQw4w9WgXcQ')."""

    title: str
    """Título do vídeo conforme retornado pelo yt-dlp."""

    upload_date: str
    """Data de publicação no formato YYYYMMDD."""

    def youtube_url(self) -> str:
        """URL canônica do vídeo."""
        return f"https://www.youtube.com/watch?v={self.id}"

    def __str__(self) -> str:
        return f"{self.title} ({self.upload_date})"


@dataclass(frozen=True)
class Segment:
    """
    Define qual trecho de um vídeo deve ser processado.

    Quando start e end são None, indica que o vídeo inteiro deve ser usado.
    """

    video_id: str
    """ID do vídeo ao qual este segmento pertence."""

    title: str
    """Título usado para nomear o arquivo de saída."""

    start: Optional[str] = None
    """Início do trecho no formato HH:MM:SS (None = início do vídeo)."""

    end: Optional[str] = None
    """Fim do trecho no formato HH:MM:SS (None = fim do vídeo)."""

    @property
    def is_full_video(self) -> bool:
        """True quando nenhum trecho foi selecionado (usa vídeo inteiro)."""
        return self.start is None and self.end is None

    def __str__(self) -> str:
        if self.is_full_video:
            return f"{self.title} [completo]"
        return f"{self.title} [{self.start}–{self.end}]"


@dataclass(frozen=True)
class AudioFile:
    """Representa um arquivo de áudio gerado pelo processo de download."""

    path: str
    """Caminho absoluto do arquivo MP3 no sistema de arquivos local."""

    title: str
    """Nome amigável para exibição e upload."""

    video_id: str
    """ID do vídeo de origem."""

    def filename(self) -> str:
        """Nome do arquivo sem o diretório."""
        import os
        return os.path.basename(self.path)


@dataclass(frozen=True)
class ProcessingResult:
    """Resultado do processamento completo de uma data."""

    date_str: str
    """Data processada no formato DD/MM/AAAA."""

    uploaded_files: tuple[str, ...] = field(default_factory=tuple)
    """Nomes dos arquivos enviados com sucesso para o Drive."""

    skipped_files: tuple[str, ...] = field(default_factory=tuple)
    """Nomes dos arquivos ignorados (já existiam no Drive)."""

    @property
    def total(self) -> int:
        return len(self.uploaded_files) + len(self.skipped_files)

    @property
    def success(self) -> bool:
        return self.total > 0

    def summary(self) -> str:
        parts = []
        if self.uploaded_files:
            parts.append(f"{len(self.uploaded_files)} enviado(s)")
        if self.skipped_files:
            parts.append(f"{len(self.skipped_files)} já existia(m)")
        return ", ".join(parts) if parts else "nenhum arquivo processado"
