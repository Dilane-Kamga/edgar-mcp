#!/usr/bin/env python3
"""Capture EDGAR API responses as test fixtures.

Usage:
    uv run python scripts/capture_fixture.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"
USER_AGENT = "EDGAR-MCP/0.1.0 dilanekamga777@gmail.com"

TARGETS: dict[str, str] = {
    "company_tickers.json": "https://www.sec.gov/files/company_tickers.json",
    "submissions_CIK0000320193.json": (
        "https://data.sec.gov/submissions/CIK0000320193.json"
    ),
    "efts_8K_recent.json": (
        "https://efts.sec.gov/LATEST/search-index"
        "?q=%22%22&forms=8-K&dateRange=custom"
        "&startdt=2024-10-01&enddt=2024-10-02&from=0&size=50"
    ),
}

KEEP_TICKERS = {"AAPL", "MSFT", "TSLA", "NVDA", "META", "GOOGL", "AMZN"}


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    )

    for name, url in TARGETS.items():
        print(f"Capturing {name} ...")
        time.sleep(0.2)
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()

        if name == "company_tickers.json":
            data = {k: v for k, v in data.items() if v.get("ticker") in KEEP_TICKERS}

        path = FIXTURES_DIR / name
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"  -> {path} ({path.stat().st_size:,} bytes)")

    client.close()
    print("Done.")


if __name__ == "__main__":
    main()
