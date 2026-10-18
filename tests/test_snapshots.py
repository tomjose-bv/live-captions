"""Smart snapshots: change detection and the snapshot folder/timeline."""

import datetime

import pytest

Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")

from livecaptions import snapshots  # noqa: E402


def slide(title, cursor=None):
    image = Image.new("RGB", (800, 450), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 760, 120), fill="#1f4e79")
    draw.text((60, 70), title, fill="white")
    for i in range(6):
        draw.rectangle((60, 160 + i * 40, 600 - i * 50, 175 + i * 40), fill="#444444")
    if cursor:
        draw.rectangle((cursor, 400, cursor + 2, 418), fill="black")   # blinking caret
    return image


def test_first_frame_always_counts_as_changed():
    assert snapshots.has_changed(None, snapshots.thumbnail(slide("One")))


def test_same_slide_is_not_a_change_but_a_new_slide_is():
    a = snapshots.thumbnail(slide("One"))
    assert not snapshots.has_changed(a, snapshots.thumbnail(slide("One")))
    assert not snapshots.has_changed(a, snapshots.thumbnail(slide("One", cursor=300)))
    other = Image.new("RGB", (800, 450), "#202020")
    assert snapshots.has_changed(a, snapshots.thumbnail(other))


def test_folder_writes_numbered_pictures_and_a_timeline(tmp_path):
    out = snapshots.SnapshotFolder(tmp_path / "snaps")
    when = datetime.datetime(2026, 10, 18, 14, 5, 9)
    assert out.save(slide("One"), "Quarterly plan\nThree goals", when) == "snapshot-001.png"
    assert out.save(slide("Two"), "", when + datetime.timedelta(seconds=30)) == "snapshot-002.png"
    assert (tmp_path / "snaps" / "snapshot-002.png").exists()
    index = (tmp_path / "snaps" / "snapshots.md").read_text(encoding="utf-8")
    assert "## 14:05:09\n![Snapshot 1](snapshot-001.png)" in index
    assert "> Quarterly plan\n> Three goals" in index
    assert "## 14:05:39\n![Snapshot 2](snapshot-002.png)\n" in index


def test_default_folder_is_timestamped():
    folder = snapshots.default_folder(datetime.datetime(2026, 10, 18, 9, 0, 1))
    assert folder.name == "snapshots-20261018-090001"
