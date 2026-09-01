# Copyright 2026 Tecniloop
# License Other proprietary.

import re
import unicodedata
from difflib import SequenceMatcher

# Common OCR confusions after lowercasing.
_OCR_TRANS = str.maketrans(
    {
        "0": "o",
        "1": "l",
        "5": "s",
        "8": "b",
    }
)


def normalize_text(value, ocr=False):
    """Strip accents and punctuation. Optional OCR digit/letter swaps for names."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower()
    if ocr:
        text = text.translate(_OCR_TRANS)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def texts_match(left, right, threshold=0.88):
    norm_left = normalize_text(left, ocr=True)
    norm_right = normalize_text(right, ocr=True)
    if not norm_left or not norm_right:
        return False
    if norm_left == norm_right:
        return True
    if norm_left in norm_right or norm_right in norm_left:
        return True
    return SequenceMatcher(None, norm_left, norm_right).ratio() >= threshold


def unique_fuzzy_match(records, field_name, target, threshold=0.88):
    """Return the only record whose field looks like target, else empty."""
    hits = records.browse()
    for record in records:
        if texts_match(record[field_name], target, threshold=threshold):
            hits |= record
            if len(hits) > 1:
                return records.browse()
    return hits
