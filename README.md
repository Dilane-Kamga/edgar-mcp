# EDGAR MCP

A Model Context Protocol server for the SEC EDGAR filing system. Built for LLM agents doing primary-source research on US public companies.

EDGAR hosts every public filing since 1993 — 10-Ks, 10-Qs, 8-Ks, proxies, insider transactions — and exposes them through a sprawling unauthenticated API. This MCP wraps that API with tools designed for LLM consumption: typed outputs, semantic section extraction, XBRL normalization, and filing-to-filing diffs.

## Install

Requires Python 3.13+.

```bash
uvx edgar-mcp
```

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "edgar": {
      "command": "uvx",
      "args": ["edgar-mcp"],
      "env": {
        "EDGAR_MCP_CONTACT": "your-name@example.com"
      }
    }
  }
}
```

The `EDGAR_MCP_CONTACT` env var is required — the SEC's fair access policy requires every request identify the caller.

## Example prompts

Once connected, try:

- "What new risks did NVIDIA add to its 10-K this year?"
- "Show me Apple's revenue for the last 8 quarters."
- "Who at Tesla has been selling stock in the last 6 months, and how much?"
- "Diff the risk factors section of MSFT's 2024 and 2023 annual reports."

## Tools

### Company resolution

#### `resolve_company(query: str) -> Company`

Resolve any reference to a US public company — ticker, name, or CIK — into a normalized `Company` record. Use this when the user gives an ambiguous reference and you need to confirm which filer they mean before calling other tools.

```python
resolve_company("apple")
# → Company(
#     cik=320193,
#     ticker="AAPL",
#     name="Apple Inc.",
#     sic="3571",
#     sic_description="Electronic Computers",
# )
```

### Filing discovery

#### `find_filings(company: str, kind: str | None = None, since: date | None = None, limit: int = 20) -> list[Filing]`

List a company's filings, optionally filtered by form type and date. `company` accepts a ticker (`"AAPL"`), company name (`"Apple"`), or CIK (`"320193"`). `kind` accepts EDGAR form codes (`"10-K"`, `"10-Q"`, `"8-K"`, `"DEF 14A"`, `"4"`) or plain-language descriptions (`"annual report"`, `"quarterly report"`, `"proxy"`, `"insider transaction"`).

```python
find_filings("AAPL", kind="annual report", limit=3)
# → [
#     Filing(accession="0000320193-24-000123", form="10-K", filed="2024-11-01", period="2024-09-28", ticker="AAPL", name="Apple Inc."),
#     Filing(accession="0000320193-23-000106", form="10-K", filed="2023-11-03", period="2023-09-30", ticker="AAPL", name="Apple Inc."),
#     Filing(accession="0000320193-22-000108", form="10-K", filed="2022-10-28", period="2022-09-24", ticker="AAPL", name="Apple Inc."),
# ]
```

#### `list_recent_filings(kind: str, since: date | None = None, limit: int = 50) -> list[Filing]`

Cross-company feed of recent filings of a given form type. Not scoped to a single company — use for screening workflows like "all 8-Ks filed today." `kind` accepts the same values as `find_filings`.

```python
list_recent_filings("8-K", limit=3)
# → [
#     Filing(accession="0001318605-24-000198", form="8-K", filed="2024-11-01", period="2024-11-01", ticker="TSLA", name="Tesla, Inc."),
#     Filing(accession="0000320193-24-000125", form="8-K", filed="2024-11-01", period="2024-11-01", ticker="AAPL", name="Apple Inc."),
#     Filing(accession="0001326801-24-000099", form="8-K", filed="2024-10-31", period="2024-10-31", ticker="META", name="Meta Platforms, Inc."),
# ]
```

### Filing retrieval

#### `get_filing(accession_number: str) -> FilingDetail`

Full metadata for a specific filing, including the list of attached documents (exhibits, primary document, XBRL instance). Use when you need the filing's document index before calling `get_section`.

```python
get_filing("0000320193-24-000123")
# → FilingDetail(
#     accession="0000320193-24-000123",
#     form="10-K",
#     cik=320193,
#     ticker="AAPL",
#     name="Apple Inc.",
#     filed="2024-11-01",
#     period="2024-09-28",
#     documents=[
#         Document(filename="aapl-20240928.htm", type="10-K", description="Annual Report"),
#         Document(filename="aapl-20240928_g1.jpg", type="GRAPHIC", description=""),
#         Document(filename="R1.htm", type="EX-21", description="Subsidiaries of the Registrant"),
#     ],
# )
```

#### `get_section(accession_number: str, section: str, cursor: str | None = None) -> Section`

Extract a specific semantic section from a filing as clean markdown. Supported sections:

- `risk_factors` — Item 1A of 10-K, Part II Item 1A of 10-Q
- `mda` — Item 7 of 10-K, Part I Item 2 of 10-Q
- `business` — Item 1 of 10-K
- `legal_proceedings` — Item 3 of 10-K, Part II Item 1 of 10-Q
- `properties` — Item 2 of 10-K
- `controls_and_procedures` — Item 9A of 10-K, Part I Item 4 of 10-Q

```python
get_section("0000320193-24-000123", "risk_factors")
# → Section(
#     title="Item 1A. Risk Factors",
#     markdown="The Company's business, reputation, results of operations...",
#     word_count=12743,
#     source_url="https://www.sec.gov/Archives/edgar/data/320193/...",
#     next_cursor=None,
# )
```

If `word_count > 8000`, the markdown is split and `next_cursor` is set. Pass it back to retrieve the next chunk.

### Financials (XBRL)

#### `get_financials(ticker: str, concept: str, periods: int = 8) -> FinancialSeries`

Time series for a specific XBRL concept, deduplicated across filings and amendments. `concept` accepts common short names (`"Revenues"`, `"NetIncomeLoss"`, `"Assets"`) — the tool resolves them to fully qualified US-GAAP tags. To discover available concepts for a filer, call `list_concepts` first.

```python
get_financials("AAPL", "Revenues", periods=4)
# → FinancialSeries(
#     concept="us-gaap:RevenueFromContractWithCustomersExcludingAssessedTax",
#     unit="USD",
#     observations=[
#         Observation(period="2024-Q4", end_date="2024-09-28", value=94_930_000_000, form="10-K"),
#         Observation(period="2024-Q3", end_date="2024-06-29", value=85_777_000_000, form="10-Q"),
#         Observation(period="2024-Q2", end_date="2024-03-30", value=90_753_000_000, form="10-Q"),
#         Observation(period="2024-Q1", end_date="2023-12-30", value=119_575_000_000, form="10-Q"),
#     ],
# )
```

#### `list_concepts(ticker: str) -> ConceptIndex`

All XBRL concepts a filer has reported, grouped by taxonomy. Use when the user asks for a metric and you're not sure which concept name to pass to `get_financials`.

```python
list_concepts("AAPL")
# → ConceptIndex(
#     ticker="AAPL",
#     taxonomies={
#         "us-gaap": [
#             Concept(name="Revenues", label="Revenue", units=["USD"]),
#             Concept(name="NetIncomeLoss", label="Net Income (Loss)", units=["USD"]),
#             Concept(name="Assets", label="Total Assets", units=["USD"]),
#             Concept(name="EarningsPerShareBasic", label="Earnings Per Share, Basic", units=["USD/shares"]),
#             ...
#         ],
#         "dei": [
#             Concept(name="EntityCommonStockSharesOutstanding", label="Shares Outstanding", units=["shares"]),
#             ...
#         ],
#     },
# )
```

### Insider activity

#### `insider_activity(ticker: str, window: str = "6M") -> InsiderSummary`

Aggregated Form 4 transactions over a rolling window. `window` accepts `"1M"`, `"3M"`, `"6M"`, or `"1Y"`. Returns net buy/sell by named insider with aggregate value. Use when the user asks a high-level question about insider behavior.

```python
insider_activity("TSLA", window="6M")
# → InsiderSummary(
#     window_start="2025-10-23",
#     window_end="2026-04-23",
#     insiders=[
#         Insider(name="Musk, Elon", role="CEO", net_shares=-500_000, net_value=-145_000_000),
#         Insider(name="Taneja, Vaibhav", role="CFO", net_shares=-12_000, net_value=-3_480_000),
#     ],
#     total_insider_buying=0,
#     total_insider_selling=-148_480_000,
# )
```

#### `insider_transactions(ticker: str, window: str = "6M", cursor: str | None = None) -> InsiderTransactionPage`

Individual Form 4 transactions over a rolling window. Use when the user asks about specific trades, option exercises, or 10b5-1 plan activity. Paginated — pass `next_cursor` to retrieve more.

```python
insider_transactions("TSLA", window="3M")
# → InsiderTransactionPage(
#     transactions=[
#         Transaction(
#             insider="Musk, Elon",
#             role="CEO",
#             date="2026-03-15",
#             type="S-Sale",
#             shares=-100_000,
#             price=245.50,
#             value=-24_550_000,
#         ),
#         Transaction(
#             insider="Taneja, Vaibhav",
#             role="CFO",
#             date="2026-02-28",
#             type="M-Exempt",
#             shares=5_000,
#             price=0.00,
#             value=0,
#         ),
#     ],
#     next_cursor="eyJ0IjoiMjAyNi0wMi0xNSJ9",
# )
```

### Diffing

#### `diff_filings(ticker: str, section: str, periods: int = 2) -> SectionDiff`

Structured diff of a semantic section between two filings. Fetches the last `periods` filings of the form type implied by `section` (e.g., `risk_factors` → 10-K), then diffs the newest against the oldest. Returns added, removed, and modified content at the paragraph level.

With `periods=2`, you compare consecutive filings. With `periods=3`, you compare the most recent against the one from two filings back — useful for seeing drift over a longer horizon.

```python
diff_filings("NVDA", "risk_factors", periods=2)
# → SectionDiff(
#     current=FilingRef(accession="...", form="10-K", period="FY2025"),
#     previous=FilingRef(accession="...", form="10-K", period="FY2024"),
#     added=[Paragraph(text="The Company's reliance on third-party data center capacity..."), ...],
#     removed=[Paragraph(text="The Company is subject to fluctuations in cryptocurrency mining demand..."), ...],
#     modified=[Modification(before="...", after="...", similarity=0.72), ...],
# )
```

## Rate limiting and compliance

This server respects the SEC's fair access policy:

- Every request includes a `User-Agent` identifying the MCP version and the contact email from `EDGAR_MCP_CONTACT`.
- Hard limit of 10 requests/second, enforced by a token bucket in the client.
- Automatic backoff on 429 and 5xx responses.
- Filings are cached locally on disk. Cache location: `~/.cache/edgar-mcp/`.

## Development

```bash
git clone https://github.com/YOUR-USERNAME/edgar-mcp
cd edgar-mcp
uv sync
uv run pytest
```

See `CLAUDE.md` for architectural conventions if you're contributing.

## License

MIT.
