"""Diagnose failures from the 100-company stress test.

Fetches the failing companies' 10-Ks and shows the raw text around
where "Item 1A" should appear, to understand why the parser missed.
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

FAILURES = {
    "not_found": [
        ("MCD", 63908),
        ("HON", 773840),
        ("MS", 895421),
        ("C", 831001),
        ("WFC", 72971),
        ("GE", 40545),
        ("CMCSA", 1166691),
        ("INTC", 50863),
    ],
    "forward_looking": [
        ("UNH", 731766),
        ("ADBE", 796343),
        ("NKE", 320187),
        ("PM", 1413329),
    ],
    "toc": [
        ("COST", 909832),
        ("CAT", 18230),
    ],
    "too_short": [
        ("TMO", 97745),
        ("NSC", 702165),
    ],
    "too_long": [
        ("O", 726728),
    ],
}


async def find_latest_10k(client: EdgarClient, cik: int) -> tuple[str, str] | None:
    subs = await client.fetch_submissions(cik)
    recent = subs["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            return recent["accessionNumber"][i], recent["primaryDocument"][i]
    return None


async def diagnose_not_found(client: EdgarClient, ticker: str, cik: int) -> None:
    print(f"\n{'='*70}")
    print(f"{ticker} (CIK {cik}) - NOT FOUND")
    print("=" * 70)

    found = await find_latest_10k(client, cik)
    if not found:
        print("  No 10-K filing found at all")
        return

    acc, primary = found
    print(f"  Accession: {acc}, Primary: {primary}")
    html = await client.fetch_filing_document(cik, acc, primary)
    text = _html_to_text(html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    print(f"  Text length: {len(text):,} chars")

    # Search broadly for item 1a
    pat = re.compile(r"item\s*1\s*a", re.IGNORECASE)
    matches = list(pat.finditer(text))
    print(f"  Broad 'item 1a' matches: {len(matches)}")

    for i, m in enumerate(matches[:8]):
        start = max(0, m.start() - 50)
        end = min(len(text), m.end() + 200)
        snippet = text[start:end].replace("\n", " | ")
        snippet = re.sub(r"\s+", " ", snippet)
        print(f"    [{i}] offset={m.start():,}: ...{snippet[:200]}...")

    # Also check for "risk factor" without item heading
    rf = re.compile(r"risk\s+factors?", re.IGNORECASE)
    rf_matches = list(rf.finditer(text))
    print(f"  'risk factor(s)' matches: {len(rf_matches)}")
    for i, m in enumerate(rf_matches[:5]):
        start = max(0, m.start() - 80)
        end = min(len(text), m.end() + 100)
        snippet = text[start:end].replace("\n", " | ")
        snippet = re.sub(r"\s+", " ", snippet)
        print(f"    [{i}] offset={m.start():,}: ...{snippet[:200]}...")


async def diagnose_forward_looking(client: EdgarClient, ticker: str, cik: int) -> None:
    print(f"\n{'='*70}")
    print(f"{ticker} (CIK {cik}) - FORWARD-LOOKING BOILERPLATE")
    print("=" * 70)

    found = await find_latest_10k(client, cik)
    if not found:
        return

    acc, primary = found
    html = await client.fetch_filing_document(cik, acc, primary)
    try:
        title, body = extract_section(html, "risk_factors")
        print(f"  Title: {title!r}")
        print(f"  Word count: {len(body.split())}")
        print(f"  First 500 chars:")
        print(f"    {body[:500]}")
    except ValueError as e:
        print(f"  ERROR: {e}")


async def diagnose_boundary(client: EdgarClient, ticker: str, cik: int, label: str) -> None:
    print(f"\n{'='*70}")
    print(f"{ticker} (CIK {cik}) - {label}")
    print("=" * 70)

    found = await find_latest_10k(client, cik)
    if not found:
        return

    acc, primary = found
    html = await client.fetch_filing_document(cik, acc, primary)
    try:
        title, body = extract_section(html, "risk_factors")
        wc = len(body.split())
        print(f"  Title: {title!r}")
        print(f"  Word count: {wc}")
        print(f"  First 300 chars: {body[:300]}")
        print(f"  Last 300 chars: {body[-300:]}")
    except ValueError as e:
        print(f"  ERROR: {e}")


async def main() -> None:
    client = EdgarClient()

    print("DIAGNOSING NOT-FOUND FAILURES")
    for ticker, cik in FAILURES["not_found"]:
        await diagnose_not_found(client, ticker, cik)

    print("\n\nDIAGNOSING FORWARD-LOOKING FAILURES (sample)")
    for ticker, cik in FAILURES["forward_looking"]:
        await diagnose_forward_looking(client, ticker, cik)

    print("\n\nDIAGNOSING TOC / SHORT / LONG FAILURES")
    for ticker, cik in FAILURES["toc"]:
        await diagnose_boundary(client, ticker, cik, "TOC SELECTED")
    for ticker, cik in FAILURES["too_short"]:
        await diagnose_boundary(client, ticker, cik, "TOO SHORT")
    for ticker, cik in FAILURES["too_long"]:
        await diagnose_boundary(client, ticker, cik, "TOO LONG")

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
