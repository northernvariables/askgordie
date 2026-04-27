"""Audio feedback tones for the Gordie Voice appliance.

- Wake chime: O Canada first 4 notes on synth bass (5x speed)
- Thinking music: Jeopardy Think! on marimba with swing brushes
"""

from __future__ import annotations

import numpy as np

# All tones generated at 44.1kHz for quality, converted to bytes for playback
TONE_SAMPLE_RATE = 44100


def _synth_bass(freq: float, duration_s: float, volume: float = 0.04) -> np.ndarray:
    """Pure sine sub bass with soft attack and smooth taper."""
    n = int(TONE_SAMPLE_RATE * duration_s)
    t = np.arange(n) / TONE_SAMPLE_RATE
    attack_len = min(int(TONE_SAMPLE_RATE * 0.05), n)
    env = np.ones(n)
    env[:attack_len] = np.linspace(0, 1, attack_len)
    release_start = int(n * 0.4)
    env[release_start:] = np.exp(-(t[release_start:] - t[release_start]) * 5)
    fade_out = min(int(TONE_SAMPLE_RATE * 0.03), n)
    env[-fade_out:] *= np.linspace(1, 0, fade_out) ** 2
    signal = np.sin(2 * np.pi * freq * t) * env * volume
    signal = signal / (np.max(np.abs(signal)) + 1e-10) * volume
    return (signal * 32767).astype(np.int16)


def _marimba_bar(freq: float, duration_s: float, volume: float = 0.068) -> np.ndarray:
    """Physical model marimba with long sustain."""
    n = int(TONE_SAMPLE_RATE * duration_s)
    t = np.arange(n) / TONE_SAMPLE_RATE
    f1 = freq
    f2 = freq * 4.0
    f3 = freq * 9.2
    d1 = np.exp(-t * 0.2)
    d2 = np.exp(-t * 0.9)
    d3 = np.exp(-t * 2.0)
    nl = int(TONE_SAMPLE_RATE * 0.003)
    noise = np.zeros(n)
    noise[:nl] = np.random.randn(nl) * 0.08
    ne = np.zeros(n)
    ne[:nl] = np.exp(-np.arange(nl) / (TONE_SAMPLE_RATE * 0.001))
    signal = (
        np.sin(2 * np.pi * f1 * t) * d1 * 1.3
        + np.sin(2 * np.pi * f2 * t) * d2 * 0.06
        + np.sin(2 * np.pi * f3 * t) * d3 * 0.015
        + noise * ne
    )
    a = min(int(TONE_SAMPLE_RATE * 0.002), n)
    signal[:a] *= np.linspace(0, 1, a)
    signal = signal / (np.max(np.abs(signal)) + 1e-10) * volume
    return (signal * 32767).astype(np.int16)


def _brush_hit(volume: float = 0.025) -> np.ndarray:
    """Brush hit on snare."""
    n = int(TONE_SAMPLE_RATE * 0.08)
    t = np.arange(n) / TONE_SAMPLE_RATE
    noise = np.random.randn(n)
    from numpy.fft import rfft, irfft, rfftfreq
    freqs = rfftfreq(n, 1.0 / TONE_SAMPLE_RATE)
    spectrum = rfft(noise)
    bp = np.exp(-((freqs - 3500) ** 2) / (2 * 2000 ** 2))
    spectrum *= bp
    noise = irfft(spectrum, n)
    env = np.exp(-t * 50)
    return noise * env * volume


def _brush_swish(duration_s: float = 0.25, volume: float = 0.025) -> np.ndarray:
    """Brush swish on snare."""
    n = int(TONE_SAMPLE_RATE * duration_s)
    t = np.arange(n) / TONE_SAMPLE_RATE
    noise = np.random.randn(n)
    from numpy.fft import rfft, irfft, rfftfreq
    freqs = rfftfreq(n, 1.0 / TONE_SAMPLE_RATE)
    spectrum = rfft(noise)
    bp = np.exp(-((freqs - 4000) ** 2) / (2 * 2000 ** 2))
    spectrum *= bp
    noise = irfft(spectrum, n)
    attack = int(n * 0.3)
    env = np.ones(n)
    env[:attack] = np.linspace(0, 1, attack)
    env[attack:] = np.exp(-(t[attack:] - t[attack]) * 12)
    return noise * env * volume


def _brush_circle(duration_s: float, bpm: int = 120, volume: float = 0.01) -> np.ndarray:
    """Continuous brush circle."""
    n = int(TONE_SAMPLE_RATE * duration_s)
    t = np.arange(n) / TONE_SAMPLE_RATE
    noise = np.random.randn(n)
    from numpy.fft import rfft, irfft, rfftfreq
    freqs = rfftfreq(n, 1.0 / TONE_SAMPLE_RATE)
    spectrum = rfft(noise)
    bp = np.exp(-((freqs - 5000) ** 2) / (2 * 2500 ** 2))
    spectrum *= bp
    noise = irfft(spectrum, n)
    beat_freq = bpm / 60.0 / 2
    pulse = 0.5 + 0.5 * np.sin(2 * np.pi * beat_freq * t + np.pi * 0.5)
    return noise * pulse * volume


