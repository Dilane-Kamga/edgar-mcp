from __future__ import annotations

from datetime import date
from typing import Any

from ..models import Concept, Observation


def resolve_concept(
    facts: dict[str, Any], query: str
) -> tuple[str, str, dict[str, Any]]:
    """Find a concept in companyfacts by name (exact, case-insensitive, or label).

    Returns (taxonomy_prefix, concept_name, concept_data).
    Raises ValueError if not found.
    """
    for taxonomy, concepts in facts.items():
        if query in concepts:
            return taxonomy, query, concepts[query]

    query_lower = query.lower()
    for taxonomy, concepts in facts.items():
        for name, data in concepts.items():
            if name.lower() == query_lower:
                return taxonomy, name, data

    for taxonomy, concepts in facts.items():
        for name, data in concepts.items():
            label: str = data.get("label", "")
            if query_lower in label.lower() or query_lower in name.lower():
                return taxonomy, name, data

    raise ValueError(
        f"XBRL concept '{query}' not found. "
        "Use list_concepts to discover available concepts."
    )


def _period_label(obs: dict[str, Any]) -> str:
    """Generate a human-readable period label like '2024-Q4' or 'FY2024'."""
    frame: str = obs.get("frame", "")
    if frame:
        if "Q" in frame:
            year = frame.replace("CY", "").split("Q")[0]
            quarter = frame.split("Q")[1].rstrip("I")
            return f"{year}-Q{quarter}"
        return f"FY{frame.replace('CY', '')}"

    fy: int | None = obs.get("fy")
    fp: str = obs.get("fp", "")
    if fy and fp:
        if fp == "FY":
            return f"FY{fy}"
        return f"{fy}-{fp}"

    return obs.get("end", "")


def extract_timeseries(
    concept_data: dict[str, Any], periods: int
) -> tuple[str, list[Observation]]:
    """Extract a deduplicated time series from an XBRL concept.

    Returns (unit_name, observations) sorted newest-first, trimmed to `periods`.
    """
    all_units = concept_data.get("units", {})
    if not all_units:
        return "", []

    unit_name = next(iter(all_units))
    raw_obs: list[dict[str, Any]] = all_units[unit_name]

    seen_periods: dict[str, dict[str, Any]] = {}
    for obs in raw_obs:
        end_str: str = obs.get("end", "")
        if not end_str:
            continue
        period = _period_label(obs)
        existing = seen_periods.get(period)
        if existing is None or obs.get("filed", "") > existing.get("filed", ""):
            seen_periods[period] = obs

    sorted_obs = sorted(
        seen_periods.values(),
        key=lambda o: o.get("end", ""),
        reverse=True,
    )[:periods]

    observations = [
        Observation(
            period=_period_label(o),
            end_date=date.fromisoformat(o["end"]),
            value=float(o.get("val", 0)),
            form=o.get("form", ""),
        )
        for o in sorted_obs
    ]

    return unit_name, observations


def extract_concept_index(
    facts: dict[str, Any],
) -> dict[str, list[Concept]]:
    """Build a taxonomy → concept list mapping from companyfacts."""
    result: dict[str, list[Concept]] = {}
    for taxonomy, concepts in facts.items():
        concept_list: list[Concept] = []
        for name, data in concepts.items():
            units = list(data.get("units", {}).keys())
            if not units:
                continue
            concept_list.append(
                Concept(
                    name=name,
                    label=data.get("label", name),
                    units=units,
                )
            )
        concept_list.sort(key=lambda c: c.name)
        result[taxonomy] = concept_list
    return result
