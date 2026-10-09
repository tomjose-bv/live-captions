"""WASAPI capture (speaker loopback and microphone) via PyAudioWPatch. Windows only."""

import queue

import numpy as np

from .chunking import PhraseChunker


def _pyaudio():
    import pyaudiowpatch as pyaudio
    return pyaudio


class AudioSource:
    """One capture device (speaker loopback or microphone) with its own phrase buffer."""

    def __init__(self, label, pa, dev):
        pyaudio = _pyaudio()
        self.label = label
        self.name = dev["name"]
        self.rate = int(dev["defaultSampleRate"])
        self.q = queue.Queue()
        self.chunker = PhraseChunker(self.rate)
        channels = dev["maxInputChannels"]

        def callback(in_data, frame_count, time_info, status):
            samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
            self.q.put(samples.reshape(-1, channels).mean(axis=1))
            return (None, pyaudio.paContinue)

        self.stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=self.rate,
                              input=True, input_device_index=dev["index"],
                              frames_per_buffer=1024, stream_callback=callback)

    def drain(self):
        while True:
            try:
                chunk = self.q.get_nowait()
            except queue.Empty:
                return
            self.chunker.feed(chunk)

    @property
    def silence_threshold(self):
        return self.chunker.silence_threshold

    def take_ready_chunk(self):
        return self.chunker.take_ready_chunk()

    def close(self):
        self.stream.stop_stream()
        self.stream.close()


def open_pyaudio():
    pyaudio = _pyaudio()
    pa = pyaudio.PyAudio()
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    return pa, wasapi


def speaker_loopback_device(pa, wasapi):
    dev = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if dev.get("isLoopbackDevice"):
        return dev
    for lb in pa.get_loopback_device_info_generator():
        if dev["name"] in lb["name"]:
            return lb
    raise RuntimeError("No loopback device found for the default speakers.")


def microphone_device(pa, wasapi):
    return pa.get_device_info_by_index(wasapi["defaultInputDevice"])
