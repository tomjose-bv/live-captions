"""Tk-level tests. They need a display (fine on Windows desktops/CI) but no audio hardware."""

import pytest

tk = pytest.importorskip("tkinter")

from livecaptions import state, summarize, ui  # noqa: E402


@pytest.fixture
def app(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    a = ui.App(root, state_path=str(tmp_path / "state.json"), show_consent=False)
    yield a
    root.destroy()


def pump(app):
    app.root.update()
    while not app.ui_q.empty():
        app.ui_q.get_nowait()()


def test_partial_then_final_replaces_grey_text(app):
    app.add_final("Them", "hello there")
    app.show_partial("Them", "how are")
    app.show_partial("Them", "how are you")
    assert app.final_text().endswith("hello there")
    assert app.text.get("1.0", "end-1c").endswith("how are you")
    app.add_final("Them", "how are you doing")
    assert not app.partial_active
    assert app.text.get("1.0", "end-1c").endswith("hello there how are you doing")


def test_banner_turns_live(app):
    app.set_controls_enabled(False)
    assert app.banner.cget("text") == ui.BANNER_LIVE[0]
    app.set_controls_enabled(True)
    assert app.banner.cget("text") == ui.BANNER_IDLE[0]


def test_consent_notice_acknowledgement_is_saved(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    path = str(tmp_path / "s.json")
    try:
        a = ui.App(root, state_path=path, show_consent=False)
        a.show_consent_notice()
        dialogs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        assert dialogs
        button = [w for w in dialogs[0].winfo_children()[0].winfo_children()
                  if w.winfo_class() == "TButton"][0]
        button.invoke()
        assert not state.needs_consent_notice(state.load_state(path))
    finally:
        root.destroy()


def test_summarize_unreachable_shows_message(app, monkeypatch):
    shown = {}
    monkeypatch.setattr(ui.messagebox, "showinfo",
                        lambda title, msg, parent=None: shown.update(title=title, msg=msg))

    def fail(text, settings):
        raise summarize.SummaryError("Couldn't reach a local LLM")
    monkeypatch.setattr(ui.summarize, "summarize", fail)
    app.add_final("You", "let's ship on friday")
    app.summarize()
    for _ in range(50):
        pump(app)
        if shown:
            break
        app.root.after(20)
    assert shown["title"] == "Summary unavailable"
    assert app.summary_btn.instate(["!disabled"])


def test_summarize_success_stores_summary(app, monkeypatch):
    monkeypatch.setattr(ui.summarize, "summarize", lambda text, settings: "## Summary\n- ship")
    app.add_final("You", "let's ship on friday")
    app.summarize()
    for _ in range(50):
        pump(app)
        if app.last_summary:
            break
        app.root.after(20)
    assert app.last_summary == "## Summary\n- ship"


def test_export_writes_markdown(app, monkeypatch, tmp_path):
    out = tmp_path / "t.md"
    monkeypatch.setattr(ui.filedialog, "asksaveasfilename", lambda **kw: str(out))
    app.add_final("You", "hello")
    app.show_partial("Them", "not final")
    app.export()
    content = out.read_text(encoding="utf-8")
    assert content.startswith("# Transcript")
    assert "hello" in content and "not final" not in content


def _visible_inside(widget, root):
    """True if the widget is mapped with a non-trivial area fully inside the root window."""
    x, y = widget.winfo_rootx() - root.winfo_rootx(), widget.winfo_rooty() - root.winfo_rooty()
    return (widget.winfo_ismapped() and widget.winfo_height() >= widget.winfo_reqheight()
            and x >= 0 and y >= 0
            and x + widget.winfo_width() <= root.winfo_width()
            and y + widget.winfo_height() <= root.winfo_height())


@pytest.mark.parametrize("size", ["default", "minimum"])
def test_all_controls_visible(tmp_path, size):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    try:
        a = ui.App(root, state_path=str(tmp_path / "s.json"), show_consent=False)
        if size == "minimum":
            w, h = root.minsize()
            root.geometry(f"{w}x{h}")
        root.update()
        controls = a.source_checks + [a.preview_check, a.status, a.start_btn, a.summary_btn]
        for c in controls:
            assert _visible_inside(c, root), c.cget("text")
    finally:
        root.destroy()


def test_window_has_minimum_size(tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    try:
        ui.App(root, state_path=str(tmp_path / "s.json"), show_consent=False)
        w, h = root.minsize()
        assert w > 1 and h > 1
    finally:
        root.destroy()


def test_copy_new_copies_only_text_since_last_copy_new(app):
    app.add_final("Them", "first part")
    app.copy_new()
    assert app.root.clipboard_get() == "Them: first part"
    app.add_final("Them", "second part")
    app.add_final("You", "my reply")
    app.copy_new()
    assert app.root.clipboard_get() == " second part\nYou: my reply"
    app.copy_new()
    assert app.root.clipboard_get() == " second part\nYou: my reply"   # unchanged
    assert app.status.cget("text") == "Nothing new since the last Copy new"


def test_copy_new_skips_grey_partial_and_is_independent_of_copy_all(app):
    app.add_final("Them", "settled")
    app.show_partial("Them", "still talking")
    app.copy_new()
    assert app.root.clipboard_get() == "Them: settled"
    app.copy_all()                      # must not move the Copy new position
    app.add_final("Them", "still talking now")
    app.copy_new()
    assert app.root.clipboard_get() == " still talking now"


def test_clear_resets_copy_new(app):
    app.add_final("Them", "old")
    app.copy_new()
    app.clear()
    app.add_final("Them", "fresh")
    app.copy_new()
    assert app.root.clipboard_get() == "Them: fresh"


def test_screen_text_gets_its_own_labelled_lines(app):
    app.add_final("Them", "hello")
    app.add_screen_text("Slide title\nBullet one")
    app.add_screen_text("Next slide")
    app.add_final("Them", "moving on")
    assert app.final_text() == ("Them: hello\nScreen: Slide title\nBullet one\n"
                                "Screen: Next slide\nThem: moving on")


def test_read_area_adds_text_in_background(app, monkeypatch):
    monkeypatch.setattr(ui.ocr, "capture", lambda bbox: ("img", bbox))
    monkeypatch.setattr(ui.ocr, "recognize", lambda image: "Agenda item")
    app._read_area((0, 0, 100, 40))
    for _ in range(50):
        pump(app)
        if not app.reading_screen:
            break
        app.root.after(20)
    assert app.final_text() == "Screen: Agenda item"
    assert str(app.screen_btn.cget("state")) == "normal"


def test_read_area_reports_ocr_errors(app, monkeypatch):
    shown = []
    monkeypatch.setattr(ui.ocr, "capture", lambda bbox: "img")

    def fail(image):
        raise ui.ocr.OcrError("no language")

    monkeypatch.setattr(ui.ocr, "recognize", fail)
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: shown.append(a))
    app._read_area((0, 0, 100, 40))
    for _ in range(50):
        pump(app)
        if not app.reading_screen:
            break
        app.root.after(20)
    assert shown and shown[0][1] == "no language"
    assert app.final_text() == ""


def test_scroll_capture_stitches_frames_until_stopped(app, monkeypatch):
    page = [f"Paragraph {i} of a long scrolling document" for i in range(1, 21)]
    frames = iter([page[0:8], page[0:8], page[5:13], page[11:20]])
    shots = []

    def capture(bbox):
        shots.append(bbox)
        return f"frame{len(shots)}"

    monkeypatch.setattr(ui, "exclude_from_capture", lambda win: None)
    monkeypatch.setattr(ui, "SCROLL_INTERVAL_MS", 10)
    monkeypatch.setattr(ui.ocr, "capture", capture)
    monkeypatch.setattr(ui.ocr, "recognize", lambda image: "\n".join(next(frames)))
    app._start_scroll_capture((0, 0, 400, 300))
    for _ in range(400):
        pump(app)
        if len(shots) >= 4 and not app.scroll["busy"]:
            break
        app.root.after(10)
    app.stop_scroll_capture()
    for _ in range(100):
        pump(app)
        if app.scroll is None:
            break
        app.root.after(10)
    assert app.final_text() == "Screen: " + "\n".join(page)
    assert not app.reading_screen
    assert str(app.screen_btn.cget("state")) == "normal"


class FakeRecorder:
    def __init__(self, bbox, path, audio=None):
        self.bbox, self.path, self.audio = bbox, path, audio
        self.running, self.seconds, self.error, self.frames = False, 0.0, None, 0

    def start(self):
        self.running = True

    def stop(self):
        self.running = False
        self.seconds, self.frames = 75.4, 1131
        return self.path


def test_record_area_runs_until_stopped(app, monkeypatch):
    made = []
    monkeypatch.setattr(ui, "exclude_from_capture", lambda win: None)
    monkeypatch.setattr(ui.recorder, "ScreenRecorder",
                        lambda *a, **kw: made.append(FakeRecorder(*a, **kw)) or made[-1])
    app.record_sound.set("No sound")
    app._start_recording((0, 0, 400, 300), "C:/tmp/clip.mp4")
    assert app.reading_screen and made[0].running and made[0].audio is None
    assert str(app.screen_btn.cget("state")) == "disabled"
    app.pick_screen_area()             # ignored while recording
    app.stop_recording()
    assert not made[0].running and app.recording is None and not app.reading_screen
    assert str(app.screen_btn.cget("state")) == "normal"
    assert app.status.cget("text") == "Saved 1:15 recording to C:/tmp/clip.mp4"


def test_record_area_without_sound_device_still_records(app, monkeypatch):
    def no_sound(mic=False):
        raise RuntimeError("No loopback device found")

    monkeypatch.setattr(ui, "exclude_from_capture", lambda win: None)
    monkeypatch.setattr(ui.recorder, "SpeakerAudio", no_sound)
    monkeypatch.setattr(ui.recorder, "ScreenRecorder", FakeRecorder)
    app.record_sound.set("PC sound")
    app._start_recording((0, 0, 400, 300), "C:/tmp/clip.mp4")
    app.stop_recording()
    assert app.status.cget("text").endswith("(no sound: No loopback device found)")


def test_recording_that_stops_by_itself_is_finished(app, monkeypatch):
    monkeypatch.setattr(ui, "exclude_from_capture", lambda win: None)
    monkeypatch.setattr(ui.recorder, "ScreenRecorder", FakeRecorder)
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **kw: None)
    app.record_sound.set("No sound")
    app._start_recording((0, 0, 400, 300), "C:/tmp/clip.mp4")
    app.recording["rec"].running = False
    app.recording["rec"].error = "Recording stopped: screen locked"
    app._record_tick()
    assert app.recording is None and not app.reading_screen
    assert app.status.cget("text").startswith("Saved 1:15 recording")


def test_snapshots_save_only_when_the_area_changes(app, monkeypatch, tmp_path):
    Image = pytest.importorskip("PIL.Image")
    screens = iter(["white", "white", "white", "navy", "navy", "white"])
    shots = []

    def capture(bbox):
        colour = next(screens, "white")
        shots.append(colour)
        return Image.new("RGB", (320, 180), colour)

    monkeypatch.setattr(ui, "exclude_from_capture", lambda win: None)
    monkeypatch.setattr(ui, "SNAPSHOT_INTERVAL_MS", 5)
    monkeypatch.setattr(ui.ocr, "capture", capture)
    monkeypatch.setattr(ui.ocr, "recognize", lambda image: "Slide text")
    app._start_snapshots((0, 0, 320, 180), tmp_path / "snaps")
    for _ in range(600):
        pump(app)
        if len(shots) >= 6 and not app.snapping["busy"]:
            break
        app.root.after(5)
    app.stop_snapshots()
    for _ in range(100):
        pump(app)
        if app.snapping is None:
            break
        app.root.after(5)
    assert sorted(p.name for p in (tmp_path / "snaps").glob("*.png")) == [
        "snapshot-001.png", "snapshot-002.png", "snapshot-003.png"]
    text = app.final_text()
    assert text.count("Screen: [") == 3 and "snapshot-003.png]\nSlide text" in text
    assert not app.reading_screen
    assert str(app.screen_btn.cget("state")) == "normal"
    assert app.status.cget("text").startswith("Saved 3 snapshots to")


def test_mic_choice_opens_mixed_sound(app, monkeypatch):
    opened = []
    monkeypatch.setattr(ui, "exclude_from_capture", lambda win: None)
    monkeypatch.setattr(ui.recorder, "SpeakerAudio", lambda mic=False: opened.append(mic) or None)
    monkeypatch.setattr(ui.recorder, "ScreenRecorder", FakeRecorder)
    app.record_sound.set("PC sound + mic")
    app._start_recording((0, 0, 400, 300), "C:/tmp/clip.mp4")
    app.stop_recording()
    assert opened == [True]
