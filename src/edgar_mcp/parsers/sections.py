from __future__ import annotations

import re

from selectolax.parser import HTMLParser  # type: ignore[import-untyped]

_ITEM_HEADING = re.compile(
    r"(?:ITEM|Item)\s+\d+[A-Z]?\.?\s",
    re.IGNORECASE,
)

_SECTION_START: dict[str, list[re.Pattern[str]]] = {
    "risk_factors": [
        re.compile(r"(?:ITEM|Item)\s+1A[\.\s].*?Risk\s+Factors", re.IGNORECASE),
        re.compile(r"(?:ITEM|Item)\s+1A[\.\s]", re.IGNORECASE),
    ],
    "mda": [
        re.compile(
            r"(?:ITEM|Item)\s+7[\.\s].*?Management.s\s+Discussion",
            re.IGNORECASE,
        ),
        re.compile(r"(?:ITEM|Item)\s+7[\.\s]", re.IGNORECASE),
    ],
    "business": [
        re.compile(r"(?:ITEM|Item)\s+1[\.\s]+(?!A).*?Business", re.IGNORECASE),
        re.compile(r"(?:ITEM|Item)\s+1[\.\s]+(?!A)", re.IGNORECASE),
    ],
    "legal_proceedings": [
        re.compile(
            r"(?:ITEM|Item)\s+3[\.\s].*?Legal\s+Proceedings", re.IGNORECASE
        ),
        re.compile(r"(?:ITEM|Item)\s+3[\.\s]", re.IGNORECASE),
    ],
    "properties": [
        re.compile(r"(?:ITEM|Item)\s+2[\.\s].*?Properties", re.IGNORECASE),
        re.compile(r"(?:ITEM|Item)\s+2[\.\s]", re.IGNORECASE),
    ],
    "controls_and_procedures": [
        re.compile(
            r"(?:ITEM|Item)\s+9A[\.\s].*?Controls\s+and\s+Procedures",
            re.IGNORECASE,
        ),
        re.compile(r"(?:ITEM|Item)\s+9A[\.\s]", re.IGNORECASE),
    ],
}

SUPPORTED_SECTIONS = list(_SECTION_START.keys())


def _html_to_text(html: str) -> str:
    tree = HTMLParser(html)
    if tree.body is None:
        return ""
    return tree.body.text(separator="\n")


def _clean_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def extract_section(html: str, section: str) -> tuple[str, str]:
    """Extract a semantic section from filing HTML.

    Returns (title, cleaned_text).
    Raises ValueError if the section is not found.
    """
    if section not in _SECTION_START:
        raise ValueError(
            f"Unknown section '{section}'. "
            f"Supported: {', '.join(SUPPORTED_SECTIONS)}"
        )

    text = _html_to_text(html)
    patterns = _SECTION_START[section]

    best_match: re.Match[str] | None = None
    for pattern in patterns:
        for m in pattern.finditer(text):
            remaining = text[m.end() :]
            next_item = _ITEM_HEADING.search(remaining)
            # Skip TOC-like entries (< 500 chars to next item heading)
            if next_item is not None and next_item.start() < 500:
                continue
            best_match = m
            break
        if best_match is not None:
            break

    if best_match is None:
        raise ValueError(
            f"Section '{section}' not found in filing HTML"
        )

    title = best_match.group(0).strip()
    body = text[best_match.end() :]

    end_match = _ITEM_HEADING.search(body)
    if end_match:
        body = body[: end_match.start()]

    return title, _clean_text(body)


def paginate_section(text: str, max_words: int = 8000) -> list[str]:
    """Split section text into chunks of roughly max_words."""
    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n\n")
    current: list[str] = []
    current_wc = 0

    for para in paragraphs:
        para_wc = len(para.split())
        if current_wc + para_wc > max_words and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_wc = para_wc
        else:
            current.append(para)
            current_wc += para_wc

    if current:
        chunks.append("\n\n".join(current))

    return chunks
