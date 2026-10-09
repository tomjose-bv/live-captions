"""Live Captions - transcribes laptop speaker output into an editable text box.

Audio is captured via WASAPI loopback and transcribed locally with faster-whisper.
Nothing is uploaded and nothing is saved to disk automatically.
"""

import truststore

# Use the Windows certificate store so the model download works behind corporate TLS inspection.
truststore.inject_into_ssl()

import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext

import numpy as np
import pyaudiowpatch as pyaudio
from faster_whisper import WhisperModel
from faster_whisper.vad import VadOptions, get_speech_timestamps

TARGET_RATE = 16000
MAX_CHUNK_SEC = 8.0      # force a transcription after this much continuous audio
MIN_CHUNK_SEC = 1.5      # don't transcribe shorter bits unless speech has stopped
PAUSE_SEC = 0.6          # gap with no audio callbacks that counts as a pause
SILENCE_RMS = 0.004      # tail quieter than this counts as a pause

# English-only models: (engine, model id). Moonshine benchmarked ~3x faster than Whisper base here.
MODELS = {
    "Moonshine base (recommended)": ("moonshine", "moonshine/base"),
    "Moonshine tiny (fastest)": ("moonshine", "moonshine/tiny"),
    "Whisper base.en": ("whisper", "base.en"),
    "Whisper small.en (slow)": ("whisper", "small.en"),
}


class SpeechModel:
    """Wraps Moonshine or faster-whisper behind one transcribe(audio_16k) -> str call."""

    def __init__(self, engine, name):
        self.engine = engine
        if engine == "moonshine":
            from moonshine_onnx import MoonshineOnnxModel, load_tokenizer
            self.model = MoonshineOnnxModel(model_name=name)
            self.tokenizer = load_tokenizer()
        else:
            self.model = WhisperModel(name, device="cpu", compute_type="int8")

    def transcribe(self, audio):
        if self.engine == "whisper":
            segments, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=True,
                                                condition_on_previous_text=False)
            return " ".join(s.text.strip() for s in segments).strip()
        # Moonshine has no built-in VAD: keep only the span that contains speech.
        speech = get_speech_timestamps(audio, VadOptions())
        if not speech:
            return ""
        audio = audio[speech[0]["start"]:speech[-1]["end"]]
        return self.tokenizer.decode_batch(self.model.generate(audio[None, :]))[0].strip()


def to_16k_mono(audio, rate):
    if rate == TARGET_RATE:
        return audio.astype(np.float32)
    n_out = int(len(audio) * TARGET_RATE / rate)
    return np.interp(np.linspace(0, len(audio) - 1, n_out),
                     np.arange(len(audio)), audio).astype(np.float32)


class AudioSource:
    """One capture device (speaker loopback or microphone) with its own buffer."""

    def __init__(self, label, pa, dev):
        self.label = label
        self.name = dev["name"]
        self.rate = int(dev["defaultSampleRate"])
        self.q = queue.Queue()
        self.buf, self.buf_len, self.last_audio = [], 0, time.time()
        self.noise = None   # running estimate of the background level of this device
        channels = dev["maxInputChannels"]

        def callback(in_data, frame_count, time_info, status):
            samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
            self.q.put(samples.reshape(-1, channels).mean(axis=1))
            return (None, pyaudio.paContinue)

        self.stream = pa.open(format=pyaudio.paInt16, channels=channels, rate=self.rate,
                              input=True, input_device_index=dev["index"],
                              frames_per_buffer=1024, stream_callback=callback)

    def drain(self):
        while True:
            try:
                chunk = self.q.get_nowait()
            except queue.Empty:
                return
            self.buf.append(chunk)
            self.buf_len += len(chunk)
            self.last_audio = time.time()
            # Track the noise floor: drop quickly to quieter levels, rise slowly.
            rms = float(np.sqrt(np.mean(chunk ** 2)))
            if self.noise is None or rms < self.noise:
                self.noise = rms
            else:
                self.noise += (rms - self.noise) * 0.002

    @property
    def silence_threshold(self):
        # Quiet devices (e.g. laptop mic arrays) get a threshold relative to their own noise floor.
        return min(SILENCE_RMS, max(3 * (self.noise or 0.0), 0.0004))

    def take_ready_chunk(self):
        """Return buffered audio if a phrase looks complete, else None."""
        if not self.buf_len:
            return None
        secs = self.buf_len / self.rate
        idle = time.time() - self.last_audio
        tail = np.concatenate(self.buf[-20:])[-int(0.4 * self.rate):]
        paused = idle > PAUSE_SEC or np.sqrt(np.mean(tail ** 2)) < self.silence_threshold
        if secs >= MAX_CHUNK_SEC or (secs >= MIN_CHUNK_SEC and paused) or idle > 1.5:
            audio = np.concatenate(self.buf)
            self.buf, self.buf_len = [], 0
            return audio
        return None

    def close(self):
        self.stream.stop_stream()
        self.stream.close()


