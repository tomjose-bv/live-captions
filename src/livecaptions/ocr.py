"""Read text from a screen region with the Windows built-in OCR engine (offline).

Heavy imports (Pillow, the WinRT bindings) stay inside the functions so the package
imports and tests stay fast.
"""

import asyncio

MIN_TEXT_HEIGHT = 300   # small captures are upscaled; Windows OCR misses tiny text


class OcrError(Exception):
    pass


def normalize_rect(x0, y0, x1, y1):
    """Return (left, top, right, bottom) for a drag in any direction."""
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def join_lines(lines):
    """Join recognised lines, dropping blanks and stray whitespace."""
    return "\n".join(line.strip() for line in lines if line and line.strip())


def capture(bbox):
    """Screenshot ``bbox`` (left, top, right, bottom) in physical screen pixels."""
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=bbox, all_screens=True)


def _prepare(image):
    from PIL import Image

    image = image.convert("RGBA")
    if image.height < MIN_TEXT_HEIGHT:
        scale = min(4, max(2, MIN_TEXT_HEIGHT // max(image.height, 1)))
        image = image.resize((image.width * scale, image.height * scale), Image.LANCZOS)
    return image


async def _recognize(image):
    try:
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import DataWriter
    except ImportError as e:
        raise OcrError("Screen text needs the Windows OCR packages. "
                       "Run: pip install -r requirements.txt") from e

    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrError("Windows has no OCR language installed. Add one under "
                       "Settings > Time & language > Language & region.")
    limit = OcrEngine.max_image_dimension
    if image.width > limit or image.height > limit:
        image.thumbnail((limit, limit))
    writer = DataWriter()
    writer.write_bytes(image.tobytes("raw", "BGRA"))
    bitmap = SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.BGRA8, image.width, image.height)
    result = await engine.recognize_async(bitmap)
    return join_lines(line.text for line in result.lines)


def recognize(image):
    """Return the text in a PIL image, one recognised line per output line."""
    return asyncio.run(_recognize(_prepare(image)))


def read_region(bbox):
    return recognize(capture(bbox))
