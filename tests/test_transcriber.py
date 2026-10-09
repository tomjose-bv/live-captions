import numpy as np
import pytest

from livecaptions import engines
from livecaptions.transcriber import Transcriber
from livecaptions.transcript import append_text


class FakeEngine:
    def __init__(self, name, reply="hello world"):
        self.name = name
        self.reply = reply
        self.calls = []

    def transcribe(self, audio):
        self.calls.append(audio)
        return self.reply


def tone(seconds, amp=0.2, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_create_engine_uses_registry(monkeypatch):
    monkeypatch.setitem(engines.ENGINES, "fake", FakeEngine)
    eng = engines.create_engine("fake", "tiny")
    assert isinstance(eng, FakeEngine) and eng.name == "tiny"


def test_create_engine_rejects_unknown():
    with pytest.raises(ValueError):
        engines.create_engine("nope", "x")


def test_transcriber_loads_model_once():
    made = []

    def factory(kind, name):
        made.append((kind, name))
        return FakeEngine(name)

    statuses = []
    t = Transcriber(on_text=lambda *a: None, on_status=statuses.append, engine_factory=factory)
    t.load_model("Moonshine tiny (fastest)")
    t.load_model("Moonshine tiny (fastest)")
    assert made == [("moonshine", "moonshine/tiny")]
    assert statuses and "Loading" in statuses[0]


def test_transcribe_chunk_reports_text_and_resamples():
    texts = []
    t = Transcriber(on_text=lambda label, text: texts.append((label, text)),
                    on_status=lambda m: None, engine_factory=lambda k, n: FakeEngine(n))
    t.load_model("Whisper base.en")
    result = t.transcribe_chunk("Speakers", tone(1.0, rate=48000), 48000, 0.004)
    assert result == "hello world"
    assert texts == [("Speakers", "hello world")]
    assert len(t.model.calls[0]) == 16000


def test_transcribe_chunk_skips_silence():
    t = Transcriber(on_text=lambda *a: pytest.fail("should not emit"),
                    on_status=lambda m: None, engine_factory=lambda k, n: FakeEngine(n))
    t.load_model("Whisper base.en")
    assert t.transcribe_chunk("Mic", np.zeros(16000, dtype=np.float32), 16000, 0.004) is None
    assert t.model.calls == []


def test_empty_engine_output_not_emitted():
    t = Transcriber(on_text=lambda *a: pytest.fail("should not emit"),
                    on_status=lambda m: None, engine_factory=lambda k, n: FakeEngine(n, reply=""))
    t.load_model("Whisper base.en")
    assert t.transcribe_chunk("Mic", tone(1.0), 16000, 0.004) is None


def test_append_text_labels_new_source():
    s, label = append_text("", None, "You", "hi")
    assert (s, label) == ("You: hi", "You")
    s, label = append_text("You: hi", "You", "You", "there")
    assert s == " there"
    s, label = append_text("You: hi there", "You", "Them", "yo")
    assert s == "\nThem: yo" and label == "Them"


def test_append_after_user_typed_newline_has_no_extra_blank_line():
    s, _ = append_text("You: hi\n", "You", "Them", "yo")
    assert s == "Them: yo"


def test_source_labels_are_you_and_them():
    from livecaptions import transcriber
    assert transcriber.LABEL_MIC == "You"
    assert transcriber.LABEL_SPEAKERS == "Them"
