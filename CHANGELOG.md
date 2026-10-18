# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-10-18

### Added

- Snapshots: watch a screen area and save a picture each time its content changes, with
  its text added to the transcript and a `snapshots.md` timeline in the chosen folder.
- Recordings can include the microphone, mixed with the PC's sound
  (Recording: PC sound / PC sound + mic / No sound).
- README GIFs of Scroll capture and Snapshots, and `scripts/make_demo_gifs.py` to remake them.

### Changed

- The screen tools (Read screen area, Scroll capture, Snapshots, Record area) are now in one
  **Screen ▾** menu, so the window's minimum width dropped from 1,528 pixels (0.2.0) to 1,246 on a
  1920×1080 laptop screen.

### Fixed

- Scroll capture no longer replaces a line it already read with a garbled reading of the
  same line cut in half at the top edge of the next frame.

## [0.2.0] - 2026-10-18

### Added

- Record area: record any part of the screen to an `.mp4` file (H.264, 15 frames a second),
  optionally with the sound the PC is playing, until you click Stop. The red Stop bar is
  hidden from the recording, and silence is filled in so the sound stays in step.

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

[0.3.0]: https://github.com/tomjose-bv/live-captions/releases/tag/v0.3.0
[0.2.0]: https://github.com/tomjose-bv/live-captions/releases/tag/v0.2.0
[0.1.0]: https://github.com/tomjose-bv/live-captions/releases/tag/v0.1.0
