"""Live integration test: run section extraction against real EDGAR filings.

Tests Apple, NVIDIA, Meta, IBM, and Accenture 10-Ks to verify the parser
handles different formatting styles correctly.

Usage:
    EDGAR_MCP_CONTACT="you@example.com" uv run python scripts/test_sections_live.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("EDGAR_MCP_CONTACT", "dilanekamga777@gmail.com")

from edgar_mcp.client import EdgarClient  # noqa: E402
from edgar_mcp.parsers.sections import extract_section  # noqa: E402

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


async def fetch_primary_doc(
    client: EdgarClient, cik: int, accession: str
) -> tuple[str, str]:
    """Fetch submissions to find primaryDocument, then fetch the HTML."""
    submissions = await client.fetch_submissions(cik)
    recent = submissions["filings"]["recent"]
    accessions = recent["accessionNumber"]
    idx = accessions.index(accession)
    primary = recent["primaryDocument"][idx]
    html = await client.fetch_filing_document(cik, accession, primary)
    return primary, html


async def find_10k_accessions(
    client: EdgarClient, cik: int, count: int = 2
) -> list[tuple[str, str, str]]:
    """Return [(accession, filed, period), ...] for the last `count` 10-Ks."""
    submissions = await client.fetch_submissions(cik)
    recent = submissions["filings"]["recent"]
    results = []
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            results.append((
                recent["accessionNumber"][i],
                recent["filingDate"][i],
                recent["reportDate"][i],
            ))
            if len(results) >= count:
                break
    return results


def test_section(
    html: str, section: str, company: str, accession: str
) -> tuple[bool, str, int]:
    """Extract a section and run sanity checks. Returns (ok, message, word_count)."""
    try:
        title, body = extract_section(html, section)
    except ValueError as e:
        return False, f"EXTRACTION FAILED: {e}", 0

    word_count = len(body.split())
    first_500 = body[:500].lower()

    errors = []
    if word_count < 500:
        errors.append(f"Too short: {word_count} words (expected >500)")
    if "forward-looking" in first_500 or "safe harbor" in first_500:
        errors.append("Starts with forward-looking boilerplate")
    if "table of contents" in first_500:
        errors.append("Starts with table of contents")

    if errors:
        return False, "; ".join(errors), word_count
    return True, f"OK ({word_count:,} words, title={title!r})", word_count


async def main() -> None:
    client = EdgarClient()
    all_passed = True

    # Companies to test: (name, CIK)
    companies = [
        ("Apple", 320193),
        ("NVIDIA", 1045810),
        ("Meta", 1326801),
        ("IBM", 51143),
        ("Accenture", 1281761),
    ]

    save_fixtures: dict[str, tuple[str, str]] = {}

    print("=" * 70)
    print("LIVE SECTION EXTRACTION TEST")
    print("=" * 70)

    for company_name, cik in companies:
        print(f"\n--- {company_name} (CIK {cik}) ---")
        filings = await find_10k_accessions(client, cik, count=2)
        if not filings:
            print("  NO 10-K FILINGS FOUND")
            all_passed = False
            continue

        for acc, filed, period in filings:
            print(f"\n  Accession: {acc} (filed {filed}, period {period})")
            try:
                primary, html = await fetch_primary_doc(client, cik, acc)
                print(f"  Primary doc: {primary} ({len(html):,} chars)")
            except Exception as e:
                print(f"  FETCH FAILED: {e}")
                all_passed = False
                continue

            # Save fixtures for Apple and NVIDIA
            fixture_key = f"{company_name.lower()}_{period.replace('-', '')}"
            if company_name in ("Apple", "NVIDIA"):
                save_fixtures[fixture_key] = (acc, html)

            for section in ["risk_factors", "mda"]:
                ok, msg, wc = test_section(html, section, company_name, acc)
                status = "PASS" if ok else "FAIL"
                if not ok:
                    all_passed = False
                print(f"  [{status}] {section}: {msg}")

    # Save fixtures for regression tests
    print("\n" + "=" * 70)
    print("SAVING FIXTURES")
    print("=" * 70)
    for key, (acc, html) in save_fixtures.items():
        filename = f"{key}_10k.html"
        path = FIXTURES_DIR / filename
        path.write_text(html, encoding="utf-8")
        print(f"  {filename}: {path.stat().st_size:,} bytes")

    await client.close()

    print("\n" + "=" * 70)
    if all_passed:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
