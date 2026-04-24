from __future__ import annotations

import base64
import json
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import EdgarClient
from .models import (
    Company,
    ConceptIndex,
    Document,
    Filing,
    FilingDetail,
    FilingRef,
    FinancialSeries,
    InsiderSummary,
    InsiderTransactionPage,
    Insider,
    Section,
    SectionDiff,
    Transaction,
)
from .parsers.diff import diff_sections
from .parsers.form4 import parse_form4_xml
from .parsers.sections import (
    SUPPORTED_SECTIONS,
    extract_section,
    paginate_section,
)
from .parsers.xbrl import extract_concept_index, extract_timeseries, resolve_concept

mcp = FastMCP("edgar")

_client: EdgarClient | None = None


def _get_client() -> EdgarClient:
    global _client
    if _client is None:
        _client = EdgarClient()
    return _client


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_KIND_ALIASES: dict[str, str] = {
    "annual report": "10-K",
    "quarterly report": "10-Q",
    "current report": "8-K",
    "proxy": "DEF 14A",
    "insider transaction": "4",
    "insider": "4",
}

_SECTION_FORM: dict[str, str] = {
    "risk_factors": "10-K",
    "mda": "10-K",
    "business": "10-K",
    "legal_proceedings": "10-K",
    "properties": "10-K",
    "controls_and_procedures": "10-K",
}

_WINDOW_DAYS: dict[str, int] = {
    "1M": 30,
    "3M": 90,
    "6M": 182,
    "1Y": 365,
}


def _resolve_kind(kind: str) -> str:
    normalized = kind.strip().lower()
    if normalized in _KIND_ALIASES:
        return _KIND_ALIASES[normalized]
    return kind.strip()


