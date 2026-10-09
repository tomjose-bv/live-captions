"""Tunable constants and the model catalogue."""

TARGET_RATE = 16000
MAX_CHUNK_SEC = 8.0      # force a transcription after this much continuous audio
MIN_CHUNK_SEC = 1.5      # don't transcribe shorter bits unless speech has stopped
PAUSE_SEC = 0.6          # gap with no audio callbacks that counts as a pause
SILENCE_RMS = 0.004      # tail quieter than this counts as a pause
IDLE_FLUSH_SEC = 1.5     # flush whatever is buffered after this long without audio

# English-only models: display name -> (engine, model id).
MODELS = {
    "Moonshine base (recommended)": ("moonshine", "moonshine/base"),
    "Moonshine tiny (fastest)": ("moonshine", "moonshine/tiny"),
    "Whisper base.en": ("whisper", "base.en"),
    "Whisper small.en (slow)": ("whisper", "small.en"),
}

# Interim ("partial") captions: re-transcribe the growing phrase buffer while speech continues.
PARTIAL_INTERVAL_SEC = 1.0   # at most this often (backs off on slow CPUs)
PARTIAL_MIN_SEC = 0.8        # don't bother until this much audio is buffered
