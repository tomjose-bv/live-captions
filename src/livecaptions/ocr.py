"""Read text from a screen region with the Windows built-in OCR engine (offline).

Heavy imports (Pillow, the WinRT bindings) stay inside the functions so the package
imports and tests stay fast.
"""

import asyncio
import difflib

MIN_TEXT_HEIGHT = 300   # small captures are upscaled; Windows OCR misses tiny text


class OcrError(Exception):
    pass


def normalize_rect(x0, y0, x1, y1):
    """Return (left, top, right, bottom) for a drag in any direction."""
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def join_lines(lines):
    """Join recognised lines, dropping blanks and stray whitespace."""
    return "\n".join(line.strip() for line in lines if line and line.strip())


GAP_MARKER = "[…]"   # inserted when a scroll capture lost the overlap (scrolled too fast)
SIMILAR = 0.8          # line similarity needed to treat two OCR lines as the same line
MIN_SINGLE_LINE = 15   # a one-line overlap only counts if the line is at least this long


def _norm(line):
    return " ".join(line.lower().split())


def _similar(a, b):
    a, b = _norm(a), _norm(b)
    if a == b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= SIMILAR


def _overlap_ok(acc_tail, head):
    """Most overlapping lines must match exactly (lists of near-identical lines such as
    "Item 1" / "Item 7" would otherwise look alike); the rest may differ by OCR noise."""
    if len(head) == 1 and len(_norm(head[0])) < MIN_SINGLE_LINE:
        return False
    pairs = list(zip(acc_tail, head))
    exact = sum(_norm(a) == _norm(b) for a, b in pairs)
    return exact * 2 >= len(pairs) and all(_similar(a, b) for a, b in pairs)


def merge_lines(acc, new):
    """Stitch the lines of a new scroll frame onto the lines read so far.

    Finds the largest overlap between the end of ``acc`` and the start of ``new`` and
    appends only what follows it. Lines cut in half at the frame edge are tolerated by
    also trying without ``acc``'s last line and without ``new``'s first line; the newer
    frame's reading of the overlap wins. With no overlap the frames are joined with
    ``GAP_MARKER`` so the gap is visible.
    """
    acc, new = list(acc), [line for line in new if line.strip()]
    if not acc:
        return new
    if not new:
        return acc
    best = None   # (overlap, kept_acc, frame)
    for drop_tail in (0, 1):
        kept = acc[:len(acc) - drop_tail] if drop_tail else acc
        for skip in (0, 1):
            frame = new[skip:]
            for k in range(min(len(kept), len(frame)), 0, -1):
                if best and k <= best[0]:
                    break
                if _overlap_ok(kept[len(kept) - k:], frame[:k]):
                    best = (k, kept[:len(kept) - k], frame)
                    break
    if best:
        return best[1] + best[2]
    return acc + [GAP_MARKER] + new


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