def _build_ticker_maps(
    raw: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]], list[dict[str, Any]]]:
    by_ticker: dict[str, dict[str, Any]] = {}
    by_cik: dict[int, dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    for entry in raw.values():
        by_ticker[entry["ticker"].upper()] = entry
        by_cik[int(entry["cik_str"])] = entry
        entries.append(entry)
    return by_ticker, by_cik, entries


async def _resolve_to_cik(query: str) -> tuple[int, str, str]:
    """Resolve a company query to (cik, ticker, name). Raises ValueError."""
    raw = await _get_client().fetch_company_tickers()
    by_ticker, by_cik, entries = _build_ticker_maps(raw)

    stripped = query.strip()

    if stripped.isdigit():
        cik = int(stripped)
        if cik in by_cik:
            e = by_cik[cik]
            return cik, e["ticker"], e["title"]

    upper = stripped.upper()
    if upper in by_ticker:
        e = by_ticker[upper]
        return int(e["cik_str"]), e["ticker"], e["title"]

    lower = stripped.lower()
    matches = [e for e in entries if lower in e["title"].lower()]
    if matches:
        matches.sort(key=lambda e: len(e["title"]))
        e = matches[0]
        return int(e["cik_str"]), e["ticker"], e["title"]

    raise ValueError(f"No company found matching '{query}'")


def _cik_from_accession(accession: str) -> int:
    return int(accession.split("-")[0])


async def _filing_meta(
    accession: str,
) -> tuple[dict[str, Any], int, int, str, str]:
    """Look up a filing in submissions.

    Returns (submissions, row_index, cik, ticker, company_name).
    """
    cik = _cik_from_accession(accession)
    submissions = await _get_client().fetch_submissions(cik)
    recent: dict[str, Any] = submissions.get("filings", {}).get("recent", {})
    accessions: list[str] = recent.get("accessionNumber", [])
    try:
        idx = accessions.index(accession)
    except ValueError as exc:
        raise ValueError(
            f"Filing {accession} not found in recent submissions for CIK {cik}"
        ) from exc
    ticker = ""
    tickers: list[str] = submissions.get("tickers", [])
    if tickers:
        ticker = tickers[0]
    name: str = submissions.get("name", "")
    return submissions, idx, cik, ticker, name


def _infer_doc_type(filename: str, primary_doc: str, form: str) -> str:
    if filename == primary_doc:
        return form
    lower = filename.lower()
    m = re.search(r"exhibit[\s_-]*(\d+)", lower)
    if m:
        return f"EX-{m.group(1)}"
    if lower.endswith((".xsd", ".xml")) and not lower.endswith("-index.html"):
        return "XBRL"
    if lower.endswith((".jpg", ".gif", ".png", ".jpeg")):
        return "GRAPHIC"
    if "index" in lower:
        return "INDEX"
    if re.match(r"^[Rr]\d+\.htm", lower):
        return "XBRL-VIEWER"
    return ""


def _encode_cursor(data: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(data).encode()).decode()


def _decode_cursor(cursor: str) -> dict[str, Any]:
    return json.loads(base64.b64decode(cursor))


def _period_label_from_filing(report_date: str, form: str) -> str:
    if not report_date:
        return ""
    d = date.fromisoformat(report_date)
    if form in ("10-K", "20-F"):
        return f"FY{d.year}"
    month = d.month
    quarter = (month - 1) // 3 + 1
    return f"{d.year}-Q{quarter}"


# ---------------------------------------------------------------------------
# Tool 1: resolve_company
# ---------------------------------------------------------------------------


@mcp.tool()
async def resolve_company(query: str) -> Company:
    """Resolve any reference to a US public company — ticker, name, or CIK — into
    a normalized Company record. Use this when the user gives an ambiguous reference
    and you need to confirm which filer they mean before calling other tools.

    Args:
        query: Ticker symbol ("AAPL"), company name ("Apple"), or CIK number ("320193").

    Returns:
        Company with cik, ticker, name, sic, and sic_description.

    Example return:
        {"cik": 320193, "ticker": "AAPL", "name": "Apple Inc.",
         "sic": "3571", "sic_description": "Electronic Computers"}
    """
    cik, ticker, name = await _resolve_to_cik(query)
    submissions = await _get_client().fetch_submissions(cik)
    return Company(
        cik=cik,
        ticker=ticker,
        name=submissions.get("name", name),
        sic=submissions.get("sic", ""),
        sic_description=submissions.get("sicDescription", ""),
    )


# ---------------------------------------------------------------------------
# Tool 2: find_filings
# ---------------------------------------------------------------------------


@mcp.tool()
async def find_filings(
    company: str,
    kind: str | None = None,
    since: str | None = None,
    limit: int = 20,
) -> list[Filing]:
    """List a company's filings, optionally filtered by form type and date.
    `company` accepts a ticker ("AAPL"), company name ("Apple"), or CIK ("320193").
    `kind` accepts EDGAR form codes ("10-K", "10-Q", "8-K", "DEF 14A", "4") or
    plain-language descriptions ("annual report", "quarterly report", "proxy",
    "insider transaction").

    Args:
        company: Ticker, company name, or CIK.
        kind: Form type filter — EDGAR code or plain-language alias.
        since: ISO date ("2024-01-01"). Only return filings on or after this date.
        limit: Maximum number of filings to return (default 20).

    Returns:
        List of Filing objects with accession, form, filed, period, ticker, name.

    Example return:
        [{"accession": "0000320193-24-000123", "form": "10-K",
          "filed": "2024-11-01", "period": "2024-09-28",
          "ticker": "AAPL", "name": "Apple Inc."}]
    """
    cik, ticker, name = await _resolve_to_cik(company)
    submissions = await _get_client().fetch_submissions(cik)
    company_name: str = submissions.get("name", name)

    recent: dict[str, Any] = submissions.get("filings", {}).get("recent", {})
    accessions: list[str] = recent.get("accessionNumber", [])
    forms: list[str] = recent.get("form", [])
    filing_dates: list[str] = recent.get("filingDate", [])
    report_dates: list[str] = recent.get("reportDate", [])

    form_filter: str | None = None
    if kind is not None:
        form_filter = _resolve_kind(kind)

    since_date: date | None = None
    if since is not None:
        since_date = date.fromisoformat(since)

    results: list[Filing] = []
    for i in range(len(accessions)):
        if form_filter and forms[i] != form_filter:
            continue

        filed = date.fromisoformat(filing_dates[i])
        if since_date and filed < since_date:
            continue

        period_str = report_dates[i] if i < len(report_dates) else ""
        period = date.fromisoformat(period_str) if period_str else filed

        results.append(
            Filing(
                accession=accessions[i],
                form=forms[i],
                filed=filed,
                period=period,
                ticker=ticker,
                name=company_name,
            )
        )
        if len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Tool 3: list_recent_filings
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_recent_filings(
    kind: str,
    since: str | None = None,
    limit: int = 50,
) -> list[Filing]:
    """Cross-company feed of recent filings of a given form type. Not scoped to a
    single company — use for screening workflows like "all 8-Ks filed today."
    `kind` accepts the same values as find_filings.

    Args:
        kind: EDGAR form code ("10-K") or plain-language ("annual report").
        since: ISO date ("2024-01-01"). Only return filings on or after this date.
        limit: Maximum number of filings to return (default 50).

    Returns:
        List of Filing objects from multiple companies.

    Example return:
        [{"accession": "0001318605-24-000198", "form": "8-K",
          "filed": "2024-11-01", "period": "2024-11-01",
          "ticker": "TSLA", "name": "Tesla, Inc."}]
    """
    form = _resolve_kind(kind)
    client = _get_client()

    raw = await client.search_filings(
        forms=form,
        start_date=since,
        limit=limit * 5,
    )

    tickers_raw = await client.fetch_company_tickers()
    _, by_cik, _ = _build_ticker_maps(tickers_raw)

    hits: list[dict[str, Any]] = raw.get("hits", {}).get("hits", [])

    seen: set[str] = set()
    results: list[Filing] = []
    for hit in hits:
        src: dict[str, Any] = hit.get("_source", {})
        accession: str = src.get("adsh", "")
        if not accession or accession in seen:
            continue
        seen.add(accession)

        cik_strs: list[str] = src.get("ciks", [])
        cik_str = cik_strs[0].lstrip("0") if cik_strs else ""
        cik = int(cik_str) if cik_str else 0

        ticker = ""
        entity_name = ""
        if cik in by_cik:
            ticker = by_cik[cik]["ticker"]
            entity_name = by_cik[cik]["title"]

        if not entity_name:
            display_names: list[str] = src.get("display_names", [])
            if display_names:
                full = display_names[0]
                paren_idx = full.find("(")
                entity_name = (
                    full[:paren_idx].strip() if paren_idx > 0 else full.strip()
                )

        filed_str: str = src.get("file_date", "")
        period_str: str = src.get("period_ending", "") or filed_str
        if not filed_str:
            continue

        filed = date.fromisoformat(filed_str)
        period = date.fromisoformat(period_str) if period_str else filed

        results.append(
            Filing(
                accession=accession,
                form=src.get("form", form),
                filed=filed,
                period=period,
                ticker=ticker,
                name=entity_name,
            )
        )
        if len(results) >= limit:
            break

    return results


# ---------------------------------------------------------------------------
# Tool 4: get_filing
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_filing(accession_number: str) -> FilingDetail:
    """Full metadata for a specific filing, including the list of attached documents
    (exhibits, primary document, XBRL instance). Use when you need the filing's
    document index before calling get_section.

    Args:
        accession_number: EDGAR accession number (e.g. "0000320193-24-000123").

    Returns:
        FilingDetail with accession, form, cik, ticker, name, filed, period, documents.

    Example return:
        {"accession": "0000320193-24-000123", "form": "10-K", "cik": 320193,
         "ticker": "AAPL", "name": "Apple Inc.", "filed": "2024-11-01",
         "period": "2024-09-28", "documents": [{"filename": "aapl.htm",
         "type": "10-K", "description": "Annual Report"}]}
    """
    submissions, idx, cik, ticker, name = await _filing_meta(accession_number)
    recent: dict[str, Any] = submissions["filings"]["recent"]

    form: str = recent["form"][idx]
    filed_str: str = recent["filingDate"][idx]
    period_str: str = recent["reportDate"][idx]
    primary_doc: str = recent["primaryDocument"][idx]
    primary_desc: str = recent.get("primaryDocDescription", [""] * (idx + 1))[idx]

    filed = date.fromisoformat(filed_str)
    period = date.fromisoformat(period_str) if period_str else filed

    index_data = await _get_client().fetch_filing_index(cik, accession_number)
    items: list[dict[str, Any]] = index_data.get("directory", {}).get("item", [])

    documents: list[Document] = []
    for item in items:
        fn: str = item["name"]
        if fn.endswith((".txt",)) and "-index" not in fn:
            continue
        if "index" in fn.lower():
            continue
        doc_type = _infer_doc_type(fn, primary_doc, form)
        if not doc_type or doc_type in ("XBRL", "XBRL-VIEWER", "INDEX", "META"):
            continue
        desc = primary_desc if fn == primary_doc else ""
        documents.append(Document(filename=fn, type=doc_type, description=desc))

    return FilingDetail(
        accession=accession_number,
        form=form,
        cik=cik,
        ticker=ticker,
        name=name,
        filed=filed,
        period=period,
        documents=documents,
    )


# ---------------------------------------------------------------------------
# Tool 5: get_section
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_section(
    accession_number: str,
    section: str,
    cursor: str | None = None,
) -> Section:
    """Extract a specific semantic section from a filing as clean markdown.
    Supported sections: risk_factors, mda, business, legal_proceedings,
    properties, controls_and_procedures.

    Args:
        accession_number: EDGAR accession number.
        section: Section key (e.g. "risk_factors", "mda").
        cursor: Pagination cursor from a previous call's next_cursor.

    Returns:
        Section with title, markdown, word_count, source_url, next_cursor.

    Example return:
        {"title": "Item 1A. Risk Factors",
         "markdown": "The Company's business, reputation...",
         "word_count": 12743, "source_url": "https://...", "next_cursor": null}
    """
    if section not in SUPPORTED_SECTIONS:
        raise ValueError(
            f"Unknown section '{section}'. "
            f"Supported: {', '.join(SUPPORTED_SECTIONS)}"
        )

    submissions, idx, cik, _ticker, _name = await _filing_meta(accession_number)
    recent: dict[str, Any] = submissions["filings"]["recent"]
    primary_doc: str = recent["primaryDocument"][idx]

    client = _get_client()
    source_url = client.filing_document_url(cik, accession_number, primary_doc)

    html = await client.fetch_filing_document(cik, accession_number, primary_doc)
    title, body = extract_section(html, section)
    chunks = paginate_section(body)

    page = 0
    if cursor is not None:
        page = _decode_cursor(cursor).get("p", 0)

    if page >= len(chunks):
        raise ValueError(f"Cursor page {page} out of range (total {len(chunks)})")

    chunk = chunks[page]
    word_count = len(chunk.split())
    next_cursor = _encode_cursor({"p": page + 1}) if page + 1 < len(chunks) else None

    return Section(
        title=title,
        markdown=chunk,
        word_count=word_count,
        source_url=source_url,
        next_cursor=next_cursor,
    )


# ---------------------------------------------------------------------------
# Tool 6: get_financials
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_financials(
    ticker: str,
    concept: str,
    periods: int = 8,
) -> FinancialSeries:
    """Time series for a specific XBRL concept, deduplicated across filings and
    amendments. `concept` accepts common short names ("Revenues", "NetIncomeLoss",
    "Assets") — the tool resolves them to fully qualified US-GAAP tags. To discover
    available concepts for a filer, call list_concepts first.

    Args:
        ticker: Stock ticker symbol.
        concept: XBRL concept name or common short name.
        periods: Number of most-recent periods to return (default 8).

    Returns:
        FinancialSeries with concept, unit, and list of Observation.

    Example return:
        {"concept": "us-gaap:Revenues", "unit": "USD",
         "observations": [{"period": "2024-Q4", "end_date": "2024-09-28",
         "value": 94930000000, "form": "10-K"}]}
    """
    cik, _tk, _name = await _resolve_to_cik(ticker)
    facts_data = await _get_client().fetch_xbrl_companyfacts(cik)
    facts: dict[str, Any] = facts_data.get("facts", {})

    taxonomy, concept_name, concept_data = resolve_concept(facts, concept)
    unit_name, observations = extract_timeseries(concept_data, periods)

    return FinancialSeries(
        concept=f"{taxonomy}:{concept_name}",
        unit=unit_name,
        observations=observations,
    )


# ---------------------------------------------------------------------------
# Tool 7: list_concepts
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_concepts(ticker: str) -> ConceptIndex:
    """All XBRL concepts a filer has reported, grouped by taxonomy. Use when the
    user asks for a metric and you're not sure which concept name to pass to
    get_financials.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        ConceptIndex with ticker and taxonomies mapping.

    Example return:
        {"ticker": "AAPL", "taxonomies": {"us-gaap": [
         {"name": "Revenues", "label": "Revenue", "units": ["USD"]}]}}
    """
    cik, resolved_ticker, _name = await _resolve_to_cik(ticker)
    facts_data = await _get_client().fetch_xbrl_companyfacts(cik)
    facts: dict[str, Any] = facts_data.get("facts", {})
    taxonomies = extract_concept_index(facts)

    return ConceptIndex(ticker=resolved_ticker, taxonomies=taxonomies)


# ---------------------------------------------------------------------------
# Tool 8: insider_activity
# ---------------------------------------------------------------------------


@mcp.tool()
async def insider_activity(
    ticker: str,
    window: str = "6M",
) -> InsiderSummary:
    """Aggregated Form 4 transactions over a rolling window. Returns net buy/sell
    by named insider with aggregate value. Use when the user asks a high-level
    question about insider behavior.

    Args:
        ticker: Stock ticker symbol.
        window: Rolling window — "1M", "3M", "6M", or "1Y" (default "6M").

    Returns:
        InsiderSummary with window dates, per-insider aggregates, and totals.

    Example return:
        {"window_start": "2025-10-23", "window_end": "2026-04-23",
         "insiders": [{"name": "Cook, Timothy D.", "role": "CEO",
         "net_shares": -500000, "net_value": -145000000}],
         "total_insider_buying": 0, "total_insider_selling": -145000000}
    """
    days = _WINDOW_DAYS.get(window)
    if days is None:
        raise ValueError(f"Invalid window '{window}'. Use 1M, 3M, 6M, or 1Y.")

    today = date.today()
    window_start = today - timedelta(days=days)

    cik, _tk, _name = await _resolve_to_cik(ticker)
    submissions = await _get_client().fetch_submissions(cik)
    recent: dict[str, Any] = submissions.get("filings", {}).get("recent", {})

    form4_accessions = _collect_form4_accessions(
        recent, window_start, limit=100
    )

    per_insider: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"role": "", "shares": 0, "value": 0.0}
    )

    client = _get_client()
    for acc in form4_accessions:
        xml = await client.fetch_filing_document(cik, acc, "form4.xml")
        insider_name, role, transactions = parse_form4_xml(xml)
        for tx in transactions:
            bucket = per_insider[tx.insider]
            bucket["role"] = tx.role or bucket["role"]
            bucket["shares"] += tx.shares
            bucket["value"] += tx.value

    insiders: list[Insider] = []
    total_buying = 0.0
    total_selling = 0.0
    for ins_name, agg in sorted(per_insider.items(), key=lambda x: x[1]["value"]):
        net_val = agg["value"]
        insiders.append(
            Insider(
                name=ins_name,
                role=agg["role"],
                net_shares=agg["shares"],
                net_value=net_val,
            )
        )
        if net_val > 0:
            total_buying += net_val
        else:
            total_selling += net_val

    return InsiderSummary(
        window_start=window_start,
        window_end=today,
        insiders=insiders,
        total_insider_buying=total_buying,
        total_insider_selling=total_selling,
    )


