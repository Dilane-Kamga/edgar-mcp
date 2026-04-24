from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from edgar_mcp.models import (
    Company,
    ConceptIndex,
    Filing,
    FilingDetail,
    FinancialSeries,
    InsiderSummary,
    InsiderTransactionPage,
    Section,
    SectionDiff,
)
from edgar_mcp.server import (
    diff_filings,
    find_filings,
    get_filing,
    get_financials,
    get_section,
    insider_activity,
    insider_transactions,
    list_concepts,
    list_recent_filings,
    resolve_company,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_client() -> None:
    import edgar_mcp.server as srv

    srv._client = None


@pytest.fixture()
def mock_client() -> AsyncMock:
    client = AsyncMock()
    client.fetch_company_tickers.return_value = _load("company_tickers.json")
    client.fetch_submissions.return_value = _load("submissions_CIK0000320193.json")
    client.search_filings.return_value = _load("efts_8K_recent.json")
    client.fetch_filing_index.return_value = _load("filing_index_320193.json")
    client.fetch_xbrl_companyfacts.return_value = _load(
        "xbrl_companyfacts_320193.json"
    )
    client.filing_document_url = Mock(
        return_value="https://www.sec.gov/Archives/edgar/data/320193/000032019325000059/aapl-20250927.htm"
    )
    with patch("edgar_mcp.server._get_client", return_value=client):
        yield client


# -- resolve_company --


@pytest.mark.asyncio
async def test_resolve_company_by_ticker(mock_client: AsyncMock) -> None:
    result = await resolve_company("AAPL")
    assert isinstance(result, Company)
    assert result.cik == 320193
    assert result.ticker == "AAPL"
    assert result.name == "Apple Inc."
    assert result.sic == "3571"
    assert result.sic_description == "Electronic Computers"


@pytest.mark.asyncio
async def test_resolve_company_by_name(mock_client: AsyncMock) -> None:
    result = await resolve_company("apple")
    assert isinstance(result, Company)
    assert result.ticker == "AAPL"


@pytest.mark.asyncio
async def test_resolve_company_by_cik(mock_client: AsyncMock) -> None:
    result = await resolve_company("320193")
    assert isinstance(result, Company)
    assert result.ticker == "AAPL"
    assert result.cik == 320193


@pytest.mark.asyncio
async def test_resolve_company_not_found(mock_client: AsyncMock) -> None:
    with pytest.raises(ValueError, match="No company found"):
        await resolve_company("xyznonexistent12345")


# -- find_filings --


@pytest.mark.asyncio
async def test_find_filings_annual_report(mock_client: AsyncMock) -> None:
    result = await find_filings("AAPL", kind="annual report", limit=3)
    assert isinstance(result, list)
    assert len(result) <= 3
    assert len(result) > 0
    for f in result:
        assert isinstance(f, Filing)
        assert f.form == "10-K"
        assert f.ticker == "AAPL"
        assert f.name == "Apple Inc."


@pytest.mark.asyncio
async def test_find_filings_with_since(mock_client: AsyncMock) -> None:
    result = await find_filings("AAPL", since="2025-01-01")
    for f in result:
        assert f.filed >= date(2025, 1, 1)


@pytest.mark.asyncio
async def test_find_filings_limit(mock_client: AsyncMock) -> None:
    result = await find_filings("AAPL", limit=5)
    assert len(result) <= 5
    for f in result:
        assert f.ticker == "AAPL"


@pytest.mark.asyncio
async def test_find_filings_kind_plain_language(mock_client: AsyncMock) -> None:
    result = await find_filings("AAPL", kind="quarterly report", limit=5)
    for f in result:
        assert f.form == "10-Q"


@pytest.mark.asyncio
async def test_find_filings_kind_form_code(mock_client: AsyncMock) -> None:
    result = await find_filings("AAPL", kind="10-K", limit=3)
    for f in result:
        assert f.form == "10-K"


# -- list_recent_filings --


@pytest.mark.asyncio
async def test_list_recent_filings_basic(mock_client: AsyncMock) -> None:
    result = await list_recent_filings("8-K", limit=5)
    assert isinstance(result, list)
    assert len(result) <= 5
    assert len(result) > 0
    for f in result:
        assert isinstance(f, Filing)
        assert f.form == "8-K"


@pytest.mark.asyncio
async def test_list_recent_filings_deduplicates(mock_client: AsyncMock) -> None:
    result = await list_recent_filings("8-K", limit=50)
    accessions = [f.accession for f in result]
    assert len(accessions) == len(set(accessions))


@pytest.mark.asyncio
async def test_list_recent_filings_plain_language(mock_client: AsyncMock) -> None:
    await list_recent_filings("current report", limit=5)
    mock_client.search_filings.assert_called_once()
    call_args = mock_client.search_filings.call_args
    assert call_args.kwargs["forms"] == "8-K"


# -- get_filing --


@pytest.mark.asyncio
async def test_get_filing_basic(mock_client: AsyncMock) -> None:
    result = await get_filing("0000320193-25-000079")
    assert isinstance(result, FilingDetail)
    assert result.accession == "0000320193-25-000079"
    assert result.form == "10-K"
    assert result.cik == 320193
    assert result.ticker == "AAPL"
    assert result.name == "Apple Inc."
    assert result.filed == date(2025, 10, 31)
    assert result.period == date(2025, 9, 27)


@pytest.mark.asyncio
async def test_get_filing_has_documents(mock_client: AsyncMock) -> None:
    result = await get_filing("0000320193-25-000079")
    assert len(result.documents) > 0
    primary = [d for d in result.documents if d.type == "10-K"]
    assert len(primary) == 1
    assert primary[0].filename == "aapl-20250927.htm"


@pytest.mark.asyncio
async def test_get_filing_filters_xbrl_and_index(mock_client: AsyncMock) -> None:
    result = await get_filing("0000320193-25-000079")
    types = [d.type for d in result.documents]
    assert "XBRL" not in types
    assert "XBRL-VIEWER" not in types
    assert "INDEX" not in types


@pytest.mark.asyncio
async def test_get_filing_not_found(mock_client: AsyncMock) -> None:
    with pytest.raises(ValueError, match="not found"):
        await get_filing("0000320193-99-999999")


# -- get_section --


@pytest.mark.asyncio
async def test_get_section_risk_factors(mock_client: AsyncMock) -> None:
    html = _load_text("section_risk_factors_current.html")
    mock_client.fetch_filing_document.return_value = html
    result = await get_section("0000320193-25-000079", "risk_factors")
    assert isinstance(result, Section)
    assert "Risk Factors" in result.title
    assert result.word_count > 0
    assert "competitive" in result.markdown.lower()
    assert result.source_url.startswith("https://")


@pytest.mark.asyncio
async def test_get_section_pagination(mock_client: AsyncMock) -> None:
    long_content = "<html><body>\n"
    long_content += "<h1>Item 1A. Risk Factors</h1>\n"
    for i in range(200):
        long_content += f"<p>{'Risk paragraph number ' + str(i) + '. ' + 'word ' * 80}</p>\n"
    long_content += "<h1>Item 2. Properties</h1>\n"
    long_content += "<p>HQ in Cupertino.</p>\n</body></html>"
    mock_client.fetch_filing_document.return_value = long_content
    result = await get_section("0000320193-25-000079", "risk_factors")
    assert result.next_cursor is not None
    result2 = await get_section(
        "0000320193-25-000079", "risk_factors", cursor=result.next_cursor
    )
    assert isinstance(result2, Section)
    assert result2.markdown != result.markdown


@pytest.mark.asyncio
async def test_get_section_unknown_section(mock_client: AsyncMock) -> None:
    with pytest.raises(ValueError, match="Unknown section"):
        await get_section("0000320193-25-000079", "nonexistent_section")


# -- get_financials --


@pytest.mark.asyncio
async def test_get_financials_revenues(mock_client: AsyncMock) -> None:
    result = await get_financials("AAPL", "Revenues")
    assert isinstance(result, FinancialSeries)
    assert result.concept == "us-gaap:Revenues"
    assert result.unit == "USD"
    assert len(result.observations) > 0
    newest = result.observations[0]
    assert newest.value == 391035000000
    assert newest.form == "10-K"


@pytest.mark.asyncio
async def test_get_financials_periods_limit(mock_client: AsyncMock) -> None:
    result = await get_financials("AAPL", "Revenues", periods=3)
    assert len(result.observations) <= 3
    ends = [o.end_date for o in result.observations]
    assert ends == sorted(ends, reverse=True)


@pytest.mark.asyncio
async def test_get_financials_case_insensitive(mock_client: AsyncMock) -> None:
    result = await get_financials("AAPL", "revenues")
    assert result.concept == "us-gaap:Revenues"


@pytest.mark.asyncio
async def test_get_financials_not_found(mock_client: AsyncMock) -> None:
    with pytest.raises(ValueError, match="not found"):
        await get_financials("AAPL", "CompletelyFakeConceptXYZ")


# -- list_concepts --


@pytest.mark.asyncio
async def test_list_concepts_basic(mock_client: AsyncMock) -> None:
    result = await list_concepts("AAPL")
    assert isinstance(result, ConceptIndex)
    assert result.ticker == "AAPL"
    assert "us-gaap" in result.taxonomies
    assert "dei" in result.taxonomies
    us_gaap = result.taxonomies["us-gaap"]
    names = [c.name for c in us_gaap]
    assert "Revenues" in names
    assert "NetIncomeLoss" in names
    assert "Assets" in names


@pytest.mark.asyncio
async def test_list_concepts_has_units(mock_client: AsyncMock) -> None:
    result = await list_concepts("AAPL")
    for taxonomy_concepts in result.taxonomies.values():
        for concept in taxonomy_concepts:
            assert len(concept.units) > 0


# -- insider_activity --


@pytest.mark.asyncio
async def test_insider_activity_basic(mock_client: AsyncMock) -> None:
    form4_xml = _load_text("form4_cook.xml")
    mock_client.fetch_filing_document.return_value = form4_xml
    result = await insider_activity("AAPL", window="6M")
    assert isinstance(result, InsiderSummary)
    assert result.window_start < result.window_end
    assert len(result.insiders) > 0
    cook = next((i for i in result.insiders if "Cook" in i.name), None)
    assert cook is not None
    assert cook.net_shares < 0
    assert cook.net_value < 0


@pytest.mark.asyncio
async def test_insider_activity_totals(mock_client: AsyncMock) -> None:
    form4_xml = _load_text("form4_cook.xml")
    mock_client.fetch_filing_document.return_value = form4_xml
    result = await insider_activity("AAPL", window="1Y")
    assert result.total_insider_selling <= 0
    assert result.total_insider_buying >= 0


@pytest.mark.asyncio
async def test_insider_activity_invalid_window(mock_client: AsyncMock) -> None:
    with pytest.raises(ValueError, match="Invalid window"):
        await insider_activity("AAPL", window="2Y")


# -- insider_transactions --


@pytest.mark.asyncio
async def test_insider_transactions_basic(mock_client: AsyncMock) -> None:
    form4_xml = _load_text("form4_cook.xml")
    mock_client.fetch_filing_document.return_value = form4_xml
    result = await insider_transactions("AAPL", window="6M")
    assert isinstance(result, InsiderTransactionPage)
    assert len(result.transactions) > 0
    tx = result.transactions[0]
    assert tx.insider == "Cook Timothy D"
    assert tx.type == "S-Sale"
    assert tx.shares < 0
    assert tx.price > 0


@pytest.mark.asyncio
async def test_insider_transactions_pagination(mock_client: AsyncMock) -> None:
    form4_xml = _load_text("form4_cook.xml")
    mock_client.fetch_filing_document.return_value = form4_xml
    result = await insider_transactions("AAPL", window="1Y")
    if result.next_cursor is not None:
        result2 = await insider_transactions(
            "AAPL", window="1Y", cursor=result.next_cursor
        )
        assert isinstance(result2, InsiderTransactionPage)


@pytest.mark.asyncio
async def test_insider_transactions_invalid_window(mock_client: AsyncMock) -> None:
    with pytest.raises(ValueError, match="Invalid window"):
        await insider_transactions("AAPL", window="5Y")


# -- diff_filings --


@pytest.mark.asyncio
async def test_diff_filings_risk_factors(mock_client: AsyncMock) -> None:
    current_html = _load_text("section_risk_factors_current.html")
    previous_html = _load_text("section_risk_factors_previous.html")
    call_count = 0

    async def _mock_fetch_doc(
        cik: int, accession: str, filename: str
    ) -> str:
        nonlocal call_count
        call_count += 1
        if call_count <= 1:
            return current_html
        return previous_html

    mock_client.fetch_filing_document.side_effect = _mock_fetch_doc
    result = await diff_filings("AAPL", "risk_factors", periods=2)
    assert isinstance(result, SectionDiff)
    assert result.current.form == "10-K"
    assert result.previous.form == "10-K"
    assert result.current.accession != result.previous.accession
    total_changes = len(result.added) + len(result.removed) + len(result.modified)
    assert total_changes > 0


@pytest.mark.asyncio
async def test_diff_filings_has_period_labels(mock_client: AsyncMock) -> None:
    html = _load_text("section_risk_factors_current.html")
    mock_client.fetch_filing_document.return_value = html
    result = await diff_filings("AAPL", "risk_factors", periods=2)
    assert result.current.period.startswith("FY")
    assert result.previous.period.startswith("FY")


@pytest.mark.asyncio
async def test_diff_filings_unknown_section(mock_client: AsyncMock) -> None:
    with pytest.raises(ValueError, match="Unknown section"):
        await diff_filings("AAPL", "nonexistent_section")
