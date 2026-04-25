"""Diagnose Accenture 10-K section extraction."""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

os.environ.setdefault("EDGAR_MCP_CONTACT", "dilanekamga777@gmail.com")

from edgar_mcp.client import EdgarClient  # noqa: E402
from edgar_mcp.parsers.sections import (  # noqa: E402
    _ITEM_HEADING,
    _SECTION_START,
    _html_to_text,
    _is_line_start,
    extract_section,
)

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
ACN_CIK = 1467373
ACN_ACCESSION = "0001467373-25-000217"


async def main() -> None:
    client = EdgarClient()

    # Find primary doc
    subs = await client.fetch_submissions(ACN_CIK)
    recent = subs["filings"]["recent"]
    idx = recent["accessionNumber"].index(ACN_ACCESSION)
    primary = recent["primaryDocument"][idx]
    print(f"Primary doc: {primary}")

    html = await client.fetch_filing_document(ACN_CIK, ACN_ACCESSION, primary)
    print(f"HTML length: {len(html):,} chars")

    # Save fixture
    path = FIXTURES_DIR / "acn_20250831_10k.html"
    path.write_text(html, encoding="utf-8")
    print(f"Saved fixture: {path.stat().st_size:,} bytes")

    # Convert to text
    text = _html_to_text(html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    print(f"Text length: {len(text):,} chars\n")

    # Find all Item 1A occurrences
    pat = re.compile(r"item\s+1a", re.IGNORECASE)
    matches = list(pat.finditer(text))
    print(f"'Item 1A' occurrences: {len(matches)}")

    for i, m in enumerate(matches):
        start = max(0, m.start() - 100)
        end = min(len(text), m.end() + 250)
        snippet = text[start:end].replace("\n", " | ")
        snippet = re.sub(r"\s+", " ", snippet)
        remaining = text[m.end():]
        next_item = _ITEM_HEADING.search(remaining)
        dist = next_item.start() if next_item else len(remaining)
        bol = _is_line_start(text, m.start())
        line_start_pos = text.rfind("\n", 0, m.start())
        prefix = text[line_start_pos + 1 : m.start()].strip()
        print(f"\n  [{i}] offset={m.start():,}  dist={dist:,}  bol={bol}  prefix={prefix[:60]!r}")
        print(f"      ...{snippet[:250]}...")

    # Run the scoring logic manually to see candidate scores
    print("\n" + "=" * 70)
    print("SCORING CANDIDATES")
    print("=" * 70)
    patterns = _SECTION_START["risk_factors"]
    for pi, pattern in enumerate(patterns):
        for m in pattern.finditer(text):
            remaining = text[m.end():]
            next_item = _ITEM_HEADING.search(remaining)
            dist = next_item.start() if next_item else len(remaining)
            if dist < 200:
                print(f"  pattern[{pi}] offset={m.start():,} dist={dist} → SKIP (TOC)")
                continue
            score = 0
            if _is_line_start(text, m.start()):
                score += 100
            score += min(dist // 100, 50)
            print(f"  pattern[{pi}] offset={m.start():,} dist={dist:,} bol={_is_line_start(text, m.start())} score={score}")

    # Run extractor
    print("\n" + "=" * 70)
    print("EXTRACTOR OUTPUT")
    print("=" * 70)
    try:
        title, body = extract_section(html, "risk_factors")
        wc = len(body.split())
        print(f"title: {title!r}")
        print(f"word count: {wc}")
        print(f"body length: {len(body):,} chars")
        print("\n--- first 500 chars ---")
        print(body[:500])
        print("\n--- last 500 chars ---")
        print(body[-500:])

        # Check for early/late content
        lower = body.lower()
        print("\n--- content checks ---")
        for kw in ["macroeconomic", "geopolitical", "cybersecurity", "irish", "ireland", "talent", "ai"]:
            print(f"  {kw}: {'FOUND' if kw in lower else 'MISSING'}")
    except ValueError as e:
        print(f"FAILED: {e}")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
