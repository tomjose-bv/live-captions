import datetime as dt
import io
import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from livecaptions import export, state, summarize
from livecaptions.summarize import LLMSettings, SummaryError


# ---------- settings / .env ----------

def test_settings_defaults_to_ollama():
    s = LLMSettings.from_env({})
    assert s.base_url == "http://localhost:11434/v1"
    assert s.model == summarize.DEFAULT_MODEL
    assert s.api_key == ""


def test_settings_from_env_strips_trailing_slash():
    s = LLMSettings.from_env({"LLM_BASE_URL": "http://127.0.0.1:8080/v1/", "LLM_MODEL": "qwen"})
    assert s.base_url == "http://127.0.0.1:8080/v1" and s.model == "qwen"


def test_load_dotenv_parses_and_does_not_override(tmp_path):
    p = tmp_path / ".env"
    p.write_text('# comment\nLLM_MODEL="phi3"\nexport LLM_TIMEOUT=30 # secs\nBAD LINE\n'
                 "LLM_BASE_URL=http://x/v1\n")
    env = {"LLM_BASE_URL": "http://keep/v1"}
    values = summarize.load_dotenv(str(p), env)
    assert values == {"LLM_MODEL": "phi3", "LLM_TIMEOUT": "30", "LLM_BASE_URL": "http://x/v1"}
    assert env["LLM_BASE_URL"] == "http://keep/v1"
    assert env["LLM_MODEL"] == "phi3"


def test_load_dotenv_missing_file_is_fine(tmp_path):
    assert summarize.load_dotenv(str(tmp_path / "nope"), {}) == {}


@pytest.mark.parametrize("url,local", [
    ("http://localhost:11434/v1", True),
    ("http://127.0.0.1:8080/v1", True),
    ("http://[::1]:8080/v1", True),
    ("https://api.example.com/v1", False),
    ("http://192.168.1.20:11434/v1", False),
])
def test_is_local_url(url, local):
    assert summarize.is_local_url(url) is local


def test_truncate_keeps_recent_text():
    text = "\n".join(f"line {i}" for i in range(5000))
    out, cut = summarize.truncate_transcript(text, limit=1000)
    assert cut and len(out) <= 1000
    assert out.endswith("line 4999")
    assert out.startswith("line ")   # cut at a line boundary


# ---------- summarize() with fake transports ----------

class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def ok_opener(captured):
    def opener(req, timeout):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        captured["headers"] = dict(req.header_items())
        return FakeResp(json.dumps(
            {"choices": [{"message": {"content": " ## Summary\n- done "}}]}).encode())
    return opener


def test_summarize_success_builds_openai_request():
    cap = {}
    s = LLMSettings(base_url="http://localhost:1/v1", model="m", api_key="k")
    out = summarize.summarize("You: hello\nThem: hi", s, opener=ok_opener(cap))
    assert out == "## Summary\n- done"
    assert cap["url"] == "http://localhost:1/v1/chat/completions"
    assert cap["body"]["model"] == "m"
    assert "You: hello" in cap["body"]["messages"][1]["content"]
    assert cap["headers"]["Authorization"] == "Bearer k"


def test_summarize_unreachable_gives_friendly_message():
    def opener(req, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(10061, "refused"))
    with pytest.raises(SummaryError, match="Couldn't reach a local LLM"):
        summarize.summarize("text", LLMSettings(), opener=opener)


def test_summarize_missing_model_suggests_pull():
    def opener(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"model not found"))
    with pytest.raises(SummaryError, match="ollama pull"):
        summarize.summarize("text", LLMSettings(model="x"), opener=opener)


def test_summarize_bad_payload():
    with pytest.raises(SummaryError, match="Unexpected"):
        summarize.summarize("text", LLMSettings(),
                            opener=lambda r, timeout: FakeResp(b'{"nope": 1}'))


def test_summarize_empty_transcript():
    with pytest.raises(SummaryError, match="empty"):
        summarize.summarize("   ", LLMSettings(), opener=ok_opener({}))


def test_summarize_against_real_local_http_server():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = json.dumps({"choices": [{"message": {
                "content": f"model={body['model']}"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = LLMSettings(base_url=f"http://127.0.0.1:{srv.server_port}/v1", model="tiny", timeout=5)
        assert summarize.summarize("hello", s) == "model=tiny"
    finally:
        srv.shutdown()


# ---------- export ----------

NOW = dt.datetime(2026, 10, 9, 14, 30)


def test_default_filename():
    assert export.default_filename("md", NOW) == "transcript-20261009-1430.md"


def test_render_txt_is_plain_text():
    assert export.render("You: hi\nThem: hello\n", "txt", NOW) == "You: hi\nThem: hello\n"


def test_render_md_bolds_labels_and_adds_header():
    out = export.render("You: hi\nThem: hello", "md", NOW, model="Moonshine base",
                        summary="## Summary\n- x")
    assert out.startswith("# Transcript\n\n_Exported 2026-10-09 14:30 · transcribed locally with "
                          "Moonshine base_")
    assert "**You:** hi" in out and "**Them:** hello" in out
    assert out.rstrip().endswith("- x")


def test_render_rejects_unknown_format():
    with pytest.raises(ValueError):
        export.render("x", "docx", NOW)


# ---------- consent state ----------

def test_consent_first_run_then_acknowledged(tmp_path):
    p = str(tmp_path / "sub" / "state.json")
    st = state.load_state(p)
    assert st == {} and state.needs_consent_notice(st)
    state.save_state(state.acknowledge_consent(st), p)
    assert not state.needs_consent_notice(state.load_state(p))


def test_corrupt_state_file_is_treated_as_first_run(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    assert state.needs_consent_notice(state.load_state(str(p)))
