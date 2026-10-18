"""Smart snapshots: save a screen area as a picture each time its content changes.

Every saved picture also goes into ``snapshots.md`` in the same folder, with its time and
the text read from it, so the folder reads as a timeline of what was on screen.
"""

import datetime
from pathlib import Path

CHECK_SIZE = (160, 90)   # compare small greyscale copies: fast, and ignores tiny noise
PIXEL_DELTA = 24         # a pixel counts as changed if its grey level moves this much
CHANGED_SHARE = 0.02     # save when at least this share of the area has changed


def default_folder(now=None):
    now = now or datetime.datetime.now()
    return Path.home() / "Pictures" / "Live Captions" / f"snapshots-{now:%Y%m%d-%H%M%S}"


def thumbnail(image):
    return image.convert("L").resize(CHECK_SIZE)


def changed_share(a, b):
    """Share (0-1) of pixels that differ noticeably between two thumbnails."""
    from PIL import ImageChops

    diff = ImageChops.difference(a, b).point(lambda v: 255 if v >= PIXEL_DELTA else 0)
    return diff.histogram()[255] / (diff.width * diff.height)


def has_changed(previous, current, share=CHANGED_SHARE):
    return previous is None or changed_share(previous, current) >= share


class SnapshotFolder:
    """Writes numbered PNGs plus a ``snapshots.md`` timeline into ``folder``."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.count = 0
        self.index = self.folder / "snapshots.md"

    def save(self, image, text, when=None):
        when = when or datetime.datetime.now()
        if self.count == 0:
            self.folder.mkdir(parents=True, exist_ok=True)
            self.index.write_text(f"# Snapshots\n\n_Started {when:%Y-%m-%d %H:%M:%S}_\n",
                                  encoding="utf-8")
        self.count += 1
        name = f"snapshot-{self.count:03d}.png"
        image.save(self.folder / name)
        entry = [f"\n## {when:%H:%M:%S}\n", f"![Snapshot {self.count}]({name})\n"]
        if text.strip():
            entry.append("\n" + "\n".join(f"> {line}" for line in text.splitlines()) + "\n")
        with self.index.open("a", encoding="utf-8") as f:
            f.write("".join(entry))
        return name