class Transcriber:
    def __init__(self, on_text, on_status):
        self.on_text = on_text          # called with (label, text)
        self.on_status = on_status
        self.model = None
        self.model_name = None
        self.running = False

    def start(self, model_key, use_speakers, use_mic):
        self.running = True
        threading.Thread(target=self._run, args=(model_key, use_speakers, use_mic),
                         daemon=True).start()

    def stop(self):
        self.running = False

    @staticmethod
    def _speaker_loopback(pa, wasapi):
        dev = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if dev.get("isLoopbackDevice"):
            return dev
        for lb in pa.get_loopback_device_info_generator():
            if dev["name"] in lb["name"]:
                return lb
        raise RuntimeError("No loopback device found for the default speakers.")

    def _transcribe(self, source, audio):
        audio = to_16k_mono(audio, source.rate)
        if np.sqrt(np.mean(audio ** 2)) < source.silence_threshold / 2:
            return
        peak = float(np.max(np.abs(audio)))
        if 0 < peak < 0.5:
            audio = audio * (0.5 / peak)   # boost quiet input before recognition
        text = self.model.transcribe(audio)
        if text:
            self.on_text(source.label, text)

    def _run(self, model_key, use_speakers, use_mic):
        pa, sources = None, []
        try:
            if self.model is None or self.model_name != model_key:
                self.on_status("Loading model (first use downloads it)...")
                self.model = SpeechModel(*MODELS[model_key])
                self.model_name = model_key
            pa = pyaudio.PyAudio()
            wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            if use_speakers:
                sources.append(AudioSource("Speakers", pa, self._speaker_loopback(pa, wasapi)))
            if use_mic:
                mic = pa.get_device_info_by_index(wasapi["defaultInputDevice"])
                sources.append(AudioSource("Mic", pa, mic))

            self.on_status("● Listening to: " + "  +  ".join(s.name for s in sources))
            while self.running:
                time.sleep(0.1)
                for s in sources:
                    s.drain()
                for s in sources:
                    audio = s.take_ready_chunk()
                    if audio is not None:
                        self._transcribe(s, audio)
            self.on_status("Stopped")
        except Exception as e:
            self.on_status(f"Error: {e}")
        finally:
            self.running = False
            for s in sources:
                try:
                    s.close()
                except Exception:
                    pass
            if pa:
                pa.terminate()


class App:
    def __init__(self, root):
        self.root = root
        root.title("Live Captions")
        root.geometry("720x480")
        self.text_q = queue.Queue()
        self.status_q = queue.Queue()
        self.transcriber = Transcriber(lambda label, text: self.text_q.put((label, text)),
                                       self.status_q.put)
        self.last_label = None

        bar = ttk.Frame(root, padding=6)
        bar.pack(fill="x")
        self.start_btn = ttk.Button(bar, text="Start", command=self.toggle)
        self.start_btn.pack(side="left")
        ttk.Label(bar, text="  Model:").pack(side="left")
        self.model = ttk.Combobox(bar, values=list(MODELS), state="readonly", width=30)
        self.model.set(next(iter(MODELS)))
        self.model.pack(side="left")
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="right")
        ttk.Button(bar, text="Copy all", command=self.copy_all).pack(side="right", padx=4)

        self.text = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 12), undo=True)
        self.text.pack(fill="both", expand=True, padx=6)

        bottom = ttk.Frame(root, padding=6)
        bottom.pack(fill="x")
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Auto-scroll", variable=self.autoscroll).pack(side="right")
        self.use_mic = tk.BooleanVar(value=True)
        self.use_speakers = tk.BooleanVar(value=True)
        self.source_checks = [
            ttk.Checkbutton(bottom, text="Microphone", variable=self.use_mic),
            ttk.Checkbutton(bottom, text="Speakers", variable=self.use_speakers),
        ]
        for cb in self.source_checks:
            cb.pack(side="right", padx=4)
        self.status = ttk.Label(bottom, text="Stopped")
        self.status.pack(side="left")

        menu = tk.Menu(root, tearoff=0)
        for label, ev in (("Cut", "<<Cut>>"), ("Copy", "<<Copy>>"), ("Paste", "<<Paste>>")):
            menu.add_command(label=label, command=lambda e=ev: self.text.event_generate(e))
        menu.add_separator()
        menu.add_command(label="Select all", command=lambda: self.text.tag_add("sel", "1.0", "end"))
        self.text.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.poll()

    def set_controls_enabled(self, enabled):
        self.start_btn.config(text="Start" if enabled else "Stop")
        self.model.config(state="readonly" if enabled else "disabled")
        for cb in self.source_checks:
            cb.config(state="normal" if enabled else "disabled")

    def toggle(self):
        if self.transcriber.running:
            self.transcriber.stop()
            self.set_controls_enabled(True)
        elif not (self.use_speakers.get() or self.use_mic.get()):
            self.status.config(text="Tick Speakers and/or Microphone first")
        else:
            self.transcriber.start(self.model.get(), self.use_speakers.get(), self.use_mic.get())
            self.set_controls_enabled(False)

    def copy_all(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))
        self.status.config(text="Copied all text to clipboard")

    def clear(self):
        self.text.delete("1.0", "end")
        self.last_label = None

    def poll(self):
        while not self.text_q.empty():
            label, chunk = self.text_q.get_nowait()
            existing = self.text.get("1.0", "end-1c")
            if label != self.last_label:
                # New speaker source: start a labelled line.
                prefix = ("\n" if existing and not existing.endswith("\n") else "") + f"[{label}] "
                self.last_label = label
            else:
                prefix = "" if not existing or existing[-1] in " \n" else " "
            self.text.insert("end", prefix + chunk)
            if self.autoscroll.get():
                self.text.see("end")
        while not self.status_q.empty():
            msg = self.status_q.get_nowait()
            self.status.config(text=msg)
            if msg.startswith("Error") or msg == "Stopped":
                self.set_controls_enabled(True)
        self.root.after(150, self.poll)

    def on_close(self):
        self.transcriber.stop()
        self.root.after(300, self.root.destroy)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
