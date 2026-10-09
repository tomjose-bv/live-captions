import io
import json
import tarfile

import numpy as np
import pytest

from livecaptions.bench import cli, dataset, metrics, runner


# ---------- metrics ----------

def test_normalize_handles_case_punctuation_and_apostrophes():
    assert metrics.normalize("Hello, World! Don't-stop 'quoted'") == "hello world don't stop quoted"


def test_wer_perfect_after_normalisation():
    assert metrics.corpus_wer(["HELLO WORLD"], ["Hello, world."]) == 0.0


def test_wer_is_corpus_level():
    # 1 substitution in 2 words + 0 errors in 4 words = 1/6, not mean(0.5, 0).
    w = metrics.corpus_wer(["a b", "c d e f"], ["a x", "c d e f"])
    assert w == pytest.approx(1 / 6)


def test_wer_counts_deletions_and_insertions():
    assert metrics.corpus_wer(["one two three"], ["one three"]) == pytest.approx(1 / 3)
    assert metrics.corpus_wer(["one two"], ["one two three"]) == pytest.approx(1 / 2)


def test_wer_rejects_all_empty_refs():
    with pytest.raises(ValueError):
        metrics.corpus_wer([""], ["x"])


def test_percentile():
    assert metrics.percentile([1, 2, 3, 4, 5], 50) == 3
    assert np.isnan(metrics.percentile([], 50))


# ---------- dataset ----------

def _make_archive(chapters):
    """chapters: {(spk, ch): [(utt_suffix, text), ...]} -> gzipped tar bytes in LibriSpeech layout.

    The transcript file is written *after* the audio of its chapter, like the real archive.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name, data):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for (spk, ch), utts in chapters.items():
            lines = []
            for suffix, text in utts:
                utt = f"{spk}-{ch}-{suffix}"
                add(f"LibriSpeech/test-clean/{spk}/{ch}/{utt}.flac", b"fake-flac")
                lines.append(f"{utt} {text}")
            add(f"LibriSpeech/test-clean/{spk}/{ch}/{spk}-{ch}.trans.txt",
                ("\n".join(lines) + "\n").encode())
    buf.seek(0)
    return buf


CHAPTERS = {
    ("1", "10"): [("0000", "A B"), ("0001", "C D"), ("0002", "E F")],
    ("2", "20"): [("0000", "G H"), ("0001", "I J")],
    ("3", "30"): [("0000", "K L")],
}


def test_parse_transcripts():
    assert dataset.parse_transcripts("1-2-3 HELLO THERE\n\n1-2-4 BYE\n") == {
        "1-2-3": "HELLO THERE", "1-2-4": "BYE"}


def test_extract_first_n(tmp_path):
    ids, tr = dataset.extract_subset(_make_archive(CHAPTERS), tmp_path, first=4,
                                     progress=lambda m: None)
    assert ids == ["1-10-0000", "1-10-0001", "1-10-0002", "2-20-0000"]
    assert tr["2-20-0000"] == "G H"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"{i}.flac" for i in ids)


def test_extract_per_speaker(tmp_path):
    ids, _ = dataset.extract_subset(_make_archive(CHAPTERS), tmp_path, per_speaker=2,
                                    progress=lambda m: None)
    assert ids == ["1-10-0000", "1-10-0001", "2-20-0000", "2-20-0001", "3-30-0000"]


def test_selector_requires_one_mode():
    with pytest.raises(ValueError):
        dataset.Selector()
    with pytest.raises(ValueError):
        dataset.Selector(first=1, per_speaker=1)


def test_load_manifest_resolves_paths(tmp_path):
    (tmp_path / "manifest.jsonl").write_text(
        json.dumps({"id": "x", "audio": "x.flac", "text": "HI", "duration": 1.0}) + "\n")
    items = dataset.load_manifest(str(tmp_path))
    assert items[0]["audio"] == str(tmp_path / "x.flac")


# ---------- runner with a fake engine ----------

class EchoEngine:
    """Returns a scripted transcript per call; reports a fake model file."""

    def __init__(self, replies, model_file):
        self.replies = list(replies)
        self.model_file = model_file

    def transcribe(self, audio):
        assert audio.dtype == np.float32
        return self.replies.pop(0)

    def model_files(self):
        return [self.model_file]


def test_run_engine_with_fake(tmp_path):
    model = tmp_path / "model.bin"
    model.write_bytes(b"x" * 2_000_000)
    utts = [{"id": "a", "audio": "a", "text": "HELLO WORLD", "duration": 1.0},
            {"id": "b", "audio": "b", "text": "GOOD MORNING", "duration": 2.0}]
    clips = {"a": 1.0, "b": 2.0}
    # warm-up consumes the first reply
    factory = lambda kind, name: EchoEngine(["warm", "hello world", "good evening"], str(model))

    def loader(path):
        sr = 48000
        return (0.1 * np.ones(int(clips[path] * sr), dtype=np.float32), sr)

    r = runner.run_engine("fake", "m", utts, engine_factory=factory, audio_loader=loader)
    assert r["engine"] == "fake:m"
    assert r["utterances"] == 2
    assert r["audio_s"] == pytest.approx(3.0)
    assert r["wer"] == pytest.approx(1 / 4)
    assert r["model_size_mb"] == pytest.approx(2.0)
    assert r["rtf"] >= 0 and r["latency_p95_s"] >= r["latency_p50_s"]
    assert [row["hyp"] for row in r["rows"]] == ["hello world", "good evening"]


# ---------- cli helpers ----------

def test_parse_engines():
    assert cli.parse_engines("moonshine:moonshine/tiny, whisper:base.en") == [
        ("moonshine", "moonshine/tiny"), ("whisper", "base.en")]
    with pytest.raises(Exception):
        cli.parse_engines("whisper")


def test_markdown_table_marks_missing_values_tbd():
    row = {"engine": "x:y", "wer": 0.05, "rtf": 0.1, "latency_p50_s": 0.2, "latency_p95_s": 0.4,
           "cpu_s_per_audio_s": 0.3, "avg_cores_busy": 3.0, "model_size_mb": None,
           "peak_rss_mb": 300.0, "load_s": 1.0}
    table = cli.markdown_table([row, {"engine": "bad:z", "error": "boom"}])
    assert "| x:y | 5.00 | 0.100 |" in table
    assert "TBD" in table
    assert "error: boom" in table
