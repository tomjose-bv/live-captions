"""Tkinter window."""

import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from . import export, ocr, recorder, state, summarize
from .config import MODELS
from .transcriber import Transcriber
from .transcript import append_text

BANNER_IDLE = ("Captions stay on this PC. Before captioning a call or meeting, "
               "tell everyone and get their consent.", "#fff4ce", "#5c4400")
BANNER_LIVE = ("● CAPTIONING LIVE — make sure everyone being captioned has agreed.",
               "#c42b1c", "#ffffff")


SCROLL_INTERVAL_MS = 100      # look again as soon as the previous frame is read (~8-10 fps)
SCROLL_MAX_SECONDS = 15 * 60  # safety stop if the user forgets


def exclude_from_capture(win):
    """Hide a helper window from screenshots (Windows 10 2004+); harmless elsewhere."""
    try:
        import ctypes

        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, 0x11)   # WDA_EXCLUDEFROMCAPTURE
    except (AttributeError, OSError):
        pass


def virtual_screen(root):
    """(left, top, width, height) of the desktop spanning every monitor."""
    try:
        import ctypes

        metric = ctypes.windll.user32.GetSystemMetrics
        left, top, width, height = metric(76), metric(77), metric(78), metric(79)
        if width and height:
            return left, top, width, height
    except (AttributeError, OSError):
        pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


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
        ttk.Button(bar, text="Copy new", command=self.copy_new).pack(side="right")
        self.screen_btn = ttk.Button(bar, text="Read screen area", command=self.pick_screen_area)
        self.screen_btn.pack(side="right", padx=4)
        self.scroll_btn = ttk.Button(bar, text="Scroll capture", command=self.pick_scroll_area)
        self.scroll_btn.pack(side="right")
        self.record_btn = ttk.Button(bar, text="Record area", command=self.pick_record_area)
        self.record_btn.pack(side="right", padx=4)
        ttk.Button(bar, text="Export…", command=self.export).pack(side="right")
        self.summary_btn = ttk.Button(bar, text="Summarize", command=self.summarize)
        self.summary_btn.pack(side="right", padx=4)

        # Pack the bottom bar before the transcript so the expanding text box can never
        # squeeze it out of view; the text box gets whatever height is left.
        bottom = ttk.Frame(root, padding=6)
        bottom.pack(side="bottom", fill="x")
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Auto-scroll", variable=self.autoscroll).pack(side="right")
        self.record_sound = tk.BooleanVar(value=True)
        ttk.Checkbutton(bottom, text="Record sound",
                        variable=self.record_sound).pack(side="right", padx=4)
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

        # A modest requested height keeps the window's natural size small; the text box
        # still expands to fill the window.
        self.text = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 12),
                                              undo=True, height=8)
        self.text.pack(fill="both", expand=True, padx=6)
        self.text.tag_configure("partial", foreground="#888888", font=("Segoe UI", 12, "italic"))
        # Everything before this mark has already been copied with "Copy new".
        self.text.mark_set("copied_upto", "1.0")
        self.text.mark_gravity("copied_upto", "left")
        self.reading_screen = False
        self.scroll = None
        self.recording = None

        # Never let the window shrink below the size needed to show every control.
        root.update_idletasks()
        root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())

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

    def copy_new(self):
        """Copy only the text added since the last "Copy new"."""
        end = "partial_start" if self.partial_active else "end-1c"
        new = self.text.get("copied_upto", end).lstrip("\n")
        if not new.strip():
            self.status.config(text="Nothing new since the last Copy new")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(new)
        self.text.mark_set("copied_upto", end)
        self.status.config(text=f"Copied {len(new.split())} new words to clipboard")

    def clear(self):
        self.text.delete("1.0", "end")
        self.text.mark_set("copied_upto", "1.0")
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

    # ---------- screen text ----------

    def pick_screen_area(self):
        self._pick_area("Drag over the text to read  ·  Esc to cancel",
                        lambda bbox: self.root.after(150, lambda: self._read_area(bbox)))

    def pick_scroll_area(self):
        self._pick_area("Drag over the area you will scroll  ·  Esc to cancel",
                        self._start_scroll_capture)

    def _pick_area(self, hint, on_pick):
        if self.reading_screen:
            return
        self.root.iconify()      # get out of the way of what the user wants to select
        self.root.after(250, lambda: self._show_area_picker(hint, on_pick))

    def _show_area_picker(self, hint, on_pick):
        left, top, width, height = virtual_screen(self.root)
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.geometry(f"{width}x{height}+{left}+{top}")
        win.attributes("-topmost", True)
        win.attributes("-alpha", 0.3)
        canvas = tk.Canvas(win, bg="black", cursor="crosshair", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_text(width // 2, 40, fill="white", font=("Segoe UI", 16, "bold"),
                           text=hint)
        drag = {}

        def press(e):
            drag["start"] = (e.x_root, e.y_root)
            drag["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff3b30", width=3)

        def move(e):
            if "rect" in drag:
                x0, y0 = drag["start"]
                canvas.coords(drag["rect"], x0 - left, y0 - top, e.x, e.y)

        def release(e):
            if "start" not in drag:
                return
            bbox = ocr.normalize_rect(*drag["start"], e.x_root, e.y_root)
            win.destroy()
            if bbox[2] - bbox[0] < 5 or bbox[3] - bbox[1] < 5:
                self._restore_window("Selection too small — try again")
                return
            on_pick(bbox)

        def cancel(_e=None):
            win.destroy()
            self._restore_window("Screen read cancelled")

        canvas.bind("<ButtonPress-1>", press)
        canvas.bind("<B1-Motion>", move)
        canvas.bind("<ButtonRelease-1>", release)
        win.bind("<Escape>", cancel)
        win.focus_force()

    def _restore_window(self, message):
        self.root.deiconify()
        self.root.lift()
        self.status.config(text=message)

    def _read_area(self, bbox):
        self.reading_screen = True
        self.screen_btn.config(state="disabled")
        try:
            image = ocr.capture(bbox)
        except Exception as e:
            self._screen_done(None, f"Couldn't capture the screen: {e}")
            return
        self._restore_window("Reading text from screen…")

        def work():
            try:
                text, error = ocr.recognize(image), None
            except ocr.OcrError as e:
                text, error = None, str(e)
            except Exception as e:   # never let a background failure kill the app
                text, error = None, f"Unexpected error: {e}"
            self.ui_q.put(lambda: self._screen_done(text, error))

        threading.Thread(target=work, daemon=True).start()

    def _screen_done(self, text, error):
        self.reading_screen = False
        self.screen_btn.config(state="normal")
        if error:
            self._restore_window("Screen read failed")
            messagebox.showinfo("Screen read failed", error, parent=self.root)
            return
        if not text:
            self.status.config(text="No text found in that area")
            return
        self.add_screen_text(text)
        self.status.config(text=f"Added {len(text.split())} words from the screen")

    # ---------- scroll capture ----------

    def _start_scroll_capture(self, bbox):
        self.reading_screen = True
        self._set_capture_buttons("disabled")
        self.scroll = {"bbox": bbox, "lines": [], "last_bytes": None, "busy": False,
                       "stopping": False, "frames": 0, "started": time.monotonic()}
        self.scroll["bar"] = self._capture_bar(
            bbox, "● Scroll capture — scroll or hold ↓", self.stop_scroll_capture)
        self.root.after(300, self._scroll_tick)   # let the picker overlay vanish first

    def _capture_bar(self, bbox, text, on_stop):
        """Small always-on-top bar outside the captured area, with a Stop button."""
        bar = tk.Toplevel(self.root)
        bar.overrideredirect(True)
        bar.attributes("-topmost", True)
        frame = tk.Frame(bar, bg="#c42b1c", padx=8, pady=4)
        frame.pack()
        label = tk.Label(frame, text=text, bg="#c42b1c", fg="white",
                         font=("Segoe UI", 10, "bold"))
        label.pack(side="left")
        ttk.Button(frame, text="Stop", command=on_stop).pack(
            side="left", padx=(8, 0))
        bar.update_idletasks()
        w, h = bar.winfo_reqwidth(), bar.winfo_reqheight()
        left, top, width, height = virtual_screen(self.root)
        x = min(max(bbox[0], left), left + width - w)
        y = bbox[1] - h - 6 if bbox[1] - h - 6 >= top else bbox[3] + 6
        if y + h > top + height:          # area fills the screen height: overlap a corner
            x, y = left + width - w - 10, top + 10
        bar.geometry(f"+{x}+{y}")
        exclude_from_capture(bar)
        bar.label = label
        return bar

    def _scroll_tick(self):
        sc = self.scroll
        if sc is None or sc["stopping"]:
            return
        if not sc["busy"]:
            if time.monotonic() - sc["started"] > SCROLL_MAX_SECONDS:
                self.stop_scroll_capture()
                return
            try:
                image = ocr.capture(sc["bbox"])
            except Exception as e:
                self._finish_scroll(f"Couldn't capture the screen: {e}")
                return
            data = image.tobytes() if hasattr(image, "tobytes") else image
            if data != sc["last_bytes"]:          # skip OCR while the page isn't moving
                sc["last_bytes"] = data
                sc["busy"] = True
                threading.Thread(target=self._scroll_ocr, args=(sc, image), daemon=True).start()
        self.root.after(SCROLL_INTERVAL_MS, self._scroll_tick)

    def _scroll_ocr(self, sc, image):
        try:
            lines, error = ocr.recognize(image).splitlines(), None
        except ocr.OcrError as e:
            lines, error = None, str(e)
        except Exception as e:   # never let a background failure kill the app
            lines, error = None, f"Unexpected error: {e}"
        self.ui_q.put(lambda: self._scroll_frame_done(sc, lines, error))

    def _scroll_frame_done(self, sc, lines, error):
        sc["busy"] = False
        if self.scroll is not sc:
            return
        if error:
            self._finish_scroll(error)
            return
        sc["lines"] = ocr.merge_lines(sc["lines"], lines)
        sc["frames"] += 1
        try:
            sc["bar"].label.config(
                text=f"● Scroll capture — {len(sc['lines'])} lines  ·  scroll or hold ↓")
        except tk.TclError:
            pass
        if sc["stopping"]:
            self._finish_scroll()

    def stop_scroll_capture(self):
        sc = self.scroll
        if sc is None or sc["stopping"]:
            return
        sc["stopping"] = True
        if not sc["busy"]:                 # otherwise the frame in flight finishes it
            self._finish_scroll()

    def _finish_scroll(self, error=None):
        sc, self.scroll = self.scroll, None
        if sc is None:
            return
        try:
            sc["bar"].destroy()
        except tk.TclError:
            pass
        self.reading_screen = False
        self._set_capture_buttons("normal")
        self._restore_window("Scroll capture finished")
        if error:
            messagebox.showinfo("Scroll capture stopped", error, parent=self.root)
        text = "\n".join(sc["lines"])
        if text.strip():
            self.add_screen_text(text)
            self.status.config(text=f"Added {len(sc['lines'])} lines from scroll capture")
        elif not error:
            self.status.config(text="No text found while scrolling")

    def _set_capture_buttons(self, state):
        for btn in (self.screen_btn, self.scroll_btn, self.record_btn):
            btn.config(state=state)

    # ---------- screen recording ----------

    def pick_record_area(self):
        if self.reading_screen:
            return
        default = recorder.new_recording_path()
        try:
            default.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save recording as", defaultextension=".mp4",
            initialdir=str(default.parent), initialfile=default.name,
            filetypes=[("MP4 video", "*.mp4")])
        if not path:
            return
        self._pick_area("Drag over the area to record  ·  Esc to cancel",
                        lambda bbox: self._start_recording(bbox, path))

    def _start_recording(self, bbox, path):
        sound, note = None, ""
        if self.record_sound.get():
            try:
                sound = recorder.SpeakerAudio()
            except Exception as e:
                note = f" (no sound: {e})"
        try:
            rec = recorder.ScreenRecorder(bbox, path, audio=sound)
            rec.start()
        except Exception as e:
            if sound is not None:
                sound.close()
            self._restore_window("Recording failed")
            messagebox.showinfo("Recording failed", f"Couldn't start recording: {e}",
                                parent=self.root)
            return
        self.reading_screen = True
        self._set_capture_buttons("disabled")
        self.recording = {"rec": rec, "note": note,
                          "bar": self._capture_bar(bbox, "● Recording 0:00",
                                                   self.stop_recording)}
        self.root.after(500, self._record_tick)

    def _record_tick(self):
        rc = self.recording
        if rc is None:
            return
        if not rc["rec"].running:          # stopped by itself: error or time limit
            self.stop_recording()
            return
        secs = int(rc["rec"].seconds)
        try:
            rc["bar"].label.config(text=f"● Recording {secs // 60}:{secs % 60:02d}"
                                        f"{'' if rc['rec'].audio else ' (no sound)'}")
        except tk.TclError:
            pass
        self.root.after(500, self._record_tick)

    def stop_recording(self):
        rc, self.recording = self.recording, None
        if rc is None:
            return
        try:
            rc["bar"].destroy()
        except tk.TclError:
            pass
        rec = rc["rec"]
        path = rec.stop()
        self.reading_screen = False
        self._set_capture_buttons("normal")
        secs = int(rec.seconds)
        if rec.frames:
            self._restore_window(f"Saved {secs // 60}:{secs % 60:02d} recording to {path}"
                                 + rc["note"])
        else:
            self._restore_window("Recording failed")
        if rec.error:
            messagebox.showinfo("Recording stopped", rec.error, parent=self.root)

    def add_screen_text(self, text):
        self.last_label = None   # every capture starts its own "Screen:" line
        self.add_final("Screen", text)
        if self.autoscroll.get():
            self.text.see("end")

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
        self.stop_recording()
        self.transcriber.stop()
        self.root.after(300, self.root.destroy)
