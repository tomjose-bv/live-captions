"""Hardware-free audio buffering, pause detection and pre-processing.

Everything here operates on numpy arrays and an injectable clock so it can be
unit-tested without a sound card.
"""

import time

import numpy as np

from .config import (IDLE_FLUSH_SEC, MAX_CHUNK_SEC, MIN_CHUNK_SEC, PAUSE_SEC, SILENCE_RMS,
                     TARGET_RATE)


def rms(audio):
    return float(np.sqrt(np.mean(np.square(audio)))) if len(audio) else 0.0


def to_16k_mono(audio, rate):
    """Linear-interpolation resample of a mono float signal to 16 kHz."""
    if rate == TARGET_RATE:
        return audio.astype(np.float32)
    n_out = int(len(audio) * TARGET_RATE / rate)
    return np.interp(np.linspace(0, len(audio) - 1, n_out),
                     np.arange(len(audio)), audio).astype(np.float32)


def prepare_audio(audio, rate, silence_threshold):
    """Resample a chunk and normalise its level; return None if it is effectively silent."""
    audio = to_16k_mono(audio, rate)
    if rms(audio) < silence_threshold / 2:
        return None
    peak = float(np.max(np.abs(audio)))
    if 0 < peak < 0.5:
        audio = audio * (0.5 / peak)   # boost quiet input before recognition
    return audio


class PhraseChunker:
    """Buffers audio from one device and decides when a phrase is ready to transcribe.

    A chunk is released when speech pauses (tail goes quiet or callbacks stop),
    when it reaches MAX_CHUNK_SEC, or when the device has been idle for a while.
    """

    def __init__(self, rate, clock=time.time):
        self.rate = rate
        self.clock = clock
        self.buf, self.buf_len = [], 0
        self.last_audio = clock()
        self.noise = None   # running estimate of the background level of this device

    def feed(self, chunk):
        self.buf.append(chunk)
        self.buf_len += len(chunk)
        self.last_audio = self.clock()
        # Track the noise floor: drop quickly to quieter levels, rise slowly.
        level = rms(chunk)
        if self.noise is None or level < self.noise:
            self.noise = level
        else:
            self.noise += (level - self.noise) * 0.002

    @property
    def seconds(self):
        return self.buf_len / self.rate

    @property
    def silence_threshold(self):
        # Quiet devices (e.g. laptop mic arrays) get a threshold relative to their own noise floor.
        return min(SILENCE_RMS, max(3 * (self.noise or 0.0), 0.0004))

    def take_ready_chunk(self):
        """Return buffered audio if a phrase looks complete, else None."""
        if not self.buf_len:
            return None
        secs = self.seconds
        idle = self.clock() - self.last_audio
        tail = np.concatenate(self.buf[-20:])[-int(0.4 * self.rate):]
        paused = idle > PAUSE_SEC or rms(tail) < self.silence_threshold
        if secs >= MAX_CHUNK_SEC or (secs >= MIN_CHUNK_SEC and paused) or idle > IDLE_FLUSH_SEC:
            return self.flush()
        return None

    def flush(self):
        audio = np.concatenate(self.buf) if self.buf else np.zeros(0, dtype=np.float32)
        self.buf, self.buf_len = [], 0
        return audio
