"""Small dependency-free text helpers used by the chat boundary."""

import re


def normalize_farsi(text: str) -> str:
    """Normalize common Arabic/Persian variants and invisible characters."""
    text = text.replace("ي", "ی").replace("ك", "ک")
    # ZWNJ separates words in some user input; directional marks are purely
    # presentational and should disappear without introducing punctuation gaps.
    text = re.sub(r"\u200c+", " ", text)
    text = re.sub(r"[\u200d\u200e\u200f]+", "", text)
    return text.strip()
