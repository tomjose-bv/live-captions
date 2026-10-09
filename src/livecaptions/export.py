"""Render the transcript for export. Only ever written when the user clicks Export."""

import datetime as dt
import re

_LABEL = re.compile(r"^(You|Them|Speakers|Mic):\s?|^\[(You|Them|Speakers|Mic)\]\s?")


def default_filename(fmt, now=None):
    now = now or dt.datetime.now()
    return f"transcript-{now:%Y%m%d-%H%M}.{fmt}"


def render(text, fmt, now=None, model=None, summary=None):
    """Return file contents for ``fmt`` ("txt" or "md")."""
    now = now or dt.datetime.now()
    text = text.strip()
    if fmt == "txt":
        out = text + "\n"
        if summary:
            out += "\n---- Summary ----\n" + summary.strip() + "\n"
        return out
    if fmt != "md":
        raise ValueError(f"Unsupported export format: {fmt}")
    meta = f"Exported {now:%Y-%m-%d %H:%M}"
    if model:
        meta += f" · transcribed locally with {model}"
    lines = ["# Transcript", "", f"_{meta}_", ""]
    for line in text.splitlines():
        m = _LABEL.match(line)
        if m:
            label = m.group(1) or m.group(2)
            line = f"**{label}:** {line[m.end():]}"
        lines.append(line)
        lines.append("")
    if summary:
        lines += ["---", "", summary.strip(), ""]
    return "\n".join(lines).rstrip() + "\n"
