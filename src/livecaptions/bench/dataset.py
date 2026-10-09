"""Reproducible LibriSpeech test-clean subset.

Two selection modes, both deterministic because the archive is static:

* ``per_speaker=K`` (default, K=2): the first K utterances of every speaker in
  archive order -> 40 speakers x K. Reads the whole ~346 MB archive once.
* ``first=N``: the first N utterances in archive order. Stops streaming early, but
  the first chapters cover very few speakers, so it is mainly for quick checks.

Audio is streamed from the .tar.gz; only selected FLAC files are written to disk.
The manifest records the chosen utterance IDs.
"""

import json
import os
import tarfile
import urllib.request

ARCHIVE_URLS = [
    "https://www.openslr.org/resources/12/test-clean.tar.gz",
    "https://us.openslr.org/resources/12/test-clean.tar.gz",
    "https://openslr.elda.org/resources/12/test-clean.tar.gz",
]
MANIFEST = "manifest.jsonl"
DEFAULT_PER_SPEAKER = 2


def default_dir(per_speaker=DEFAULT_PER_SPEAKER, first=None):
    tag = f"first{first}" if first else f"{per_speaker}per-speaker"
    return os.path.join("data", f"librispeech-test-clean-{tag}")


def parse_transcripts(text):
    """Parse a LibriSpeech *.trans.txt file into {utterance_id: transcript}."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line:
            utt, _, words = line.partition(" ")
            out[utt] = words
    return out


def select_first_complete(order, transcripts, n):
    """Return the first ``n`` utterance IDs (archive order) once all have transcripts, else None."""
    if len(order) < n:
        return None
    head = order[:n]
    return head if all(u in transcripts for u in head) else None


class Selector:
    """Decides which FLAC members to keep while streaming the archive."""

    def __init__(self, first=None, per_speaker=None):
        if bool(first) == bool(per_speaker):
            raise ValueError("Give exactly one of first or per_speaker")
        self.first, self.per_speaker = first, per_speaker
        self.order, self.counts = [], {}

    def want(self, utt):
        if self.first:
            return len(self.order) < self.first
        return self.counts.get(utt.split("-")[0], 0) < self.per_speaker

    def keep(self, utt):
        self.order.append(utt)
        spk = utt.split("-")[0]
        self.counts[spk] = self.counts.get(spk, 0) + 1

    def done(self, transcripts):
        """IDs to use if selection can finish early (``first`` mode only)."""
        return select_first_complete(self.order, transcripts, self.first) if self.first else None

    def final(self, transcripts):
        ids = [u for u in self.order if u in transcripts]
        if self.first:
            return ids[:self.first] if len(ids) >= self.first else None
        return ids or None


def extract_subset(fileobj, out_dir, first=None, per_speaker=None, progress=print):
    """Stream a LibriSpeech tar.gz from ``fileobj`` and write the selected utterances."""
    os.makedirs(out_dir, exist_ok=True)
    sel = Selector(first, per_speaker)
    transcripts, chosen = {}, None
    with tarfile.open(fileobj=fileobj, mode="r|gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            base = os.path.basename(member.name)
            if base.endswith(".trans.txt"):
                transcripts.update(parse_transcripts(tar.extractfile(member).read().decode()))
            elif base.endswith(".flac") and sel.want(base[:-5]):
                with open(os.path.join(out_dir, base), "wb") as f:
                    f.write(tar.extractfile(member).read())
                sel.keep(base[:-5])
                if len(sel.order) % 10 == 0:
                    progress(f"  {len(sel.order)} utterances selected")
            chosen = sel.done(transcripts)
            if chosen:
                break
    chosen = chosen or sel.final(transcripts)
    if not chosen:
        raise RuntimeError("Archive ended before the requested utterances were found")
    for utt in set(sel.order) - set(chosen):   # drop audio we kept but cannot use
        os.remove(os.path.join(out_dir, f"{utt}.flac"))
    return chosen, transcripts


def write_manifest(out_dir, ids, transcripts):
    import soundfile as sf
    path = os.path.join(out_dir, MANIFEST)
    total = 0.0
    with open(path, "w", encoding="utf-8") as f:
        for utt in ids:
            audio = f"{utt}.flac"
            duration = sf.info(os.path.join(out_dir, audio)).duration
            total += duration
            f.write(json.dumps({"id": utt, "audio": audio, "text": transcripts[utt],
                                "duration": round(duration, 3)}) + "\n")
    return path, total


def download(per_speaker=DEFAULT_PER_SPEAKER, first=None, out_dir=None, progress=print):
    """Download a test-clean subset (see module docstring); return the manifest path."""
    import truststore
    truststore.inject_into_ssl()
    if first:
        per_speaker = None
    out_dir = out_dir or default_dir(per_speaker, first)
    if os.path.exists(os.path.join(out_dir, MANIFEST)):
        progress(f"Dataset already present: {out_dir}")
        return os.path.join(out_dir, MANIFEST)
    errors = []
    for url in ARCHIVE_URLS:
        what = f"first {first} utterances" if first else f"{per_speaker} per speaker"
        progress(f"Streaming {url} ({what})...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "livecaptions-bench"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                ids, transcripts = extract_subset(resp, out_dir, first, per_speaker, progress)
            break
        except Exception as e:   # try the next mirror, but keep the reason
            errors.append(f"{url}: {e}")
            progress(f"  failed: {e}")
    else:
        raise RuntimeError("All LibriSpeech mirrors failed:\n" + "\n".join(errors))
    path, total = write_manifest(out_dir, ids, transcripts)
    progress(f"Wrote {len(ids)} utterances ({total / 60:.1f} min of audio) to {out_dir}")
    return path


def load_manifest(path):
    """Load utterances as dicts with absolute ``audio`` paths. Accepts a dir or a file."""
    if os.path.isdir(path):
        path = os.path.join(path, MANIFEST)
    base = os.path.dirname(os.path.abspath(path))
    items = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                item["audio"] = os.path.join(base, item["audio"])
                items.append(item)
    return items
