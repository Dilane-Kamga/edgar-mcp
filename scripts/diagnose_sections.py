"""Diagnose the Apple 10-K section extraction bug.

Fetches Apple's FY2025 10-K from EDGAR, runs the section extractor,
and inspects every 'Item 1A' occurrence in the raw HTML to find
where the parser is latching on.
"""
from __future__ import annotations

import asyncio
import os
import re

os.environ.setdefault("EDGAR_MCP_CONTACT", "dilanekamga777@gmail.com")

from edgar_mcp.client import EdgarClient  # noqa: E402
from edgar_mcp.parsers.sections import (  # noqa: E402
    _html_to_text,
    extract_section,
)

APPLE_CIK = 320193
APPLE_10K_ACCESSION = "0000320193-25-000079"
PRIMARY_DOC = "aapl-20250927.htm"


async def main() -> None:
    client = EdgarClient()

    # 1. Fetch the raw HTML
    print("Fetching Apple FY2025 10-K primary document...")
    html = await client.fetch_filing_document(
        APPLE_CIK, APPLE_10K_ACCESSION, PRIMARY_DOC
    )
    print(f"HTML length: {len(html):,} chars\n")

    # 2. Convert to text (same as the parser does)
    text = _html_to_text(html)
    print(f"Plain text length: {len(text):,} chars\n")

    # 3. Find every 'Item 1A' occurrence in the plain text
    pattern = re.compile(r"item\s+1a", re.IGNORECASE)
    matches = list(pattern.finditer(text))
    print(f"'Item 1A' occurrences in plain text: {len(matches)}")
    for i, m in enumerate(matches):
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 200)
        snippet = text[start:end].replace("\n", " | ")
        snippet = re.sub(r"\s+", " ", snippet)
        # Check distance to next item heading
        remaining = text[m.end():]
        next_item = re.search(r"(?:ITEM|Item)\s+\d+[A-Z]?\.?\s", remaining)
        dist = next_item.start() if next_item else -1
        print(f"\n  [{i}] offset={m.start():,}  next_item_dist={dist}")
        print(f"      ...{snippet}...")

    # 4. Run the actual extractor
    print("\n" + "=" * 70)
    print("EXTRACTOR OUTPUT")
    print("=" * 70)
    try:
        title, body = extract_section(html, "risk_factors")
        print(f"title: {title!r}")
        print(f"body length: {len(body):,} chars")
        print(f"word count: {len(body.split())}")
        print(f"\n--- first 800 chars ---")
        print(body[:800])
        print(f"\n--- last 800 chars ---")
        print(body[-800:])
    except ValueError as e:
        print(f"EXTRACTION FAILED: {e}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
