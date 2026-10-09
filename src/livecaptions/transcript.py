"""Pure helpers for appending caption text to the transcript."""


def append_text(existing, last_label, label, text):
    """Return (string_to_insert, new_last_label) for appending ``text`` from ``label``.

    A change of source starts a new labelled line ("You: ..." / "Them: ..."); otherwise
    text continues the current line with a single separating space.
    """
    if label != last_label:
        prefix = ("\n" if existing and not existing.endswith("\n") else "") + f"{label}: "
    else:
        prefix = "" if not existing or existing[-1] in " \n" else " "
    return prefix + text, label
