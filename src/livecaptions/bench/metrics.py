"""Text normalisation, WER and summary statistics."""

import re

import numpy as np

_KEEP = re.compile(r"[^a-z0-9' ]+")


def normalize(text):
    """Lower-case, map hyphens to spaces, drop punctuation except apostrophes, squash spaces.

    Deliberately simple and engine-neutral. It does *not* expand numbers or
    abbreviations ("2" vs "two", "Mr." vs "mister"), which penalises engines that
    emit digits; see the README benchmark notes.
    """
    text = text.lower().replace("-", " ")
    text = _KEEP.sub(" ", text)
    text = re.sub(r"\s+'|'\s+", " ", f" {text} ")   # stray quote marks, keep don't / o'clock
    return " ".join(text.split())


def corpus_wer(references, hypotheses):
    """Corpus-level WER (total edits / total reference words) after normalisation."""
    import jiwer
    refs = [normalize(r) for r in references]
    hyps = [normalize(h) for h in hypotheses]
    pairs = [(r, h) for r, h in zip(refs, hyps) if r]
    if not pairs:
        raise ValueError("No non-empty references")
    refs, hyps = zip(*pairs)
    return jiwer.wer(list(refs), list(hyps))


def percentile(values, q):
    return float(np.percentile(np.asarray(values, dtype=float), q)) if len(values) else float("nan")
