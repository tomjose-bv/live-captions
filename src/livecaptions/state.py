"""Tiny persisted app state (currently just the consent-notice acknowledgement).

Stored in %APPDATA%\\LiveCaptions\\state.json (or ~/.livecaptions on other OSes).
No transcript text is ever written here.
"""

import json
import os

CONSENT_VERSION = 1   # bump to re-show the notice if its wording changes materially

CONSENT_TEXT = (
    "Live Captions transcribes audio on this computer: what plays through your "
    "speakers and, if enabled, your microphone.\n\n"
    "Before captioning a call or meeting, tell the other people and get their "
    "consent. In many places recording or transcribing a conversation without "
    "everyone's permission is illegal, and it is always a matter of trust.\n\n"
    "Everything stays on this PC. Nothing is uploaded and nothing is saved unless "
    "you copy or export it."
)


def state_path():
    base = os.environ.get("APPDATA")
    folder = os.path.join(base, "LiveCaptions") if base else os.path.expanduser("~/.livecaptions")
    return os.path.join(folder, "state.json")


def load_state(path=None):
    path = path or state_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state, path=None):
    path = path or state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def needs_consent_notice(state):
    return state.get("consent_notice_version", 0) < CONSENT_VERSION


def acknowledge_consent(state):
    state = dict(state)
    state["consent_notice_version"] = CONSENT_VERSION
    return state
