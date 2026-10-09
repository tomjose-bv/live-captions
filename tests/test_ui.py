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
