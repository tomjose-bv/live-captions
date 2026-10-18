# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-18

First public release.

### Added

- Live, fully local captions of speaker output (WASAPI loopback) and microphone,
  labelled "You:" and "Them:", with Moonshine (base, tiny) and faster-whisper
  (base.en, small.en) engines.
- Grey interim captions while someone is still speaking, replaced when the phrase ends.
- Editable transcript with Copy all, Copy new (only text added since the last Copy new),
  Clear, and Export to `.txt` or `.md`.
- Read screen area: drag over any part of the screen and its text is added as a
  `Screen:` line, using the offline OCR engine built into Windows.
- Scroll capture: select an area once and scroll (or hold the Down arrow); frames are
  read up to about 10 times a second and stitched together without repeating lines.
- Optional summaries through a local OpenAI-compatible LLM (Ollama by default), with a
  warning before sending text anywhere that is not this computer.
- Recording-consent notice on first run and a red banner while captioning.
- `livecaptions-bench`: reproducible ASR benchmark (WER, real-time factor, memory) on a
  LibriSpeech subset, with measured results for an i7-1185G7 laptop.
- One-command setup script and GitHub Actions CI.

### Fixed

- Bottom controls stay visible at any window size; the window has a minimum size.

[0.1.0]: https://github.com/tomjose-bv/live-captions/releases/tag/v0.1.0