# ---------------------------------------------------------------------------
# Tool 9: insider_transactions
# ---------------------------------------------------------------------------


@mcp.tool()
async def insider_transactions(
    ticker: str,
    window: str = "6M",
    cursor: str | None = None,
) -> InsiderTransactionPage:
    """Individual Form 4 transactions over a rolling window. Use when the user asks
    about specific trades, option exercises, or 10b5-1 plan activity. Paginated —
    pass next_cursor to retrieve more.

    Args:
        ticker: Stock ticker symbol.
        window: Rolling window — "1M", "3M", "6M", or "1Y" (default "6M").
        cursor: Pagination cursor from a previous call's next_cursor.

    Returns:
        InsiderTransactionPage with transactions list and next_cursor.

    Example return:
        {"transactions": [{"insider": "Cook, Timothy D.", "role": "CEO",
         "date": "2026-03-15", "type": "S-Sale", "shares": -100000,
         "price": 245.50, "value": -24550000}], "next_cursor": null}
    """
    days = _WINDOW_DAYS.get(window)
    if days is None:
        raise ValueError(f"Invalid window '{window}'. Use 1M, 3M, 6M, or 1Y.")

    today = date.today()
    window_start = today - timedelta(days=days)

    cik, _tk, _name = await _resolve_to_cik(ticker)
    submissions = await _get_client().fetch_submissions(cik)
    recent: dict[str, Any] = submissions.get("filings", {}).get("recent", {})

    form4_accessions = _collect_form4_accessions(recent, window_start, limit=200)

    page_size = 10
    offset = 0
    if cursor is not None:
        offset = _decode_cursor(cursor).get("o", 0)

    page_accessions = form4_accessions[offset : offset + page_size]

    all_tx: list[Transaction] = []
    client = _get_client()
    for acc in page_accessions:
        xml = await client.fetch_filing_document(cik, acc, "form4.xml")
        _ins, _role, transactions = parse_form4_xml(xml)
        all_tx.extend(transactions)

    has_more = offset + page_size < len(form4_accessions)
    next_cursor = (
        _encode_cursor({"o": offset + page_size}) if has_more else None
    )

    return InsiderTransactionPage(
        transactions=all_tx,
        next_cursor=next_cursor,
    )