def _ghost_tap(volume: float = 0.01) -> np.ndarray:
    """Very quiet ghost note."""
    n = int(TONE_SAMPLE_RATE * 0.03)
    t = np.arange(n) / TONE_SAMPLE_RATE
    noise = np.random.randn(n)
    env = np.exp(-t * 100)
    return noise * env * volume


def listening_chime(sample_rate: int = 16000) -> bytes:
    """O Canada first 4 notes on synth bass — played when wake word is detected.

    A4 (half), C5 (dotted quarter), C5 (eighth), F4 (dotted half) at 5x speed.
    Returns PCM int16 bytes at TONE_SAMPLE_RATE (44.1kHz).
    """
    A3 = 220.0
    C4 = 261.6
    F3 = 174.6
    Q = 100  # 5x speed quarter note in ms

    audio = np.concatenate([
        _synth_bass(A3, Q * 2 / 1000, 0.16),
        _synth_bass(C4, int(Q * 1.5) / 1000, 0.16),
        _synth_bass(C4, (Q // 2) / 1000, 0.16),
        _synth_bass(F3, Q * 3 / 1000, 0.168),
    ])
    return audio.tobytes()


def thinking_tone(sample_rate: int = 16000) -> bytes:
    """Jeopardy Think! on marimba with swing brushes.

    Key of D major, 120 BPM. Returns PCM int16 bytes at TONE_SAMPLE_RATE (44.1kHz).
    """
    BPM = 120
    quarter_s = 60.0 / BPM
    quarter = int(TONE_SAMPLE_RATE * quarter_s)
    eighth = quarter // 2

    # Notes in D major
    D4 = 293.7; E4 = 329.6; Fs4 = 370.0; G4 = 392.0
    A4 = 440.0; Bb4 = 466.2; B4 = 493.9
    Cs5 = 554.4; D5 = 587.3; E5 = 659.3; Fs5 = 740.0

    def n(freq, dur):
        seconds = quarter_s * (4 / dur)
        return _marimba_bar(freq, seconds)

    def rest(dur_value):
        seconds = quarter_s * (4 / dur_value)
        return np.zeros(int(TONE_SAMPLE_RATE * seconds))

    melody_parts = [
        # Line 1
        n(A4, 4), n(D5, 4), n(A4, 4), n(D4, 4),
        n(A4, 4), n(D5, 4), n(A4, 2),
        # Line 2
        n(A4, 4), n(D5, 4), n(A4, 4), n(D5, 4),
        n(Fs5, 4), rest(8), n(E5, 8), n(D5, 8), n(Cs5, 8), n(B4, 8), n(Bb4, 8),
        # Line 3
        n(A4, 4), n(D5, 4), n(A4, 4),
        n(Fs4, 8), n(G4, 8), n(A4, 4), n(D5, 4), n(A4, 2),
        # Line 4
        n(D5, 4), rest(8), n(B4, 8),
        n(A4, 4), n(G4, 4), n(Fs4, 4), n(E4, 4), n(D4, 4), rest(4),
    ]

    melody = np.concatenate(melody_parts)
    total_duration = len(melody) / TONE_SAMPLE_RATE

    # Generate swing brush pattern
    total_samples = len(melody)
    drums = np.zeros(total_samples)
    swing_eighth = int(quarter * 2 / 3)
    cycle_len = 4 * quarter

    pos = 0
    while pos < total_samples:
        # Hit 1: beat 1
        hit = _brush_hit()
        end = min(pos + len(hit), total_samples)
        drums[pos:end] += hit[:end - pos]

        # Hit 2: swung eighth after beat 1
        pos2 = pos + quarter + swing_eighth
        if pos2 < total_samples:
            hit = _brush_hit(0.018)
            end = min(pos2 + len(hit), total_samples)
            drums[pos2:end] += hit[:end - pos2]

        # Hit 3: beat 3
        pos3 = pos + 2 * quarter
        if pos3 < total_samples:
            hit = _brush_hit()
            end = min(pos3 + len(hit), total_samples)
            drums[pos3:end] += hit[:end - pos3]

        # Swishes on beats 2 and 4
        for beat in [1, 3]:
            swish_pos = pos + beat * quarter
            if swish_pos < total_samples:
                swish = _brush_swish()
                end = min(swish_pos + len(swish), total_samples)
                drums[swish_pos:end] += swish[:end - swish_pos]

        # Ghost notes on swung eighths
        for beat in range(4):
            ghost_pos = pos + beat * quarter + int(quarter * 2 / 3)
            if ghost_pos < total_samples:
                g = _ghost_tap(np.random.uniform(0.006, 0.012))
                end = min(ghost_pos + len(g), total_samples)
                drums[ghost_pos:end] += g[:end - ghost_pos]

        pos += cycle_len

    # Brush circle
    circle = _brush_circle(total_duration, BPM)
    drums[:len(circle)] += circle[:len(drums)]

    # Mix
    drums_scaled = drums * 32767
    mixed = melody + drums_scaled
    mixed = np.clip(mixed, -32767, 32767)

    return mixed.astype(np.int16).tobytes()


def get_tone_sample_rate() -> int:
    """Return the sample rate used by the tone generators."""
    return TONE_SAMPLE_RATE
