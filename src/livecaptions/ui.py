"""Tkinter window."""

import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from . import export, state, summarize
from .config import MODELS
from .transcriber import Transcriber
from .transcript import append_text

BANNER_IDLE = ("Captions stay on this PC. Before captioning a call or meeting, "
               "tell everyone and get their consent.", "#fff4ce", "#5c4400")
BANNER_LIVE = ("● CAPTIONING LIVE — make sure everyone being captioned has agreed.",
               "#c42b1c", "#ffffff")


class App:
    def __init__(self, root, state_path=None, show_consent=True):
        self.root = root
        root.title("Live Captions")
        root.geometry("820x520")
        self.state_path = state_path
        self.text_q = queue.Queue()     # ("final" | "partial", label, text)
        self.status_q = queue.Queue()
        self.ui_q = queue.Queue()       # callables to run on the Tk thread
        self.transcriber = Transcriber(
            on_text=lambda label, text: self.text_q.put(("final", label, text)),
            on_status=self.status_q.put,
            on_partial=lambda label, text: self.text_q.put(("partial", label, text)))
        self.last_label = None
        self.partial_active = False
        self.last_summary = None
        self.summarizing = False

        self.banner = tk.Label(root, anchor="w", padx=8, pady=4, font=("Segoe UI", 9, "bold"))
        self.banner.pack(fill="x")
        self.set_banner(live=False)

        bar = ttk.Frame(root, padding=6)
        bar.pack(fill="x")
        self.start_btn = ttk.Button(bar, text="Start", command=self.toggle)
        self.start_btn.pack(side="left")
        ttk.Label(bar, text="  Model:").pack(side="left")
        self.model = ttk.Combobox(bar, values=list(MODELS), state="readonly", width=28)
        self.model.set(next(iter(MODELS)))
        self.model.pack(side="left")
        ttk.Button(bar, text="Clear", command=self.clear).pack(side="right")
        ttk.Button(bar, text="Copy all", command=self.copy_all).pack(side="right", padx=4)
        ttk.Button(bar, text="Export…", command=self.export).pack(side="right")
        self.summary_btn = ttk.Button(bar, text="Summarize", command=self.summarize)
        self.summary_btn.pack(side="right", padx=4)

        self.text = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 12), undo=True)
        self.text.pack(fill="both", expand=True, padx=6)
        self.text.tag_configure("partial", foreground="#888888", font=("Segoe UI", 12, "italic"))

        bottom = ttk.Frame(root, padding=6)
        bottom.pack(fill="x")
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Auto-scroll", variable=self.autoscroll).pack(side="right")
        self.live_preview = tk.BooleanVar(value=True)
        self.preview_check = ttk.Checkbutton(bottom, text="Live preview", variable=self.live_preview)
        self.preview_check.pack(side="right", padx=4)
        self.use_mic = tk.BooleanVar(value=True)
        self.use_speakers = tk.BooleanVar(value=True)
        self.source_checks = [
            ttk.Checkbutton(bottom, text="Microphone (You)", variable=self.use_mic),
            ttk.Checkbutton(bottom, text="Speakers (Them)", variable=self.use_speakers),
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
        if show_consent and state.needs_consent_notice(state.load_state(self.state_path)):
            root.after(200, self.show_consent_notice)

    # ---------- consent ----------

    def set_banner(self, live):
        text, bg, fg = BANNER_LIVE if live else BANNER_IDLE
        self.banner.config(text=text, bg=bg, fg=fg)

    def show_consent_notice(self):
        win = tk.Toplevel(self.root)
        win.title("Before you start")
        win.transient(self.root)
        win.resizable(False, False)
        frame = ttk.Frame(win, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Get consent before you caption people",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(frame, text=state.CONSENT_TEXT, wraplength=440, justify="left").pack(
            anchor="w", pady=(8, 12))

        def accept():
            try:
                state.save_state(state.acknowledge_consent(state.load_state(self.state_path)),
                                 self.state_path)
            except OSError:
                pass   # can't persist: we'll simply show the notice again next time
            win.destroy()

        ttk.Button(frame, text="I understand", command=accept).pack(anchor="e")
        win.protocol("WM_DELETE_WINDOW", accept)
        win.update_idletasks()   # centre over the main window
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 3
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()
        win.focus_set()

    # ---------- controls ----------

    def set_controls_enabled(self, enabled):
        self.start_btn.config(text="Start" if enabled else "Stop")
        self.model.config(state="readonly" if enabled else "disabled")
        for cb in self.source_checks + [self.preview_check]:
            cb.config(state="normal" if enabled else "disabled")
        self.set_banner(live=not enabled)

    def toggle(self):
        if self.transcriber.running:
            self.transcriber.stop()
            self.set_controls_enabled(True)
        elif not (self.use_speakers.get() or self.use_mic.get()):
            self.status.config(text="Tick Speakers and/or Microphone first")
        else:
            self.transcriber.start(self.model.get(), self.use_speakers.get(), self.use_mic.get(),
                                   partials=self.live_preview.get())
            self.set_controls_enabled(False)

    def final_text(self):
        """Transcript text excluding any interim (grey) caption."""
        end = "partial_start" if self.partial_active else "end-1c"
        return self.text.get("1.0", end)

    def copy_all(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.final_text())
        self.status.config(text="Copied all text to clipboard")

    def clear(self):
        self.text.delete("1.0", "end")
        self.last_label = None
        self.partial_active = False
        self.last_summary = None

    # ---------- export ----------

    def export(self):
        text = self.final_text().strip()
        if not text:
            self.status.config(text="Nothing to export yet")
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export transcript", defaultextension=".md",
            initialfile=export.default_filename("md"),
            filetypes=[("Markdown", "*.md"), ("Plain text", "*.txt")])
        if not path:
            return
        fmt = "txt" if path.lower().endswith(".txt") else "md"
        content = export.render(text, fmt, model=self.transcriber.model_name,
                                summary=self.last_summary)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            messagebox.showerror("Export failed", str(e), parent=self.root)
            return
        self.status.config(text=f"Exported to {path}")

    # ---------- summaries ----------

    def summarize(self):
        if self.summarizing:
            return
        text = self.final_text().strip()
        if not text:
            self.status.config(text="Nothing to summarize yet")
            return
        settings = summarize.LLMSettings.from_env()
        if not summarize.is_local_url(settings.base_url):
            ok = messagebox.askyesno(
                "Send transcript off this PC?",
                f"LLM_BASE_URL points to {settings.base_url}, which is not this computer.\n\n"
                "Summarizing will send the transcript there. Continue?", parent=self.root)
            if not ok:
                return
        self.summarizing = True
        self.summary_btn.config(state="disabled")
        self.status.config(text=f"Summarizing with {settings.model}…")

        def work():
            try:
                result, error = summarize.summarize(text, settings), None
            except summarize.SummaryError as e:
                result, error = None, str(e)
            except Exception as e:   # never let a background failure kill the app
                result, error = None, f"Unexpected error: {e}"
            self.ui_q.put(lambda: self._summary_done(result, error, settings))

        threading.Thread(target=work, daemon=True).start()

    def _summary_done(self, result, error, settings):
        self.summarizing = False
        self.summary_btn.config(state="normal")
        if error:
            self.status.config(text="Summary unavailable")
            messagebox.showinfo("Summary unavailable", error, parent=self.root)
            return
        self.last_summary = result
        self.status.config(text="Summary ready (included in Markdown/text export)")
        win = tk.Toplevel(self.root)
        win.title(f"Summary — {settings.model}")
        win.geometry("600x420")
        box = scrolledtext.ScrolledText(win, wrap="word", font=("Segoe UI", 11))
        box.pack(fill="both", expand=True, padx=6, pady=6)
        box.insert("1.0", result)
        btns = ttk.Frame(win, padding=6)
        btns.pack(fill="x")

        def copy():
            self.root.clipboard_clear()
            self.root.clipboard_append(box.get("1.0", "end-1c"))

        ttk.Button(btns, text="Copy", command=copy).pack(side="right")
        ttk.Label(btns, text="AI-generated from an automatic transcript — check before sharing.",
                  foreground="#666666").pack(side="left")

    # ---------- transcript updates ----------

    def clear_partial(self):
        if self.partial_active:
            self.text.config(undo=False)    # keep interim churn out of the undo history
            self.text.delete("partial_start", "end-1c")
            self.text.config(undo=True)
            self.partial_active = False

    def show_partial(self, label, chunk):
        self.clear_partial()
        if not chunk:
            return
        insert, _ = append_text(self.final_text(), self.last_label, label, chunk)
        self.text.config(undo=False)
        self.text.mark_set("partial_start", "end-1c")
        self.text.mark_gravity("partial_start", "left")
        self.text.insert("end", insert, "partial")
        self.text.config(undo=True)
        self.partial_active = True

    def add_final(self, label, chunk):
        self.clear_partial()
        insert, self.last_label = append_text(self.final_text(), self.last_label, label, chunk)
        self.text.insert("end", insert)

    def poll(self):
        changed = False
        while not self.text_q.empty():
            kind, label, chunk = self.text_q.get_nowait()
            if kind == "partial":
                self.show_partial(label, chunk)
            else:
                self.add_final(label, chunk)
            changed = True
        if changed and self.autoscroll.get():
            self.text.see("end")
        while not self.status_q.empty():
            msg = self.status_q.get_nowait()
            self.status.config(text=msg)
            if msg.startswith("Error") or msg == "Stopped":
                self.clear_partial()
                self.set_controls_enabled(True)
        while not self.ui_q.empty():
            self.ui_q.get_nowait()()
        self.root.after(150, self.poll)

    def on_close(self):
        self.transcriber.stop()
        self.root.after(300, self.root.destroy)
