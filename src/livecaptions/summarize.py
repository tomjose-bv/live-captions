"""Optional summaries and action items via a local OpenAI-compatible endpoint.

Defaults target Ollama (http://localhost:11434/v1). Nothing here is required for
captioning: if no server is running, the caller gets a SummaryError with a
plain-language explanation of how to enable the feature.
"""

import ipaddress
import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "llama3.2:3b"
MAX_TRANSCRIPT_CHARS = 24000   # keep prompts within small local models' context windows

SYSTEM_PROMPT = (
    "You summarize meeting and call transcripts. The transcript comes from automatic "
    "speech recognition and may contain errors. Lines may be labelled 'You:' (the "
    "person running the app) or 'Them:' (audio from the computer's speakers). "
    "Be concise and factual; do not invent details that are not in the transcript."
)
USER_TEMPLATE = (
    "Transcript:\n\"\"\"\n{transcript}\n\"\"\"\n\n"
    "Write, in Markdown:\n"
    "## Summary\n3-6 bullet points.\n"
    "## Action items\nBullets of the form '- [owner if stated] task (due date if stated)'. "
    "Write 'None identified.' if there are none.\n"
    "## Open questions\nOnly if any were raised; otherwise omit this section."
)


class SummaryError(Exception):
    """A user-presentable failure (endpoint down, model missing, bad response...)."""


@dataclass
class LLMSettings:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = ""
    timeout: float = 180.0

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        return cls(
            base_url=(env.get("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            model=env.get("LLM_MODEL") or DEFAULT_MODEL,
            api_key=env.get("LLM_API_KEY", ""),
            timeout=float(env.get("LLM_TIMEOUT") or 180),
        )


def load_dotenv(path, env=None):
    """Minimal .env reader: KEY=VALUE lines, # comments, optional quotes.

    Existing environment variables win, so a real env var can override the file.
    Returns the dict of values read from the file.
    """
    env = os.environ if env is None else env
    values = {}
    if not os.path.isfile(path):
        return values
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().removeprefix("export ").strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()
            values[key] = value
            env.setdefault(key, value)
    return values


def is_local_url(url):
    """True if the endpoint host is this machine (loopback), i.e. text never leaves the PC."""
    host = urllib.parse.urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def truncate_transcript(text, limit=MAX_TRANSCRIPT_CHARS):
    """Keep the most recent ``limit`` characters; returns (text, was_truncated)."""
    text = text.strip()
    if len(text) <= limit:
        return text, False
    cut = text[-limit:]
    nl = cut.find("\n")
    if 0 <= nl < 200:
        cut = cut[nl + 1:]
    return cut, True


def build_messages(transcript):
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_TEMPLATE.format(transcript=transcript)}]


def summarize(transcript, settings=None, opener=urllib.request.urlopen):
    """Return a Markdown summary of ``transcript``. Raises SummaryError on any failure."""
    settings = settings or LLMSettings.from_env()
    text, truncated = truncate_transcript(transcript)
    if not text:
        raise SummaryError("The transcript is empty - nothing to summarize yet.")

    url = settings.base_url + "/chat/completions"
    body = json.dumps({"model": settings.model, "messages": build_messages(text),
                       "temperature": 0.2, "stream": False}).encode()
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with opener(req, timeout=settings.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        if e.code == 404:
            raise SummaryError(
                f"The server at {settings.base_url} doesn't know model '{settings.model}'.\n"
                f"With Ollama, run:  ollama pull {settings.model}\n"
                f"or set LLM_MODEL in your .env file.") from None
        raise SummaryError(f"The LLM server returned HTTP {e.code}. {detail}".strip()) from None
    except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError) as e:
        reason = getattr(e, "reason", e)
        raise SummaryError(
            f"Couldn't reach a local LLM at {settings.base_url} ({reason}).\n\n"
            "Summaries are optional. To enable them, install Ollama (https://ollama.com), "
            f"run  ollama pull {settings.model}  and keep Ollama running - or point "
            "LLM_BASE_URL / LLM_MODEL in .env at any OpenAI-compatible local server.") from None
    except json.JSONDecodeError:
        raise SummaryError("The LLM server sent a response that isn't JSON.") from None

    try:
        content = payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise SummaryError("Unexpected response format from the LLM server.") from None
    if truncated:
        content = ("_Note: the transcript was long, so only its most recent part was "
                   "summarized._\n\n" + content)
    return content
