"""Screen recording: real H.264/AAC encoding with fake screen grabs and fake sound."""

import datetime
import time

import numpy as np
import pytest

av = pytest.importorskip("av")
Image = pytest.importorskip("PIL.Image")

from livecaptions import recorder  # noqa: E402


def colour_grab(bbox):
    left, top, right, bottom = bbox
    shade = int(time.monotonic() * 100) % 255
    return Image.new("RGB", (right - left, bottom - top), (shade, 80, 160))


class FakeSound:
    """Plays a tone for the first few reads, then goes quiet like an idle loopback."""

    rate, channels = 48000, 2

    def __init__(self):
        self.reads = 0
        self.closed = False

    def read(self):
        self.reads += 1
        if self.reads > 3:
            return np.zeros((0, 2), dtype=np.int16)
        tone = (np.sin(np.arange(2400) / 10) * 8000).astype(np.int16)
        return np.stack([tone, tone], axis=1)

    def close(self):
        self.closed = True


def streams(path):
    with av.open(str(path)) as c:
        return {s.type: (s.codec_context.name, float(s.duration * s.time_base),
                         getattr(s, "width", None), getattr(s, "height", None))
                for s in c.streams}


def record(tmp_path, seconds=0.6, **kw):
    rec = recorder.ScreenRecorder((10, 20, 211, 121), tmp_path / "clip.mp4",
                                  grab=colour_grab, **kw)
    rec.start()
    time.sleep(seconds)
    return rec, rec.stop()


def test_even_box_trims_odd_sizes():
    assert recorder.even_box((0, 0, 201, 101)) == (0, 0, 200, 100)
    assert recorder.even_box((5, 5, 15, 15)) == (5, 5, 15, 15)
    with pytest.raises(recorder.RecorderError):
        recorder.even_box((0, 0, 1, 50))


def test_new_recording_path_is_timestamped(tmp_path):
    path = recorder.new_recording_path(tmp_path, datetime.datetime(2026, 10, 18, 9, 5, 7))
    assert path == tmp_path / "recording-20261018-090507.mp4"


def test_records_video_in_real_time(tmp_path):
    rec, path = record(tmp_path, fps=10)
    assert rec.error is None and not rec.running
    info = streams(path)
    assert set(info) == {"video"}
    codec, duration, width, height = info["video"]
    assert (codec, width, height) == ("h264", 200, 100)
    assert 0.4 <= duration <= 1.0
    assert rec.frames == round(duration * 10)


def test_sound_is_padded_to_match_the_picture(tmp_path):
    sound = FakeSound()
    rec, path = record(tmp_path, seconds=1.0, audio=sound)
    assert rec.error is None and sound.closed
    info = streams(path)
    assert info["audio"][0] == "aac"
    assert abs(info["audio"][1] - info["video"][1]) < 0.15


def test_grab_failure_stops_recording(tmp_path):
    def broken(bbox):
        raise OSError("screen locked")

    rec2 = recorder.ScreenRecorder((0, 0, 100, 100), tmp_path / "bad.mp4", grab=broken)
    rec2.start()
    for _ in range(100):
        if not rec2.running:
            break
        time.sleep(0.01)
    assert not rec2.running
    rec2.stop()
    assert "screen locked" in rec2.error and rec2.frames == 0


def test_time_limit_stops_recording(tmp_path):
    rec = recorder.ScreenRecorder((0, 0, 100, 100), tmp_path / "short.mp4",
                                  grab=colour_grab, max_seconds=0.3)
    rec.start()
    for _ in range(200):
        if not rec.running:
            break
        time.sleep(0.01)
    assert not rec.running and rec.error is None
