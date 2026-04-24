"""Test NVIDIA FY2026 vs FY2025 risk factor diff using saved fixtures."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("EDGAR_MCP_CONTACT", "dilanekamga777@gmail.com")

from edgar_mcp.parsers.sections import extract_section  # noqa: E402
from edgar_mcp.parsers.diff import diff_sections  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


def main() -> None:
    current_html = (FIXTURES / "nvidia_20260125_10k.html").read_text(encoding="utf-8")
    previous_html = (FIXTURES / "nvidia_20250126_10k.html").read_text(encoding="utf-8")

    _, current_text = extract_section(current_html, "risk_factors")
    _, previous_text = extract_section(previous_html, "risk_factors")

    print(f"Current (FY2026): {len(current_text.split())} words")
    print(f"Previous (FY2025): {len(previous_text.split())} words")

    added, removed, modified = diff_sections(current_text, previous_text)

    print(f"\nAdded paragraphs: {len(added)}")
    print(f"Removed paragraphs: {len(removed)}")
    print(f"Modified paragraphs: {len(modified)}")

    if added:
        print("\n--- ADDED (first 3) ---")
        for p in added[:3]:
            preview = p.text[:200].replace("\n", " ")
            print(f"  + {preview}...")

    if removed:
        print("\n--- REMOVED (first 3) ---")
        for p in removed[:3]:
            preview = p.text[:200].replace("\n", " ")
            print(f"  - {preview}...")

    if modified:
        print("\n--- MODIFIED (first 3) ---")
        for m in modified[:3]:
            print(f"  ~ similarity={m.similarity:.2f}")
            print(f"    before: {m.before[:150].replace(chr(10), ' ')}...")
            print(f"    after:  {m.after[:150].replace(chr(10), ' ')}...")

    # Key assertions
    added_text = " ".join(p.text.lower() for p in added)
    modified_text = " ".join(m.after.lower() for m in modified)
    all_new_content = added_text + " " + modified_text

    print("\n--- KEY CONTENT CHECKS ---")
    for keyword in ["export", "china", "h20", "h100", "tariff", "compliance"]:
        found = keyword in all_new_content
        print(f"  {'FOUND' if found else 'MISSING'}: '{keyword}' in added/modified content")

    total = len(added) + len(removed) + len(modified)
    assert total > 0, "Diff returned zero changes — suspect identical extraction"
    print(f"\nTOTAL CHANGES: {total} — DIFF IS SUBSTANTIVE")


if __name__ == "__main__":
    main()
