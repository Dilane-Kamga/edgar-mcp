"""Diagnose remaining section extraction failures from live test."""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

os.environ.setdefault("EDGAR_MCP_CONTACT", "dilanekamga777@gmail.com")

from edgar_mcp.parsers.sections import _html_to_text, extract_section  # noqa: E402

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def diagnose_section(html: str, section: str, label: str) -> None:
    """Show all candidate matches and what the extractor picks."""
    text = _html_to_text(html)
    text = re.sub(r"\n{3,}", "\n\n", text)

    from edgar_mcp.parsers.sections import _SECTION_START, _ITEM_HEADING

    patterns = _SECTION_START[section]
    print(f"\n{'='*70}")
    print(f"DIAGNOSIS: {label} — section={section}")
    print(f"{'='*70}")
    print(f"Text length: {len(text):,} chars")

    # Show heading pattern for this section
    section_label = {"risk_factors": "Item 1A", "mda": "Item 7"}[section]
    pat = re.compile(rf"item\s+{'1a' if section == 'risk_factors' else '7'}", re.IGNORECASE)
    matches = list(pat.finditer(text))
    print(f"\n'{section_label}' occurrences: {len(matches)}")

    for i, m in enumerate(matches):
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 200)
        snippet = text[start:end].replace("\n", " | ")
        snippet = re.sub(r"\s+", " ", snippet)
        remaining = text[m.end():]
        next_item = _ITEM_HEADING.search(remaining)
        dist = next_item.start() if next_item else len(remaining)
        line_start_pos = text.rfind("\n", 0, m.start())
        prefix = text[line_start_pos + 1: m.start()].strip()
        is_bol = prefix == ""
        print(f"\n  [{i}] offset={m.start():,}  next_item_dist={dist}  line_start={is_bol}  prefix={prefix[:50]!r}")
        print(f"      ...{snippet[:200]}...")

    print(f"\nExtractor result:")
    try:
        title, body = extract_section(html, section)
        wc = len(body.split())
        print(f"  title: {title!r}")
        print(f"  word_count: {wc}")
        print(f"  first 300 chars: {body[:300]!r}")
        print(f"  last 200 chars: {body[-200:]!r}")
    except ValueError as e:
        print(f"  FAILED: {e}")


async def main() -> None:
    # 1. NVIDIA FY2025 risk_factors (from saved fixture)
    nvda_2025 = FIXTURES_DIR / "nvidia_20250126_10k.html"
    if nvda_2025.exists():
        html = nvda_2025.read_text(encoding="utf-8")
        diagnose_section(html, "risk_factors", "NVIDIA FY2025")

    # 2. Meta MD&A (need to fetch)
    from edgar_mcp.client import EdgarClient
    client = EdgarClient()

    # Meta FY2025
    print("\nFetching Meta FY2025 10-K...")
    subs = await client.fetch_submissions(1326801)
    recent = subs["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            acc = recent["accessionNumber"][i]
            primary = recent["primaryDocument"][i]
            html = await client.fetch_filing_document(1326801, acc, primary)
            diagnose_section(html, "mda", f"Meta ({acc})")
            break

    # IBM MD&A
    print("\nFetching IBM FY2025 10-K...")
    subs = await client.fetch_submissions(51143)
    recent = subs["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            acc = recent["accessionNumber"][i]
            primary = recent["primaryDocument"][i]
            html = await client.fetch_filing_document(51143, acc, primary)
            diagnose_section(html, "mda", f"IBM ({acc})")
            break

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
