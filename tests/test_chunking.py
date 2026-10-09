import numpy as np
import pytest

from livecaptions.chunking import PhraseChunker, prepare_audio, rms, to_16k_mono
from livecaptions.config import MAX_CHUNK_SEC

RATE = 16000


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def tone(seconds, amp=0.2, rate=RATE):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds, rate=RATE):
    return np.zeros(int(seconds * rate), dtype=np.float32)


def feed_in_blocks(chunker, audio, clock, block=1024):
    for i in range(0, len(audio), block):
        chunker.feed(audio[i:i + block])
        clock.t += block / chunker.rate


def test_rms_of_empty_is_zero():
    assert rms(np.zeros(0)) == 0.0


def test_resample_keeps_duration():
    audio = tone(1.0, rate=48000)
    out = to_16k_mono(audio, 48000)
    assert out.dtype == np.float32
    assert len(out) == 16000


def test_resample_passthrough_at_16k():
    audio = tone(0.5)
    assert np.array_equal(to_16k_mono(audio, RATE), audio)


def test_prepare_drops_silence():
    assert prepare_audio(silence(1.0), RATE, 0.004) is None


def test_prepare_boosts_quiet_audio_to_half_scale():
    out = prepare_audio(tone(1.0, amp=0.05), RATE, 0.004)
    assert out is not None
    assert np.max(np.abs(out)) == pytest.approx(0.5, rel=1e-3)


def test_prepare_leaves_loud_audio_alone():
    audio = tone(1.0, amp=0.8)
    out = prepare_audio(audio, RATE, 0.004)
    assert np.max(np.abs(out)) == pytest.approx(0.8, rel=1e-3)


def test_empty_buffer_never_ready():
    clock = FakeClock()
    c = PhraseChunker(RATE, clock=clock)
    clock.t += 10
    assert c.take_ready_chunk() is None


def test_short_continuous_speech_is_held():
    clock = FakeClock()
    c = PhraseChunker(RATE, clock=clock)
    feed_in_blocks(c, tone(1.0), clock)
    assert c.take_ready_chunk() is None


def test_pause_after_min_length_releases_phrase():
    clock = FakeClock()
    c = PhraseChunker(RATE, clock=clock)
    feed_in_blocks(c, np.concatenate([tone(2.0), silence(0.5)]), clock)
    chunk = c.take_ready_chunk()
    assert chunk is not None
    assert len(chunk) == pytest.approx(2.5 * RATE, abs=1024)
    assert c.buf_len == 0


def test_long_speech_forced_out_at_max_length():
    clock = FakeClock()
    c = PhraseChunker(RATE, clock=clock)
    feed_in_blocks(c, tone(MAX_CHUNK_SEC + 0.1), clock)
    assert c.take_ready_chunk() is not None


def test_callback_gap_counts_as_pause():
    clock = FakeClock()
    c = PhraseChunker(RATE, clock=clock)
    feed_in_blocks(c, tone(2.0), clock)
    assert c.take_ready_chunk() is None
    clock.t += 0.7   # no callbacks for longer than PAUSE_SEC
    assert c.take_ready_chunk() is not None


def test_idle_flush_releases_short_fragments():
    clock = FakeClock()
    c = PhraseChunker(RATE, clock=clock)
    feed_in_blocks(c, tone(0.5), clock)
    assert c.take_ready_chunk() is None
    clock.t += 2.0
    assert c.take_ready_chunk() is not None


def test_noise_floor_tracks_quiet_device():
    clock = FakeClock()
    c = PhraseChunker(RATE, clock=clock)
    feed_in_blocks(c, tone(1.0, amp=0.0003), clock)
    # Very quiet device -> threshold relative to its own floor, but never below the minimum.
    assert 0.0004 <= c.silence_threshold < 0.004
