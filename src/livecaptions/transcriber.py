"""Background loop: pull audio from sources, chunk it, transcribe, report text."""

import threading
import time

from .chunking import prepare_audio
from .config import MODELS
from .engines import create_engine


class Transcriber:
    def __init__(self, on_text, on_status, engine_factory=create_engine):
        self.on_text = on_text          # called with (label, text)
        self.on_status = on_status
        self.engine_factory = engine_factory
        self.model = None
        self.model_name = None
        self.running = False

    def start(self, model_key, use_speakers, use_mic):
        self.running = True
        threading.Thread(target=self._run, args=(model_key, use_speakers, use_mic),
                         daemon=True).start()

    def stop(self):
        self.running = False

    def load_model(self, model_key):
        if self.model is None or self.model_name != model_key:
            self.on_status("Loading model (first use downloads it)...")
            self.model = self.engine_factory(*MODELS[model_key])
            self.model_name = model_key
        return self.model

    def transcribe_chunk(self, label, audio, rate, silence_threshold):
        """Transcribe one finished chunk and report it. Returns the text (or None)."""
        audio = prepare_audio(audio, rate, silence_threshold)
        if audio is None:
            return None
        text = self.model.transcribe(audio)
        if text:
            self.on_text(label, text)
        return text or None

    def _run(self, model_key, use_speakers, use_mic):
        from .audio import AudioSource, microphone_device, open_pyaudio, speaker_loopback_device
        pa, sources = None, []
        try:
            self.load_model(model_key)
            pa, wasapi = open_pyaudio()
            if use_speakers:
                sources.append(AudioSource("Speakers", pa, speaker_loopback_device(pa, wasapi)))
            if use_mic:
                sources.append(AudioSource("Mic", pa, microphone_device(pa, wasapi)))

            self.on_status("● Listening to: " + "  +  ".join(s.name for s in sources))
            while self.running:
                time.sleep(0.1)
                for s in sources:
                    s.drain()
                for s in sources:
                    audio = s.take_ready_chunk()
                    if audio is not None:
                        self.transcribe_chunk(s.label, audio, s.rate, s.silence_threshold)
            self.on_status("Stopped")
        except Exception as e:
            self.on_status(f"Error: {e}")
        finally:
            self.running = False
            for s in sources:
                try:
                    s.close()
                except Exception:
                    pass
            if pa:
                pa.terminate()
