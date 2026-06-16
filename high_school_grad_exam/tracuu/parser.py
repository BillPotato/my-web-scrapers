"""Classify a lookup response into one of four outcomes.

Confirmed from live captures (all responses are HTTP 200 / application/json):
  - SUCCESS       : JSON object with student fields (has "SBD", no "Message").
  - WRONG_CAPTCHA : {"Message": "Mã xác nhận không hợp lệ"}        -> re-solve and retry.
  - NOT_FOUND     : {"Message": "Không tìm thấy thí sinh."}        -> record, stop.
  - ERROR         : anything else (other message, non-JSON, bad shape).

Vietnamese diacritics are stripped before matching so the classification is robust to
NFC/NFD encoding differences.
"""

import unicodedata
from enum import Enum


class Outcome(Enum):
    SUCCESS = "success"
    WRONG_CAPTCHA = "wrong_captcha"
    NOT_FOUND = "not_found"
    ERROR = "error"


def _fold(text: str) -> str:
    """Lowercase and strip diacritics, e.g. 'Không tìm thấy' -> 'khong tim thay'."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return stripped.lower()


def classify(response):
    """Return (Outcome, payload). payload is the student dict for SUCCESS, else the message/raw."""
    try:
        obj = response.json()
    except ValueError:
        return Outcome.ERROR, {"_status": response.status_code, "_raw": response.text[:500]}

    if isinstance(obj, dict) and "Message" in obj and "SBD" not in obj:
        message = obj.get("Message", "")
        folded = _fold(message)
        if "tim thay" in folded or "thi sinh" in folded:
            return Outcome.NOT_FOUND, message
        if "xac nhan" in folded or "hop le" in folded:
            return Outcome.WRONG_CAPTCHA, message
        return Outcome.ERROR, message

    if isinstance(obj, dict) and "SBD" in obj:
        return Outcome.SUCCESS, obj

    return Outcome.ERROR, obj
