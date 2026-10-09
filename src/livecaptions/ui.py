"""Tkinter window."""

import queue
import tkinter as tk
from tkinter import scrolledtext, ttk

from .config import MODELS
from .transcriber import Transcriber
from .transcript import append_text


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
            insert, self.last_label = append_text(existing, self.last_label, label, chunk)
            self.text.insert("end", insert)
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
