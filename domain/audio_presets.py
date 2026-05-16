"""
Constantes e presets do pipeline de edição de áudio.

Sem importações de terceiros (apenas stdlib). Constantes — não devem ser
mutadas em runtime.
"""

from __future__ import annotations

from typing import Tuple


# Frequências fixas dos 5 sliders de equalização (em Hz).
# Estilo equalizador Hi-Fi: graves, médios-graves, médios, médios-agudos, agudos.
EQ_FREQS: Tuple[int, ...] = (80, 250, 1000, 4000, 10000)


# Faixa permitida do ganho de cada banda (em dB).
EQ_GAIN_MIN_DB: float = -12.0
EQ_GAIN_MAX_DB: float = +12.0


# Preset padrão "Voz Masculina" — otimizado para clareza em pregação:
#   80 Hz: -3 dB  (corta rumble e boom)
#  250 Hz: -2 dB  (reduz a "lama" típica do registro masculino)
#    1 kHz: 0 dB  (referência neutra)
#    4 kHz: +3 dB (presença/inteligibilidade dos consoantes)
#   10 kHz: +1 dB (leve "ar")
EQ_PRESET_VOZ_MASCULINA: Tuple[Tuple[int, float], ...] = (
    (80,    -3.0),
    (250,   -2.0),
    (1000,   0.0),
    (4000,  +3.0),
    (10000, +1.0),
)


# Intensidades válidas de redução de ruído (mapeadas no FfmpegAudioEditor para
# valores de `nr` do filtro afftdn).
NOISE_INTENSITIES: Tuple[str, ...] = ("baixa", "media", "alta")
