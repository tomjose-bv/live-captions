r"""Record README GIFs of Scroll capture and Snapshots, using synthetic demo windows only.

A plain backdrop window covers the capture region so other windows stay hidden. Pop-up
menus can still appear above it, so don't use the PC while it records, and check the
frames before publishing. Run from the repo root:

    .venv\Scripts\python scripts\make_demo_gifs.py scroll docs\media\scroll-capture.gif
    .venv\Scripts\python scripts\make_demo_gifs.py snap docs\media\snapshots.gif
"""

import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageGrab

from livecaptions import ui
from livecaptions.app import enable_dpi_awareness

MODE, OUT = sys.argv[1], Path(sys.argv[2])
X0, Y0, W, H = 0, 20, 1920, 960
FPS = 6
GIF_WIDTH = 1000

ARTICLE = [
    "Getting started with local speech recognition",
    "",
    "Speech recognition used to need a server farm. Today a laptop can transcribe",
    "speech faster than real time, with no internet connection at all.",
    "",
]
for i in range(1, 16):
    ARTICLE += [f"Step {i}. " + [
        "Pick a model that fits your hardware and your accuracy needs.",
        "Measure word error rate on a public test set before trusting it.",
        "Check the real-time factor: how long it takes per second of audio.",
        "Keep the audio on the device and process it in memory.",
        "Tell people before you caption or record them, and respect a no.",
    ][i % 5], "   Short notes for this step, written for the demo only.", ""]
ARTICLE.append("End of the article.")

SLIDES = [
    ("Quarterly roadmap", ["Ship offline captions", "Add screen text reading", "Publish benchmarks"]),
    ("Benchmark method", ["Public LibriSpeech subset", "Word error rate per model", "Same laptop, same date"]),
    ("Next steps", ["Microphone in recordings", "Snapshots timeline", "Feedback from users"]),
]

frames = []
recording = threading.Event()


def grab_loop():
    while recording.is_set():
        t = time.monotonic()
        frames.append(ImageGrab.grab((X0, Y0, X0 + W, Y0 + H), all_screens=True))
        time.sleep(max(0, 1 / FPS - (time.monotonic() - t)))


def save_gif():
    h = round(H * GIF_WIDTH / W)
    small = [f.convert("RGB").resize((GIF_WIDTH, h), Image.LANCZOS) for f in frames]
    pal = [f.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
           for f in small]
    durations = [int(1000 / FPS)] * len(pal)
    durations[-1] = 2500
    pal[0].save(OUT, save_all=True, append_images=pal[1:], duration=durations, loop=0,
                optimize=True, disposal=1)
    print(f"{OUT}: {len(pal)} frames, {OUT.stat().st_size // 1024} KB")


enable_dpi_awareness()
ui.exclude_from_capture = lambda win: None   # show the red Stop bar in the GIF
root = tk.Tk()
app = ui.App(root, state_path=str(Path(tempfile.gettempdir()) / "lc-demo-state.json"),
             show_consent=False)

backdrop = tk.Toplevel(root)
backdrop.overrideredirect(True)
backdrop.geometry(f"{W}x{H}+{X0}+{Y0}")
backdrop.configure(bg="#dfe3e8")
backdrop.attributes("-topmost", True)

doc = tk.Toplevel(root)
doc.title("Article")
doc_w = 620
doc.geometry(f"{doc_w}x{H - 140}+{X0 + 20}+{Y0 + 100}")
doc.attributes("-topmost", True)

root.geometry(f"{W - doc_w - 50}x{H - 140}+{X0 + doc_w + 35}+{Y0 + 100}")
root.attributes("-topmost", True)

if MODE == "scroll":
    body = tk.Text(doc, font=("Segoe UI", 11), wrap="word", bd=0, padx=16, pady=12)
    body.insert("1.0", "\n".join(ARTICLE))
    body.config(state="disabled")
    body.pack(fill="both", expand=True)
else:
    body = tk.Canvas(doc, bg="white", highlightthickness=0)
    body.pack(fill="both", expand=True)

    def show_slide(n):
        title, bullets = SLIDES[n]
        body.delete("all")
        body.create_rectangle(0, 0, 2000, 110, fill="#1f4e79", width=0)
        body.create_text(30, 55, anchor="w", text=title, fill="white",
                         font=("Segoe UI", 26, "bold"))
        for i, b in enumerate(bullets):
            body.create_text(50, 170 + i * 70, anchor="w", text="•  " + b,
                             font=("Segoe UI", 20))
        body.create_text(30, body.winfo_height() - 30, anchor="w",
                         text=f"Slide {n + 1} of {len(SLIDES)}", fill="#666",
                         font=("Segoe UI", 12))
    doc.update()
    show_slide(0)

for w in (backdrop, doc, root):
    w.lift()
root.update()


def area():
    body.update_idletasks()
    x, y = body.winfo_rootx(), body.winfo_rooty()
    return (x, y, x + body.winfo_width(), y + body.winfo_height())


def finish():
    recording.clear()
    time.sleep(0.3)
    save_gif()
    root.destroy()


def start():
    root.geometry(f"{W - doc_w - 50}x{H - 140}+{X0 + doc_w + 35}+{Y0 + 100}")
    root.update()
    recording.set()
    threading.Thread(target=grab_loop, daemon=True).start()
    if MODE == "scroll":
        root.after(1200, lambda: app._start_scroll_capture(area()))
        steps = {"n": 0}

        def scroll():
            if steps["n"] < 60:
                body.yview_scroll(1, "units")
                steps["n"] += 1
                root.after(110, scroll)
            else:
                root.after(800, app.stop_scroll_capture)
                root.after(3500, finish)
        root.after(2500, scroll)
    else:
        root.after(1000, lambda: app._start_snapshots(area(), Path(tempfile.mkdtemp()) / "snaps"))
        root.after(4500, lambda: show_slide(1))
        root.after(8000, lambda: show_slide(2))
        root.after(11000, app.stop_snapshots)
        root.after(13500, finish)


root.after(800, start)
root.mainloop()
