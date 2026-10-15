import sys

import pytest

from livecaptions import ocr


def test_normalize_rect_handles_any_drag_direction():
    assert ocr.normalize_rect(300, 200, 100, 50) == (100, 50, 300, 200)
    assert ocr.normalize_rect(10, 20, 30, 40) == (10, 20, 30, 40)


def test_join_lines_drops_blanks_and_whitespace():
    assert ocr.join_lines(["  first ", "", "   ", "second"]) == "first\nsecond"
    assert ocr.join_lines([]) == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR only")
def test_recognize_reads_rendered_text():
    pytest.importorskip("winrt.windows.media.ocr")
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("segoeui.ttf", 36)
    except OSError:
        pytest.skip("Segoe UI font not available")
    image = Image.new("RGB", (640, 150), "white")
    draw = ImageDraw.Draw(image)
    draw.text((10, 15), "Quarterly roadmap review", fill="black", font=font)
    draw.text((10, 80), "Second line of text", fill="black", font=font)
    try:
        text = ocr.recognize(image)
    except ocr.OcrError as e:
        pytest.skip(str(e))
    assert text.splitlines() == ["Quarterly roadmap review", "Second line of text"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR only")
def test_recognize_upscales_small_captures():
    pytest.importorskip("winrt.windows.media.ocr")
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("segoeui.ttf", 13)
    except OSError:
        pytest.skip("Segoe UI font not available")
    image = Image.new("RGB", (220, 24), "white")
    ImageDraw.Draw(image).text((4, 3), "Small caption text", fill="black", font=font)
    try:
        text = ocr.recognize(image)
    except ocr.OcrError as e:
        pytest.skip(str(e))
    assert text == "Small caption text"


PAGE = [f"Line {i}: the quick brown fox jumps over item {i}" for i in range(1, 31)]


def test_merge_lines_stitches_overlapping_frames():
    acc = ocr.merge_lines([], PAGE[0:10])
    acc = ocr.merge_lines(acc, PAGE[6:16])
    acc = ocr.merge_lines(acc, PAGE[14:24])
    assert acc == PAGE[0:24]


def test_merge_lines_ignores_unchanged_frames():
    acc = ocr.merge_lines(PAGE[0:10], PAGE[0:10])
    assert acc == PAGE[0:10]


def test_merge_lines_tolerates_ocr_noise_and_cut_lines():
    noisy = PAGE[7:12]
    noisy[1] = noisy[1].replace("quick", "quiek")   # OCR read one overlapping line differently
    acc = ocr.merge_lines(PAGE[0:10] + ["Line 11: the qu"], ["ox jumps over item 7"] + noisy)
    assert acc[:7] == PAGE[0:7]
    assert acc[7:] == noisy
    assert len(acc) == 12


def test_merge_lines_marks_gaps_when_scrolled_too_fast():
    acc = ocr.merge_lines(PAGE[0:5], PAGE[20:25])
    assert acc == PAGE[0:5] + [ocr.GAP_MARKER] + PAGE[20:25]


def test_merge_lines_needs_more_than_a_short_single_line():
    # "OK" appears at both edges but is too short to prove the frames overlap.
    assert ocr.merge_lines(["Alpha section text here", "OK"], ["OK", "Beta"]) == [
        "Alpha section text here", "OK", ocr.GAP_MARKER, "OK", "Beta"]
