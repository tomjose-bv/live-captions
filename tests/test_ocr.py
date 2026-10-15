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
