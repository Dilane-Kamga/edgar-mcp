from __future__ import annotations

import re

from selectolax.parser import HTMLParser  # type: ignore[import-untyped]

_ITEM_HEADING = re.compile(
    r"(?:ITEM|Item)\s+\d+[A-Z]?\.?\s",
    re.IGNORECASE,
)

_ITEM_HEADING_BOL = re.compile(
    r"(?:^|\n)\s*(?:ITEM|Item)\s+\d+[A-Z]?\.?\s",
    re.IGNORECASE,
)

_SECTION_START: dict[str, list[re.Pattern[str]]] = {
    "risk_factors": [
        re.compile(
            r"(?:ITEM|Item)\s+1A[\.\s][\s\S]*?Risk\s+Factors", re.IGNORECASE
        ),
        re.compile(r"(?:ITEM|Item)\s+1A[\.\s]", re.IGNORECASE),
    ],
    "mda": [
        re.compile(
            r"(?:ITEM|Item)\s+7[\.\s][\s\S]*?Management.s\s+Discussion",
            re.IGNORECASE,
        ),
        re.compile(r"(?:ITEM|Item)\s+7[\.\s]", re.IGNORECASE),
    ],
    "business": [
        re.compile(
            r"(?:ITEM|Item)\s+1[\.\s]+(?!A)[\s\S]*?Business", re.IGNORECASE
        ),
        re.compile(r"(?:ITEM|Item)\s+1[\.\s]+(?!A)", re.IGNORECASE),
    ],
    "legal_proceedings": [
        re.compile(
            r"(?:ITEM|Item)\s+3[\.\s][\s\S]*?Legal\s+Proceedings",
            re.IGNORECASE,
        ),
        re.compile(r"(?:ITEM|Item)\s+3[\.\s]", re.IGNORECASE),
    ],
    "properties": [
        re.compile(
            r"(?:ITEM|Item)\s+2[\.\s][\s\S]*?Properties", re.IGNORECASE
        ),
        re.compile(r"(?:ITEM|Item)\s+2[\.\s]", re.IGNORECASE),
    ],
    "controls_and_procedures": [
        re.compile(
            r"(?:ITEM|Item)\s+9A[\.\s][\s\S]*?Controls\s+and\s+Procedures",
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


def _is_line_start(text: str, match_start: int) -> bool:
    """Check if the match begins at the start of a line (after optional whitespace)."""
    line_start = text.rfind("\n", 0, match_start)
    prefix = text[line_start + 1 : match_start].strip()
    return prefix == ""


def extract_section(html: str, section: str) -> tuple[str, str]:
    """Extract a semantic section from filing HTML.

    Uses a scoring approach: collects all candidate matches across all
    patterns, scores each by line-start anchoring and content length,
    then picks the best one. This avoids latching onto cross-references
    in forward-looking statements or other mid-paragraph mentions.

    Returns (title, cleaned_text).
    Raises ValueError if the section is not found.
    """
    if section not in _SECTION_START:
        raise ValueError(
            f"Unknown section '{section}'. "
            f"Supported: {', '.join(SUPPORTED_SECTIONS)}"
        )

    text = _html_to_text(html)
    text = re.sub(r"\n{3,}", "\n\n", text)

    patterns = _SECTION_START[section]
    candidates: list[tuple[int, re.Match[str]]] = []

    for pattern in patterns:
        for m in pattern.finditer(text):
            remaining = text[m.end() :]
            next_item = _ITEM_HEADING.search(remaining)
            dist = next_item.start() if next_item else len(remaining)

            # Hard skip: TOC entries where the next heading is very close
            if dist < 200:
                continue

            score = 0

            # Strong signal: heading at the start of a line (not mid-paragraph)
            if _is_line_start(text, m.start()):
                score += 100

            # Longer content to next heading = more likely the real section
            score += min(dist // 100, 50)

            candidates.append((score, m))

    if not candidates:
        raise ValueError(f"Section '{section}' not found in filing HTML")

    candidates.sort(key=lambda x: (x[0], -x[1].start()), reverse=True)
    best_match = candidates[0][1]

    title = best_match.group(0).strip()
    body = text[best_match.end() :]

    # Extract the item number so we skip page headers that repeat it
    item_num_match = re.search(
        r"(?:ITEM|Item)\s+(\d+[A-Z]?)", best_match.group(0), re.IGNORECASE
    )
    current_item = item_num_match.group(1).upper() if item_num_match else ""

    # Find the next DIFFERENT item heading at line start
    for end_match in _ITEM_HEADING_BOL.finditer(body):
        end_item_match = re.search(
            r"(?:ITEM|Item)\s+(\d+[A-Z]?)", end_match.group(0), re.IGNORECASE
        )
        if end_item_match and end_item_match.group(1).upper() != current_item:
            body = body[: end_match.start()]
            break

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
