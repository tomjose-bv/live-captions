"""Record a screen area to an MP4 file, optionally with the sound playing on the PC.

Video is H.264 at a constant frame rate. Frames are grabbed against the wall clock, so
if a grab is slow the previous picture is repeated and the video keeps real time.
Speaker sound (WASAPI loopback) is encoded as AAC; Windows sends no loopback data while
nothing is playing, so silence is filled in to keep the sound in step with the picture.
Encoding uses PyAV, which faster-whisper already installs.
"""

import datetime
import queue
import threading
import time
from pathlib import Path

import numpy as np

from . import ocr

FPS = 15
MAX_SECONDS = 4 * 60 * 60   # safety stop if the user forgets
AUDIO_LAG = 0.25            # pad silence once the sound falls this far behind the clock


class RecorderError(Exception):
    pass


def even_box(bbox):
    """H.264 (yuv420p) needs an even width and height: trim a pixel where needed."""
    left, top, right, bottom = bbox
    width, height = right - left, bottom - top
    if width < 2 or height < 2:
        raise RecorderError("The selected area is too small to record.")
    return left, top, left + width - width % 2, top + height - height % 2


def default_folder():
    return Path.home() / "Videos" / "Live Captions"


def new_recording_path(folder=None, now=None):
    now = now or datetime.datetime.now()
    return Path(folder or default_folder()) / f"recording-{now:%Y%m%d-%H%M%S}.mp4"


class SpeakerAudio:
    """What the PC is playing, from the default speakers' loopback device."""

    def __init__(self):
        from . import audio

        pyaudio = audio._pyaudio()
        self.pa, wasapi = audio.open_pyaudio()
        try:
            dev = audio.speaker_loopback_device(self.pa, wasapi)
        except Exception:
            self.pa.terminate()
            raise
        self.rate = int(dev["defaultSampleRate"])
        self.device_channels = dev["maxInputChannels"]
        self.channels = min(self.device_channels, 2)
        self.q = queue.Queue()

        def callback(in_data, frame_count, time_info, status):
            self.q.put(in_data)
            return (None, pyaudio.paContinue)

        self.stream = self.pa.open(format=pyaudio.paInt16, channels=self.device_channels,
                                   rate=self.rate, input=True,
                                   input_device_index=dev["index"],
                                   frames_per_buffer=1024, stream_callback=callback)

    def read(self):
        """All sound captured since the last call, as int16 (samples, channels)."""
        chunks = []
        while True:
            try:
                chunks.append(self.q.get_nowait())
            except queue.Empty:
                break
        if not chunks:
            return np.zeros((0, self.channels), dtype=np.int16)
        data = np.frombuffer(b"".join(chunks), dtype=np.int16)
        return data.reshape(-1, self.device_channels)[:, :self.channels]

    def close(self):
        try:
            self.stream.stop_stream()
            self.stream.close()
        finally:
            self.pa.terminate()


class ScreenRecorder:
    """Records ``bbox`` to ``path`` on a background thread until ``stop()``.

    ``grab`` (bbox -> PIL image) and ``audio`` (an object like SpeakerAudio) can be
    replaced in tests.
    """

    def __init__(self, bbox, path, fps=FPS, audio=None, grab=ocr.capture,
                 clock=time.monotonic, max_seconds=MAX_SECONDS):
        self.bbox = even_box(bbox)
        self.path = Path(path)
        self.fps = fps
        self.audio = audio
        self.grab = grab
        self.clock = clock
        self.max_seconds = max_seconds
        self.frames = 0
        self.seconds = 0.0
        self.error = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def size(self):
        left, top, right, bottom = self.bbox
        return right - left, bottom - top

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        import av

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.container = av.open(str(self.path), "w")
        try:
            width, height = self.size
            self.video = self.container.add_stream(
                "libx264", rate=self.fps, options={"preset": "veryfast", "crf": "23"})
            self.video.width, self.video.height = width, height
            self.video.pix_fmt = "yuv420p"
            self.sound = None
            if self.audio is not None:
                self.sound = self.container.add_stream("aac", rate=self.audio.rate)
                self.sound.layout = "stereo" if self.audio.channels == 2 else "mono"
                self.audio_samples = 0
        except Exception:
            self.container.close()
            raise
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        """Finish the file. Returns the path; ``self.error`` says if recording failed."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        return self.path

    # ---------- background thread ----------

    def _run(self):
        started = self.clock()
        image = None
        try:
            while not self._stop.is_set():
                elapsed = self.clock() - started
                if elapsed > self.max_seconds:
                    break
                due = int(elapsed * self.fps) + 1      # frames that should exist by now
                if self.frames < due:
                    image = self.grab(self.bbox)
                    while self.frames < due:           # repeat it if we fell behind
                        self._write_frame(image)
                if self.sound is not None:
                    self._write_audio(elapsed)
                self.seconds = elapsed
                wait = (self.frames / self.fps) - (self.clock() - started)
                self._stop.wait(max(wait, 0.001))
        except Exception as e:   # reported by the UI once stop() returns
            self.error = f"Recording stopped: {e}"
            self._stop.set()
        finally:
            self._close()

    def _write_frame(self, image):
        import av

        if image.size != self.size:
            image = image.resize(self.size)
        frame = av.VideoFrame.from_image(image.convert("RGB"))
        frame.pts = self.frames
        for packet in self.video.encode(frame):
            self.container.mux(packet)
        self.frames += 1

    def _write_audio(self, elapsed):
        samples = self.audio.read()
        behind = elapsed - (self.audio_samples + len(samples)) / self.audio.rate
        if behind > AUDIO_LAG:
            gap = int((behind - AUDIO_LAG / 2) * self.audio.rate)
            samples = np.concatenate(
                [samples, np.zeros((gap, self.audio.channels), dtype=np.int16)])
        if len(samples):
            self._encode_audio(samples)

    def _encode_audio(self, samples):
        import av

        frame = av.AudioFrame.from_ndarray(
            np.ascontiguousarray(samples).reshape(1, -1), format="s16",
            layout=self.sound.layout.name)
        frame.sample_rate = self.audio.rate
        frame.pts = self.audio_samples
        self.audio_samples += len(samples)
        for packet in self.sound.encode(frame):
            self.container.mux(packet)

    def _close(self):
        try:
            if self.sound is not None:   # end the sound with the picture
                gap = int(self.frames / self.fps * self.audio.rate) - self.audio_samples
                if gap > 0:
                    self._encode_audio(np.zeros((gap, self.audio.channels), dtype=np.int16))
            for stream in (self.video, self.sound):
                if stream is not None:
                    for packet in stream.encode(None):
                        self.container.mux(packet)
        except Exception as e:
            self.error = self.error or f"Couldn't finish the video: {e}"
        finally:
            self.container.close()
            if self.audio is not None:
                try:
                    self.audio.close()
                except Exception:
                    pass
