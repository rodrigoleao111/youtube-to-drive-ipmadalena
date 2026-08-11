"""
Entidades do domínio — objetos imutáveis que representam conceitos de negócio.

Regras:
  - Sem importações de terceiros (apenas stdlib)
  - Imutáveis via frozen=True
  - Sem lógica de infraestrutura (rede, disco, UI)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


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

    subfolder: Optional[str] = None
    """
    Caminho absoluto da subpasta criada por segmento em downloads/.
    None quando o downloader não usa subpastas (retrocompatibilidade).
    Usado pelo presenter para montar a lista de upload com todos os
    artefatos (MP4, capa.jpg, descricao.txt) e pela GUI para localizar
    a capa na tela Início.
    """

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


# ===========================================================================
# Edição de áudio (vinhetas, fade, EQ, redução de ruído)
# ===========================================================================

@dataclass(frozen=True)
class EqBand:
    """
    Banda de equalização paramétrica.

    Uma frequência fixa (definida pelo preset) e um ganho ajustável em dB.
    A largura de banda Q é constante no pipeline ffmpeg (ver FfmpegAudioEditor).
    """

    freq_hz: int
    """Frequência central da banda em Hz (ex.: 80, 250, 1000, 4000, 10000)."""

    gain_db: float
    """Ganho/atenuação em dB (intervalo recomendado: -12.0 a +12.0)."""


def _default_eq_bands() -> Tuple[EqBand, ...]:
    """Constrói as bandas de EQ a partir do preset Voz Masculina."""
    from domain.audio_presets import EQ_PRESET_VOZ_MASCULINA
    return tuple(EqBand(freq_hz=f, gain_db=g) for f, g in EQ_PRESET_VOZ_MASCULINA)


@dataclass(frozen=True)
class AudioEditConfig:
    """
    Configuração do pipeline de edição de áudio.

    Aplicado entre o download do trecho e o upload para o Drive.
    Quando todas as etapas estão desligadas (`has_any_filter_enabled` é False),
    o editor é um no-op rápido — o arquivo passa direto.

    Persistido em `config.json` sob a chave `audio_edit` via `to_dict()` /
    reconstruído via `from_dict()` (campos ausentes recebem o default desta
    classe — backwards compatibility automática).
    """

    intro_path: Optional[str] = None
    """Caminho do arquivo de áudio da vinheta de entrada (None = sem vinheta)."""

    outro_path: Optional[str] = None
    """Caminho do arquivo de áudio da vinheta de saída (None = sem vinheta)."""

    intro_overlap_secs: float = 0.0
    """Segundos de sobreposição entre vinheta de entrada e início do áudio."""

    outro_overlap_secs: float = 0.0
    """Segundos de sobreposição entre fim do áudio e vinheta de saída."""

    fade_in_enabled: bool = False
    """Se True, aplica fade in no início do áudio."""

    fade_in_secs: float = 2.0
    """Duração do fade in em segundos (ignorado se fade_in_enabled=False)."""

    fade_out_enabled: bool = False
    """Se True, aplica fade out no fim do áudio."""

    fade_out_secs: float = 3.0
    """Duração do fade out em segundos (ignorado se fade_out_enabled=False)."""

    eq_enabled: bool = False
    """Se True, aplica equalização paramétrica de 5 bandas."""

    eq_bands: Tuple[EqBand, ...] = field(default_factory=_default_eq_bands)
    """5 bandas de EQ. Default = preset 'Voz Masculina' (clareza em pregação)."""

    noise_reduction_enabled: bool = False
    """Se True, aplica redução de ruído (filtro afftdn)."""

    noise_reduction_intensity: str = "media"
    """Intensidade da redução: 'baixa' | 'media' | 'alta'."""

    volume_norm_enabled: bool = False
    """Se True, normaliza o volume de cada peça (áudio principal + vinhetas) via loudnorm."""

    volume_norm_lufs: float = -16.0
    """Alvo de loudness integrado em LUFS (EBU R128). Intervalo típico: -30 a -6."""

    # ------------------------------------------------------------------
    # Música de fundo
    # ------------------------------------------------------------------

    bg_music_path: Optional[str] = None
    """Caminho do arquivo de música de fundo (None = sem música)."""

    bg_music_enabled: bool = False
    """Se True, mistura a música de fundo no áudio final."""

    bg_music_volume: float = 0.12
    """Volume da música em relação ao áudio principal (0.0–1.0). Default 12%."""

    bg_music_delay: float = 0.0
    """
    Intro musical: segundos em que a música toca SOZINHA antes da voz começar.

    A música arranca no segundo 0 e é o episódio que é empurrado para frente
    (`adelay`), então a saída fica `duração do episódio + este valor`.
    0 = música e voz começam juntas.
    """

    bg_music_fade_in: float = 3.0
    """Duração (s) do fade in da música de fundo."""

    bg_music_fade_out: float = 6.0
    """Duração (s) do fade out da música de fundo."""

    bg_music_loop: bool = True
    """Se True, a música é repetida em loop até o fim do episódio."""

    @property
    def has_any_filter_enabled(self) -> bool:
        """True se qualquer etapa do pipeline estiver ativa (caso contrário, no-op)."""
        return (
            self.fade_in_enabled
            or self.fade_out_enabled
            or self.eq_enabled
            or self.noise_reduction_enabled
            or self.volume_norm_enabled
            or self.intro_path is not None
            or self.outro_path is not None
            or (self.bg_music_enabled and self.bg_music_path is not None)
        )

    def to_dict(self) -> dict:
        """Serializa para dict JSON-friendly (eq_bands vira lista de objetos)."""
        return {
            "intro_path":                self.intro_path,
            "outro_path":                self.outro_path,
            "intro_overlap_secs":        self.intro_overlap_secs,
            "outro_overlap_secs":        self.outro_overlap_secs,
            "fade_in_enabled":           self.fade_in_enabled,
            "fade_in_secs":              self.fade_in_secs,
            "fade_out_enabled":          self.fade_out_enabled,
            "fade_out_secs":             self.fade_out_secs,
            "eq_enabled":                self.eq_enabled,
            "eq_bands":                  [{"freq_hz": b.freq_hz, "gain_db": b.gain_db}
                                          for b in self.eq_bands],
            "noise_reduction_enabled":   self.noise_reduction_enabled,
            "noise_reduction_intensity": self.noise_reduction_intensity,
            "volume_norm_enabled":       self.volume_norm_enabled,
            "volume_norm_lufs":          self.volume_norm_lufs,
            "bg_music_path":             self.bg_music_path,
            "bg_music_enabled":          self.bg_music_enabled,
            "bg_music_volume":           self.bg_music_volume,
            "bg_music_delay":            self.bg_music_delay,
            "bg_music_fade_in":          self.bg_music_fade_in,
            "bg_music_fade_out":         self.bg_music_fade_out,
            "bg_music_loop":             self.bg_music_loop,
        }

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "AudioEditConfig":
        """
        Constrói a partir de dict JSON.

        Campos ausentes recebem o default da classe (backwards compatibility
        ao adicionar novos campos em versões futuras). Aceita None ou {} —
        ambos retornam a configuração padrão.
        """
        if not d:
            return cls()
        bands_raw = d.get("eq_bands")
        if bands_raw:
            bands = tuple(
                EqBand(freq_hz=int(b["freq_hz"]), gain_db=float(b["gain_db"]))
                for b in bands_raw
            )
        else:
            bands = _default_eq_bands()
        return cls(
            intro_path                = d.get("intro_path"),
            outro_path                = d.get("outro_path"),
            intro_overlap_secs        = float(d.get("intro_overlap_secs", 0.0)),
            outro_overlap_secs        = float(d.get("outro_overlap_secs", 0.0)),
            fade_in_enabled           = bool(d.get("fade_in_enabled", False)),
            fade_in_secs              = float(d.get("fade_in_secs", 2.0)),
            fade_out_enabled          = bool(d.get("fade_out_enabled", False)),
            fade_out_secs             = float(d.get("fade_out_secs", 3.0)),
            eq_enabled                = bool(d.get("eq_enabled", False)),
            eq_bands                  = bands,
            noise_reduction_enabled   = bool(d.get("noise_reduction_enabled", False)),
            noise_reduction_intensity = d.get("noise_reduction_intensity", "media"),
            volume_norm_enabled       = bool(d.get("volume_norm_enabled", False)),
            volume_norm_lufs          = float(d.get("volume_norm_lufs", -16.0)),
            bg_music_path             = d.get("bg_music_path"),
            bg_music_enabled          = bool(d.get("bg_music_enabled", False)),
            bg_music_volume           = float(d.get("bg_music_volume", 0.12)),
            bg_music_delay            = float(d.get("bg_music_delay", 0.0)),
            bg_music_fade_in          = float(d.get("bg_music_fade_in", 3.0)),
            bg_music_fade_out         = float(d.get("bg_music_fade_out", 6.0)),
            bg_music_loop             = bool(d.get("bg_music_loop", True)),
        )


# ===========================================================================
# Publicação de podcast (Spotify for Podcasters)
# ===========================================================================

@dataclass(frozen=True)
class PodcastEpisode:
    """
    Metadados de um episódio a ser publicado no Spotify for Podcasters.

    Construído em ``_worker_phase2`` após o processamento bem-sucedido de um
    segmento. A publicação em si é feita pelo usuário no WebView — o app apenas
    pré-preenche o formulário.
    """

    video_id: str
    """ID do vídeo YouTube de origem (ex.: 'dQw4w9WgXcQ')."""

    title: str
    """Título do episódio (pode ser prefixado pela config Spotify)."""

    description: str
    """Descrição do episódio — inicialmente vazia; preenchida de forma assíncrona."""

    audio_path: str
    """Caminho absoluto do arquivo MP3 (vazio se keep_files=False e já apagado)."""

    tags: Tuple[str, ...] = field(default_factory=tuple)
    """Tags / labels a aplicar no episódio (vindas da config Spotify)."""

    date_str: str = ""
    """Data de referência do culto no formato DD/MM/AAAA."""
