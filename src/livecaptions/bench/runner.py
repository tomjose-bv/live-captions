"""Run one engine over a list of utterances and collect accuracy/latency/CPU numbers.

Each utterance is treated as one chunk, transcribed through the same
``prepare_audio`` + engine path the live app uses.
"""

import time

from ..chunking import prepare_audio
from ..config import TARGET_RATE
from ..engines import create_engine, files_size_bytes
from .metrics import corpus_wer, percentile


def load_audio(path):
    import soundfile as sf
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    return audio.mean(axis=1), rate


def _peak_rss_mb():
    try:
        import psutil
        info = psutil.Process().memory_info()
        return getattr(info, "peak_wset", info.rss) / 2**20
    except Exception:
        return None


def run_engine(kind, name, utterances, engine_factory=create_engine, audio_loader=load_audio,
               warmup=1, progress=None):
    """Benchmark ``kind:name`` on ``utterances`` (dicts with audio, text, duration)."""
    t0 = time.perf_counter()
    engine = engine_factory(kind, name)
    load_s = time.perf_counter() - t0

    clips = []
    for u in utterances:
        audio, rate = audio_loader(u["audio"])
        prepared = prepare_audio(audio, rate, silence_threshold=0.0)
        clips.append((u, prepared if prepared is not None else audio))

    for u, audio in clips[:warmup]:   # first call pays one-off graph/allocation costs
        engine.transcribe(audio)

    rows = []
    wall_total = cpu_total = 0.0
    for i, (u, audio) in enumerate(clips):
        c0, w0 = time.process_time(), time.perf_counter()
        hyp = engine.transcribe(audio)
        wall = time.perf_counter() - w0
        cpu = time.process_time() - c0
        wall_total += wall
        cpu_total += cpu
        rows.append({"id": u["id"], "duration": len(audio) / TARGET_RATE, "latency_s": wall,
                     "cpu_s": cpu, "ref": u["text"], "hyp": hyp})
        if progress:
            progress(i + 1, len(clips))

    audio_total = sum(r["duration"] for r in rows)
    latencies = [r["latency_s"] for r in rows]
    size = None
    if hasattr(engine, "model_files"):
        try:
            size = files_size_bytes(engine.model_files())
        except Exception:
            size = None
    return {
        "engine": f"{kind}:{name}",
        "utterances": len(rows),
        "audio_s": audio_total,
        "wer": corpus_wer([r["ref"] for r in rows], [r["hyp"] for r in rows]),
        "rtf": wall_total / audio_total if audio_total else float("nan"),
        "latency_p50_s": percentile(latencies, 50),
        "latency_p95_s": percentile(latencies, 95),
        "cpu_s_per_audio_s": cpu_total / audio_total if audio_total else float("nan"),
        "avg_cores_busy": cpu_total / wall_total if wall_total else float("nan"),
        "load_s": load_s,
        "model_size_mb": size / 1e6 if size else None,
        "peak_rss_mb": _peak_rss_mb(),
        "rows": rows,
    }
