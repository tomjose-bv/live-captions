# Live Captions

Real-time captions for anything playing on your Windows PC — meetings, videos, podcasts — **fully offline**.

Live Captions captures your speaker output (and optionally your microphone) and transcribes it locally into an editable text box. No audio or text ever leaves your machine, and nothing is saved to disk unless you copy it out.

## Features

- **System audio capture** via WASAPI loopback — captions whatever your speakers play, from any app
- **Optional microphone** input, so both sides of a call can be captured
- **On-device speech recognition** with a choice of models:
  | Model | Notes |
  |---|---|
  | Moonshine base | Recommended — about 3× faster than Whisper base on CPU in my testing |
  | Moonshine tiny | Fastest, lowest resource use |
  | Whisper base.en | faster-whisper, int8 on CPU |
  | Whisper small.en | Most accurate, slowest |
- **Voice-activity detection and pause detection** — text appears in natural phrases rather than fixed time slices
- **Adaptive noise floor** per device, so quiet laptop mic arrays still work
- **Editable transcript** with *Copy all* and *Clear*

## Requirements

- Windows 10/11
- Python 3.12

## Setup

```powershell
git clone https://github.com/tomjose-bv/live-captions.git
cd live-captions
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw live_captions.py
```

Models download automatically on first use.

**Tip:** to launch without a console window, create a shortcut that targets `.venv\Scripts\pythonw.exe` with `live_captions.py` as the argument, then pin it to the taskbar.

## How it works

1. **Capture.** PyAudioWPatch opens a WASAPI loopback stream on the default output device, and optionally the default microphone.
2. **Prepare.** Audio is downmixed to mono and resampled to 16 kHz.
3. **Chunk.** Audio is buffered until a pause is detected (silence or a gap in callbacks), or until 8 seconds of continuous speech.
4. **Filter.** Silero VAD skips chunks with no speech.
5. **Transcribe.** The chunk goes to Moonshine (ONNX) or faster-whisper on a background thread, and the text is appended to the UI.

## Privacy

Everything runs locally on CPU. The only network access is the one-time model download.

## License

MIT
