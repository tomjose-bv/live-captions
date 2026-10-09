"""Background loop: pull audio from sources, chunk it, transcribe, report text."""

import threading
import time

from .chunking import PartialScheduler, prepare_audio
from .config import MODELS
from .engines import create_engine

# Source labels. The app knows which device audio came from, which gives a simple
# two-party attribution without speaker diarization: loopback = the other side.
LABEL_SPEAKERS = "Them"
LABEL_MIC = "You"


class Transcriber:
    def __init__(self, on_text, on_status, on_partial=None, engine_factory=create_engine,
                 clock=time.monotonic):
        self.on_text = on_text          # called with (label, text) for finalized phrases
        self.on_status = on_status
        self.on_partial = on_partial    # called with (label, text) for interim text
        self.engine_factory = engine_factory
        self.clock = clock
        self.model = None
        self.model_name = None
        self.running = False
        self.partials = on_partial is not None

    def start(self, model_key, use_speakers, use_mic, partials=True):
        self.running = True
        self.partials = partials and self.on_partial is not None
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
            if self.on_partial:
                self.on_partial(label, "")   # drop any stale interim text
            return None
        text = self.model.transcribe(audio)
        if text:
            self.on_text(label, text)
        elif self.on_partial:
            self.on_partial(label, "")
        return text or None

    def transcribe_partial(self, label, audio, rate, silence_threshold):
        """Transcribe the still-growing buffer and report interim text. Returns the text."""
        audio = prepare_audio(audio, rate, silence_threshold)
        if audio is None:
            return None
        text = self.model.transcribe(audio)
        if text:
            self.on_partial(label, text)
        return text or None

    def step(self, sources, schedulers):
        """One pass over all sources: finalize ready phrases, else maybe emit interim text."""
        for s in sources:
            s.drain()
        for s in sources:
            sched = schedulers[s.label]
            audio = s.take_ready_chunk()
            if audio is not None:
                self.transcribe_chunk(s.label, audio, s.rate, s.silence_threshold)
                sched.reset(self.clock())
            elif self.partials and sched.due(self.clock(), s.chunker.seconds):
                t0 = self.clock()
                self.transcribe_partial(s.label, s.chunker.peek(), s.rate, s.silence_threshold)
                sched.record(self.clock(), self.clock() - t0)

    def _run(self, model_key, use_speakers, use_mic):
        from .audio import AudioSource, microphone_device, open_pyaudio, speaker_loopback_device
        pa, sources = None, []
        try:
            self.load_model(model_key)
            pa, wasapi = open_pyaudio()
            if use_speakers:
                sources.append(AudioSource(LABEL_SPEAKERS, pa, speaker_loopback_device(pa, wasapi)))
            if use_mic:
                sources.append(AudioSource(LABEL_MIC, pa, microphone_device(pa, wasapi)))
            schedulers = {s.label: PartialScheduler() for s in sources}

            self.on_status("● Listening to: " + "  +  ".join(s.name for s in sources))
            while self.running:
                time.sleep(0.1)
                self.step(sources, schedulers)
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
