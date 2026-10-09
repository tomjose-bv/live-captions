"""Speech-to-text engines behind a single ``transcribe(audio_16k) -> str`` interface.

Heavy imports (onnxruntime, ctranslate2) happen lazily inside the constructors so
that the rest of the package can be imported and tested without them.
"""

from typing import Callable, Dict, Protocol


class Engine(Protocol):
    def transcribe(self, audio) -> str: ...


class MoonshineEngine:
    """Moonshine (ONNX). It has no built-in VAD, so we trim to the speech span first."""

    def __init__(self, name):
        from moonshine_onnx import MoonshineOnnxModel, load_tokenizer
        self.name = name
        self.model = MoonshineOnnxModel(model_name=name)
        self.tokenizer = load_tokenizer()

    def transcribe(self, audio):
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        speech = get_speech_timestamps(audio, VadOptions())
        if not speech:
            return ""
        audio = audio[speech[0]["start"]:speech[-1]["end"]]
        return self.tokenizer.decode_batch(self.model.generate(audio[None, :]))[0].strip()


class WhisperEngine:
    """faster-whisper (CTranslate2), int8 on CPU, greedy decoding with Silero VAD."""

    def __init__(self, name):
        from faster_whisper import WhisperModel
        self.name = name
        self.model = WhisperModel(name, device="cpu", compute_type="int8")

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=True,
                                            condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


ENGINES: Dict[str, Callable[[str], Engine]] = {
    "moonshine": MoonshineEngine,
    "whisper": WhisperEngine,
}


def create_engine(engine, name):
    """Instantiate an engine by kind ("moonshine", "whisper", or any registered name)."""
    try:
        factory = ENGINES[engine]
    except KeyError:
        raise ValueError(f"Unknown engine {engine!r}; choose from {sorted(ENGINES)}") from None
    return factory(name)
