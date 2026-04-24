from __future__ import annotations

import asyncio
import os
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from .cache import disk_cache


class EdgarClientError(Exception):
    pass


class EdgarClient:
    _DATA_BASE = "https://data.sec.gov"
    _SEC_BASE = "https://www.sec.gov"
    _EFTS_BASE = "https://efts.sec.gov"

    def __init__(self) -> None:
        contact = os.environ.get("EDGAR_MCP_CONTACT")
        if not contact:
            raise EdgarClientError(
                "EDGAR_MCP_CONTACT env var is required. "
                "Set it to an email the SEC can reach you at."
            )
        self._user_agent = f"EDGAR-MCP/0.1.0 {contact}"
        self._http = httpx.AsyncClient(
            headers={"User-Agent": self._user_agent},
            timeout=30.0,
        )
        self._tokens = 10.0
        self._max_tokens = 10.0
        self._refill_rate = 10.0
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def _acquire_token(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(
                self._max_tokens,
                self._tokens + elapsed * self._refill_rate,
            )
            self._last_refill = now
            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._refill_rate
                await asyncio.sleep(wait)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0

    async def _request(
        self,
        url: str,
        *,
        cacheable: bool = True,
        ttl: int | None = None,
        as_json: bool = True,
    ) -> Any:
        if cacheable:
            hit = disk_cache.get(url)
            if hit is not None:
                return hit

        await self._acquire_token()

        last_exc: Exception | None = None
        for attempt in range(3):
            resp = await self._http.get(url)

            if resp.status_code == 200:
                data: Any = resp.json() if as_json else resp.text
                if cacheable:
                    disk_cache.set(url, data, expire=ttl)
                return data

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "10"))
                await asyncio.sleep(retry_after)
                last_exc = EdgarClientError(f"Rate limited on {url}")
                continue

            if resp.status_code >= 500:
                await asyncio.sleep(2.0**attempt)
                last_exc = EdgarClientError(
                    f"Server error {resp.status_code} on {url}"
                )
                continue

            resp.raise_for_status()

        raise last_exc or EdgarClientError(f"Failed to fetch {url}")

    async def get_json(
        self,
        url: str,
        *,
        cacheable: bool = True,
        ttl: int | None = None,
    ) -> Any:
        return await self._request(url, cacheable=cacheable, ttl=ttl, as_json=True)

    async def get_text(
        self,
        url: str,
        *,
        cacheable: bool = True,
        ttl: int | None = None,
    ) -> str:
        return await self._request(url, cacheable=cacheable, ttl=ttl, as_json=False)

    # -- High-level fetchers ------------------------------------------------

    async def fetch_company_tickers(self) -> dict[str, Any]:
        url = f"{self._SEC_BASE}/files/company_tickers.json"
        return await self.get_json(url, cacheable=True, ttl=3600)

    async def fetch_submissions(self, cik: int) -> dict[str, Any]:
        padded = str(cik).zfill(10)
        url = f"{self._DATA_BASE}/submissions/CIK{padded}.json"
        return await self.get_json(url, cacheable=False)

    async def search_filings(
        self,
        forms: str,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {
            "q": '""',
            "forms": forms,
            "from": 0,
            "size": limit,
        }
        if start_date or end_date:
            params["dateRange"] = "custom"
            if start_date:
                params["startdt"] = start_date
            if end_date:
                params["enddt"] = end_date
        url = f"{self._EFTS_BASE}/LATEST/search-index?{urlencode(params)}"
        return await self.get_json(url, cacheable=False)

    async def fetch_filing_index(self, cik: int, accession: str) -> dict[str, Any]:
        acc_nodash = accession.replace("-", "")
        url = f"{self._SEC_BASE}/Archives/edgar/data/{cik}/{acc_nodash}/index.json"
        return await self.get_json(url)

    async def fetch_filing_document(
        self, cik: int, accession: str, filename: str
    ) -> str:
        acc_nodash = accession.replace("-", "")
        url = f"{self._SEC_BASE}/Archives/edgar/data/{cik}/{acc_nodash}/{filename}"
        return await self.get_text(url)

    async def fetch_xbrl_companyfacts(self, cik: int) -> dict[str, Any]:
        padded = str(cik).zfill(10)
        url = f"{self._DATA_BASE}/api/xbrl/companyfacts/CIK{padded}.json"
        return await self.get_json(url, ttl=3600)

    def filing_document_url(
        self, cik: int, accession: str, filename: str
    ) -> str:
        acc_nodash = accession.replace("-", "")
        return (
            f"{self._SEC_BASE}/Archives/edgar/data/{cik}/{acc_nodash}/{filename}"
        )

    async def close(self) -> None:
        await self._http.aclose()
