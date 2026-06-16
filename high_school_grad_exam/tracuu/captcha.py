"""Captcha solver wrapping ddddocr.

The live captcha is 5 chars of solid-blue text on a noisy grid. ddddocr handles this
style well but outputs lowercase (it does not preserve case); whether that matters is a
property of the backend (see the probe). The image bytes may arrive as a raw PNG or as a
base64-encoded PNG, and samples can be slightly truncated, so loading is made tolerant.
"""

import base64

from PIL import ImageFile
import ddddocr

# GDI+ tolerates truncated PNGs but Pillow (used by ddddocr) does not by default.
ImageFile.LOAD_TRUNCATED_IMAGES = True

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def to_png_bytes(data: bytes) -> bytes:
    """Return raw PNG bytes whether ``data`` is already a PNG or base64-encoded PNG text."""
    if data[:8] == _PNG_MAGIC:
        return data
    try:
        decoded = base64.b64decode(data.strip(), validate=False)
        if decoded[:8] == _PNG_MAGIC:
            return decoded
    except Exception:
        pass
    return data  # let Pillow attempt it as-is


class CaptchaSolver:
    def __init__(self, beta=True):
        self.beta = beta
        self._ocr = ddddocr.DdddOcr(show_ad=False, beta=beta)

    def solve(self, data: bytes) -> str:
        """Return the model's best guess, reduced to alphanumeric characters."""
        png = to_png_bytes(data)
        text = self._ocr.classification(png)
        return "".join(ch for ch in text if ch.isalnum())