def _collect_form4_accessions(
    recent: dict[str, Any], window_start: date, limit: int
) -> list[str]:
    accessions: list[str] = recent.get("accessionNumber", [])
    forms: list[str] = recent.get("form", [])
    filing_dates: list[str] = recent.get("filingDate", [])

    result: list[str] = []
    for i in range(len(accessions)):
        if forms[i] != "4":
            continue
        filed_str = filing_dates[i]
        if not filed_str:
            continue
        filed = date.fromisoformat(filed_str)
        if filed < window_start:
            break
        result.append(accessions[i])
        if len(result) >= limit:
            break
    return result


# ---------------------------------------------------------------------------
# Tool 10: diff_filings
# ---------------------------------------------------------------------------


@mcp.tool()
async def diff_filings(
    ticker: str,
    section: str,
    periods: int = 2,
) -> SectionDiff:
    """Structured diff of a semantic section between two filings. Fetches the last
    `periods` filings of the form type implied by `section`, then diffs the newest
    against the oldest. Returns added, removed, and modified content at the paragraph
    level.

    With periods=2, you compare consecutive filings. With periods=3, you compare the
    most recent against the one from two filings back.

    Args:
        ticker: Stock ticker symbol.
        section: Section key (e.g. "risk_factors", "mda").
        periods: How many filings back to compare (default 2).

    Returns:
        SectionDiff with current/previous FilingRef and paragraph-level changes.

    Example return:
        {"current": {"accession": "...", "form": "10-K", "period": "FY2025"},
         "previous": {"accession": "...", "form": "10-K", "period": "FY2024"},
         "added": [{"text": "New risk paragraph..."}],
         "removed": [{"text": "Old risk paragraph..."}],
         "modified": [{"before": "...", "after": "...", "similarity": 0.72}]}
    """
    if section not in SUPPORTED_SECTIONS:
        raise ValueError(
            f"Unknown section '{section}'. "
            f"Supported: {', '.join(SUPPORTED_SECTIONS)}"
        )

    form_type = _SECTION_FORM[section]
    filings = await find_filings(ticker, kind=form_type, limit=periods)

    if len(filings) < 2:
        raise ValueError(
            f"Need at least 2 '{form_type}' filings to diff, found {len(filings)}"
        )

    current_filing = filings[0]
    previous_filing = filings[-1]

    client = _get_client()

    current_cik = _cik_from_accession(current_filing.accession)
    current_sub, current_idx, *_ = await _filing_meta(current_filing.accession)
    current_pdoc: str = current_sub["filings"]["recent"]["primaryDocument"][current_idx]
    current_html = await client.fetch_filing_document(
        current_cik, current_filing.accession, current_pdoc
    )
    _, current_text = extract_section(current_html, section)

    previous_cik = _cik_from_accession(previous_filing.accession)
    previous_sub, previous_idx, *_ = await _filing_meta(previous_filing.accession)
    previous_pdoc: str = previous_sub["filings"]["recent"]["primaryDocument"][previous_idx]
    previous_html = await client.fetch_filing_document(
        previous_cik, previous_filing.accession, previous_pdoc
    )
    _, previous_text = extract_section(previous_html, section)

    added, removed, modified = diff_sections(current_text, previous_text)

    current_period_str: str = current_sub["filings"]["recent"]["reportDate"][current_idx]
    previous_period_str: str = previous_sub["filings"]["recent"]["reportDate"][previous_idx]

    return SectionDiff(
        current=FilingRef(
            accession=current_filing.accession,
            form=form_type,
            period=_period_label_from_filing(current_period_str, form_type),
        ),
        previous=FilingRef(
            accession=previous_filing.accession,
            form=form_type,
            period=_period_label_from_filing(previous_period_str, form_type),
        ),
        added=added,
        removed=removed,
        modified=modified,
    )
