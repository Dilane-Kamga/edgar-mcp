"""Regression tests for section extraction using real EDGAR fixtures.

These tests use captured 10-K HTML files to verify the parser handles
real-world formatting: TOC entries, forward-looking cross-references,
embedded page markers, and table-split headings.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from edgar_mcp.parsers.diff import diff_sections
from edgar_mcp.parsers.sections import extract_section

FIXTURES = Path(__file__).parent / "fixtures"


def _require_fixture(name: str) -> str:
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"Fixture {name} not found — run scripts/test_sections_live.py to capture")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Apple risk_factors
# ---------------------------------------------------------------------------


class TestAppleFY2025RiskFactors:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.html = _require_fixture("apple_20250927_10k.html")
        self.title, self.body = extract_section(self.html, "risk_factors")
        self.wc = len(self.body.split())

    def test_word_count_above_threshold(self) -> None:
        assert self.wc > 8000, (
            f"Expected >8k words, got {self.wc}. Likely extracting wrong range."
        )

    def test_not_forward_looking_boilerplate(self) -> None:
        first_200 = self.body[:200].lower()
        assert "forward-looking" not in first_200
        assert "safe harbor" not in first_200

    def test_not_table_of_contents(self) -> None:
        first_100 = self.body[:100].lower()
        assert "table of contents" not in first_100

    def test_contains_representative_risk_language(self) -> None:
        lower = self.body.lower()
        assert "macroeconomic" in lower
        assert "supply" in lower
        assert "competition" in lower

    def test_ends_before_next_item(self) -> None:
        last_500 = self.body[-500:].lower()
        assert "unresolved staff comments" not in last_500
        assert "item 2" not in last_500 or "properties" not in last_500


class TestAppleFY2024RiskFactors:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.html = _require_fixture("apple_20240928_10k.html")
        self.title, self.body = extract_section(self.html, "risk_factors")
        self.wc = len(self.body.split())

    def test_word_count_above_threshold(self) -> None:
        assert self.wc > 8000

    def test_not_forward_looking_boilerplate(self) -> None:
        first_200 = self.body[:200].lower()
        assert "forward-looking" not in first_200


# ---------------------------------------------------------------------------
# NVIDIA risk_factors
# ---------------------------------------------------------------------------


class TestNvidiaFY2026RiskFactors:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.html = _require_fixture("nvidia_20260125_10k.html")
        self.title, self.body = extract_section(self.html, "risk_factors")
        self.wc = len(self.body.split())

    def test_word_count_above_threshold(self) -> None:
        assert self.wc > 10000, (
            f"Expected >10k words for NVIDIA, got {self.wc}"
        )

    def test_not_forward_looking_boilerplate(self) -> None:
        first_200 = self.body[:200].lower()
        assert "forward-looking" not in first_200

    def test_contains_export_control_language(self) -> None:
        lower = self.body.lower()
        assert "export" in lower
        assert "china" in lower


class TestNvidiaFY2025RiskFactors:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.html = _require_fixture("nvidia_20250126_10k.html")
        self.title, self.body = extract_section(self.html, "risk_factors")
        self.wc = len(self.body.split())

    def test_word_count_above_threshold(self) -> None:
        assert self.wc > 10000


# ---------------------------------------------------------------------------
# NVIDIA diff regression
# ---------------------------------------------------------------------------


class TestNvidiaDiffRiskFactors:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        current_html = _require_fixture("nvidia_20260125_10k.html")
        previous_html = _require_fixture("nvidia_20250126_10k.html")
        _, self.current_text = extract_section(current_html, "risk_factors")
        _, self.previous_text = extract_section(previous_html, "risk_factors")
        self.added, self.removed, self.modified = diff_sections(
            self.current_text, self.previous_text
        )

    def test_diff_is_not_empty(self) -> None:
        total = len(self.added) + len(self.removed) + len(self.modified)
        assert total > 0, (
            "Diff returned zero changes — suspect identical extraction on both sides"
        )

    def test_diff_contains_export_control_additions(self) -> None:
        all_new = " ".join(p.text.lower() for p in self.added)
        all_new += " " + " ".join(m.after.lower() for m in self.modified)
        assert "export" in all_new or "china" in all_new, (
            "Expected added/modified content about export controls. "
            "Either extraction is broken or the tokenizer is over-normalizing."
        )


# ---------------------------------------------------------------------------
# Apple diff regression
# ---------------------------------------------------------------------------


class TestAppleDiffRiskFactors:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        current_html = _require_fixture("apple_20250927_10k.html")
        previous_html = _require_fixture("apple_20240928_10k.html")
        _, self.current_text = extract_section(current_html, "risk_factors")
        _, self.previous_text = extract_section(previous_html, "risk_factors")
        self.added, self.removed, self.modified = diff_sections(
            self.current_text, self.previous_text
        )

    def test_diff_is_not_empty(self) -> None:
        total = len(self.added) + len(self.removed) + len(self.modified)
        assert total > 0

    def test_sections_are_different_lengths(self) -> None:
        cur_wc = len(self.current_text.split())
        prev_wc = len(self.previous_text.split())
        assert cur_wc != prev_wc, "Both sections have identical word counts"


# ---------------------------------------------------------------------------
# Accenture risk_factors (page-header stress test)
# ---------------------------------------------------------------------------


class TestAccentureFY2025RiskFactors:
    """Accenture 10-K embeds page headers on every page that repeat the
    section heading (e.g. "Item 1A. Risk Factors | 12"), creating ~20
    false-positive matches. This verifies the scorer picks the actual
    section start, not a late page header."""

    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.html = _require_fixture("acn_20250831_10k.html")
        self.title, self.body = extract_section(self.html, "risk_factors")
        self.wc = len(self.body.split())

    def test_word_count_above_threshold(self) -> None:
        assert self.wc > 8000, (
            f"Expected >8k words for Accenture, got {self.wc}. "
            "Likely picked a late page header instead of the section start."
        )

    def test_not_page_header_boilerplate(self) -> None:
        first_100 = self.body[:100].lower()
        assert "table of contents" not in first_100
        assert "accenture" not in first_100 or "form 10-k" not in first_100

    def test_contains_early_risk_language(self) -> None:
        lower = self.body.lower()
        assert "macroeconomic" in lower or "geopolitical" in lower

    def test_contains_late_risk_language(self) -> None:
        lower = self.body.lower()
        assert "irish" in lower or "ireland" in lower

    def test_ends_before_next_item(self) -> None:
        last_500 = self.body[-500:].lower()
        assert "unresolved staff comments" not in last_500
        assert "item 1b" not in last_500
