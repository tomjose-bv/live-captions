import numpy as np

from livecaptions.chunking import PartialScheduler, PhraseChunker
from livecaptions.transcriber import Transcriber

RATE = 16000


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class LenEngine:
    """Reports how many seconds of audio it was given, so growth is visible."""

    def __init__(self, clock=None, cost=0.0):
        self.clock, self.cost = clock, cost

    def transcribe(self, audio):
        if self.clock:
            self.clock.t += self.cost
        return f"{len(audio) / RATE:.1f}s"


class FakeSource:
    """Stands in for audio.AudioSource: no hardware, audio pushed by the test."""

    def __init__(self, label, clock):
        self.label, self.rate = label, RATE
        self.chunker = PhraseChunker(RATE, clock=clock)
        self.pending = []

    def push(self, audio):
        self.pending.append(audio)

    def drain(self):
        for a in self.pending:
            self.chunker.feed(a)
        self.pending = []

    @property
    def silence_threshold(self):
        return self.chunker.silence_threshold

    def take_ready_chunk(self):
        return self.chunker.take_ready_chunk()


def tone(seconds, amp=0.2):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_scheduler_waits_for_min_audio_and_interval():
    s = PartialScheduler(interval=1.0, min_audio=0.8)
    assert not s.due(0.0, 0.5)
    assert s.due(0.0, 1.0)
    s.record(0.0, cost=0.1)
    assert not s.due(0.5, 2.0)
    assert s.due(1.0, 2.0)


def test_scheduler_backs_off_when_model_is_slow():
    s = PartialScheduler(interval=1.0, min_audio=0.0)
    s.record(10.0, cost=1.5)        # a pass took 1.5 s -> wait 3 s
    assert not s.due(12.0, 5.0)
    assert s.due(13.0, 5.0)


def test_scheduler_reset_after_final():
    s = PartialScheduler(interval=1.0, min_audio=0.0)
    s.reset(5.0)
    assert not s.due(5.5, 3.0)
    assert s.due(6.0, 3.0)


def _make(clock, partials=True):
    events = []
    t = Transcriber(on_text=lambda label, text: events.append(("final", label, text)),
                    on_status=lambda m: None,
                    on_partial=lambda label, text: events.append(("partial", label, text)),
                    engine_factory=lambda kind, name: LenEngine(), clock=clock)
    t.load_model("Moonshine tiny (fastest)")
    t.partials = partials
    return t, events


def test_interim_text_grows_then_finalizes_on_pause():
    clock = Clock()
    t, events = _make(clock)
    src = FakeSource("Mic", clock)
    scheds = {"Mic": PartialScheduler(interval=1.0, min_audio=0.8)}

    for _ in range(3):              # three seconds of continuous speech, polled each second
        src.push(tone(1.0))
        clock.t += 1.0
        t.step([src], scheds)
    partials = [e for e in events if e[0] == "partial"]
    assert [p[2] for p in partials] == ["1.0s", "2.0s", "3.0s"]

    src.push(np.zeros(int(0.5 * RATE), dtype=np.float32))   # speaker pauses
    clock.t += 0.5
    t.step([src], scheds)
    assert events[-1] == ("final", "Mic", "3.5s")


def test_no_interim_when_disabled():
    clock = Clock()
    t, events = _make(clock, partials=False)
    src = FakeSource("Mic", clock)
    scheds = {"Mic": PartialScheduler()}
    src.push(tone(1.2))
    clock.t += 1.2
    t.step([src], scheds)
    assert events == []


def test_silent_final_clears_interim():
    clock = Clock()
    t, events = _make(clock)
    assert t.transcribe_chunk("Mic", np.zeros(RATE, dtype=np.float32), RATE, 0.004) is None
    assert events == [("partial", "Mic", "")]
