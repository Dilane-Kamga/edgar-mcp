"""Stress test: run section extraction against 100 real 10-K filings.

Fetches the SEC company tickers list, picks 100 companies that have
recent 10-K filings, extracts risk_factors from each, and reports
pass/fail statistics.

Usage:
    EDGAR_MCP_CONTACT="you@example.com" uv run python scripts/stress_test_100.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

os.environ.setdefault("EDGAR_MCP_CONTACT", "dilanekamga777@gmail.com")

from edgar_mcp.client import EdgarClient  # noqa: E402
from edgar_mcp.parsers.sections import extract_section  # noqa: E402

TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "BRK-B", "JPM",
    "JNJ", "V", "UNH", "PG", "HD", "MA", "DIS", "ADBE", "CRM", "NFLX",
    "PFE", "CSCO", "PEP", "TMO", "ABT", "COST", "AVGO", "NKE", "ACN",
    "MRK", "WMT", "LLY", "MCD", "DHR", "TXN", "NEE", "PM", "UNP",
    "HON", "RTX", "LOW", "UPS", "IBM", "CVX", "XOM", "COP",
    "GS", "MS", "AXP", "BLK", "SCHW", "C", "BAC", "WFC",
    "LMT", "BA", "CAT", "DE", "GE", "MMM", "EMR",
    "AMGN", "GILD", "ISRG", "MDT", "SYK", "BMY", "VRTX", "REGN",
    "SBUX", "YUM", "KO", "MDLZ", "CL", "EL", "KMB",
    "AMT", "PLD", "SPG", "EQIX", "O",
    "SO", "DUK", "AEP", "D", "SRE", "EXC",
    "FDX", "DAL", "LUV", "CSX", "NSC",
    "T", "VZ", "TMUS", "CMCSA", "CHTR",
    "ORCL", "INTC", "AMD", "QCOM", "MU", "AMAT",
    "WM", "RSG", "ECL", "SHW",
    "F", "GM", "TM",
]


async def resolve_tickers(client: EdgarClient) -> dict[str, int]:
    """Map ticker -> CIK using SEC company_tickers.json."""
    data = await client.fetch_company_tickers()
    result: dict[str, int] = {}
    for entry in data.values():
        ticker = entry.get("ticker", "")
        cik = entry.get("cik_str", 0)
        if ticker and cik:
            result[ticker.upper()] = int(cik)
    return result


async def find_latest_10k(
    client: EdgarClient, cik: int
) -> tuple[str, str] | None:
    """Return (accession, primaryDocument) for the most recent 10-K, or None."""
    subs = await client.fetch_submissions(cik)
    recent = subs["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        if form == "10-K":
            return recent["accessionNumber"][i], recent["primaryDocument"][i]
    return None


def check_extraction(html: str) -> tuple[str, int, list[str], list[str]]:
    """Extract risk_factors, return (title, word_count, errors, warnings)."""
    title, body = extract_section(html, "risk_factors")
    wc = len(body.split())
    errors: list[str] = []
    warnings: list[str] = []
    first_200 = body[:200].lower()

    if wc < 500:
        errors.append(f"too short ({wc} words)")
    if wc > 50000:
        errors.append(f"too long ({wc} words) - end boundary missed?")
    if "forward-looking" in first_200 or "safe harbor" in first_200:
        warnings.append("starts with forward-looking preamble")
    if "table of contents" in first_200:
        errors.append("starts with table of contents")

    return title, wc, errors, warnings


async def test_one(
    client: EdgarClient, ticker: str, cik: int
) -> dict[str, object]:
    """Test extraction for one company. Returns result dict."""
    result: dict[str, object] = {
        "ticker": ticker,
        "cik": cik,
        "status": "unknown",
        "word_count": 0,
        "errors": [],
    }

    try:
        found = await find_latest_10k(client, cik)
        if found is None:
            result["status"] = "skip"
            result["errors"] = ["no 10-K found"]
            return result

        accession, primary_doc = found
        html = await client.fetch_filing_document(cik, accession, primary_doc)
        title, wc, errors, warnings = check_extraction(html)
        result["word_count"] = wc
        result["title"] = title
        result["accession"] = accession
        result["warnings"] = warnings

        if errors:
            result["status"] = "FAIL"
            result["errors"] = errors
        elif warnings:
            result["status"] = "WARN"
            result["errors"] = warnings
        else:
            result["status"] = "PASS"

    except ValueError as e:
        result["status"] = "FAIL"
        result["errors"] = [str(e)]
    except Exception as e:
        result["status"] = "ERROR"
        result["errors"] = [f"{type(e).__name__}: {e}"]

    return result


async def main() -> None:
    client = EdgarClient()
    t0 = time.time()

    print("Resolving tickers to CIKs...")
    ticker_map = await resolve_tickers(client)

    resolved = []
    missing = []
    for t in TICKERS:
        cik = ticker_map.get(t.upper().replace("-", "."))
        if cik is None:
            cik = ticker_map.get(t.upper())
        if cik:
            resolved.append((t, cik))
        else:
            missing.append(t)

    if missing:
        print(f"  Could not resolve {len(missing)} tickers: {', '.join(missing[:20])}")
    print(f"  Resolved {len(resolved)} companies\n")

    target = min(100, len(resolved))
    to_test = resolved[:target]

    print(f"Testing {target} companies...")
    print(f"{'#':>3}  {'Ticker':<8} {'CIK':>10}  {'Status':<6} {'Words':>7}  Details")
    print("-" * 80)

    passes = 0
    warns = 0
    fails = 0
    skips = 0
    errors = 0
    word_counts: list[int] = []
    fail_details: list[dict[str, object]] = []
    warn_details: list[dict[str, object]] = []

    for i, (ticker, cik) in enumerate(to_test, 1):
        r = await test_one(client, ticker, cik)
        status = r["status"]
        wc = r["word_count"]

        if status == "PASS":
            passes += 1
            word_counts.append(int(wc))  # type: ignore[arg-type]
            detail = ""
        elif status == "WARN":
            warns += 1
            warn_details.append(r)
            word_counts.append(int(wc))  # type: ignore[arg-type]
            detail = "; ".join(str(e) for e in r["errors"])  # type: ignore[union-attr]
        elif status == "skip":
            skips += 1
            detail = str(r["errors"])
        elif status == "FAIL":
            fails += 1
            fail_details.append(r)
            detail = "; ".join(str(e) for e in r["errors"])  # type: ignore[union-attr]
            if isinstance(wc, int) and wc > 0:
                word_counts.append(wc)
        else:
            errors += 1
            fail_details.append(r)
            detail = "; ".join(str(e) for e in r["errors"])  # type: ignore[union-attr]

        status_str = str(status)
        print(f"{i:>3}  {ticker:<8} {cik:>10}  {status_str:<6} {wc:>7}  {detail}")

    elapsed = time.time() - t0
    testable = passes + warns + fails

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"  Total tested:  {target}")
    print(f"  Passed:        {passes}")
    print(f"  Warnings:      {warns} (correct content, cosmetic preamble)")
    print(f"  Failed:        {fails}")
    print(f"  Skipped:       {skips} (no 10-K)")
    print(f"  Errors:        {errors} (network/SSL)")
    if word_counts:
        avg = sum(word_counts) // len(word_counts)
        lo = min(word_counts)
        hi = max(word_counts)
        print(f"  Word counts:   avg={avg:,}  min={lo:,}  max={hi:,}")
    print(f"  Elapsed:       {elapsed:.1f}s")

    if warn_details:
        print(f"\n{'='*80}")
        print("WARNINGS (correct content, cosmetic preamble)")
        print("=" * 80)
        for r in warn_details:
            errs = "; ".join(str(e) for e in r["errors"])  # type: ignore[union-attr]
            print(f"  {r['ticker']} (CIK {r['cik']}): {errs}")

    if fail_details:
        print(f"\n{'='*80}")
        print("FAILURES (extraction bugs)")
        print("=" * 80)
        for r in fail_details:
            errs = "; ".join(str(e) for e in r["errors"])  # type: ignore[union-attr]
            print(f"  {r['ticker']} (CIK {r['cik']}): {errs}")

    await client.close()

    correct = passes + warns
    correct_rate = correct / max(testable, 1) * 100
    strict_rate = passes / max(testable, 1) * 100
    print(f"\nCorrect extraction: {correct_rate:.0f}% ({correct}/{testable})")
    print(f"Strict (no preamble): {strict_rate:.0f}% ({passes}/{testable})")

    if fails > 5:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
