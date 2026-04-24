from __future__ import annotations

from datetime import date
from typing import Any

import xmltodict  # type: ignore[import-untyped]

from ..models import Transaction

_TX_CODE_LABELS: dict[str, str] = {
    "P": "P-Purchase",
    "S": "S-Sale",
    "M": "M-Exempt",
    "F": "F-Tax",
    "A": "A-Award",
    "G": "G-Gift",
    "J": "J-Other",
    "K": "K-Swap",
    "C": "C-Conversion",
    "D": "D-Return",
    "E": "E-Expire",
    "H": "H-Expire",
    "I": "I-Discretionary",
    "O": "O-OutOfMoney",
    "U": "U-Disposition",
    "W": "W-Acquisition",
    "X": "X-Exercise",
    "Z": "Z-Deposit",
}


def _get_value(node: Any, default: Any = "") -> Any:
    """Extract a <value> from an XML node that may be a dict with 'value' key."""
    if isinstance(node, dict):
        return node.get("value", node.get("#text", default))
    if node is None:
        return default
    return node


def _ensure_list(val: Any) -> list[Any]:
    if val is None:
        return []
    if isinstance(val, list):
        return val
    return [val]


def parse_form4_xml(xml_text: str) -> tuple[str, str, list[Transaction]]:
    """Parse a Form 4 XML document.

    Returns (insider_name, role, transactions).
    """
    doc: dict[str, Any] = xmltodict.parse(xml_text)
    ownership: dict[str, Any] = doc.get("ownershipDocument", {})

    owner: dict[str, Any] = ownership.get("reportingOwner", {})
    if isinstance(owner, list):
        owner = owner[0]
    owner_id: dict[str, Any] = owner.get("reportingOwnerId", {})
    owner_rel: dict[str, Any] = owner.get("reportingOwnerRelationship", {})

    insider_name: str = owner_id.get("rptOwnerName", "")
    role = owner_rel.get("officerTitle", "")
    if not role:
        if owner_rel.get("isDirector") in ("true", "1", True):
            role = "Director"
        elif owner_rel.get("isTenPercentOwner") in ("true", "1", True):
            role = "10% Owner"
        else:
            role = "Insider"

    transactions: list[Transaction] = []

    nd_table = ownership.get("nonDerivativeTable", {})
    for tx in _ensure_list(nd_table.get("nonDerivativeTransaction")):
        parsed = _parse_transaction(tx, insider_name, role)
        if parsed is not None:
            transactions.append(parsed)

    der_table = ownership.get("derivativeTable", {})
    for tx in _ensure_list(der_table.get("derivativeTransaction")):
        parsed = _parse_transaction(tx, insider_name, role)
        if parsed is not None:
            transactions.append(parsed)

    return insider_name, role, transactions


def _parse_transaction(
    tx: dict[str, Any], insider: str, role: str
) -> Transaction | None:
    tx_date_raw = tx.get("transactionDate", {})
    date_str = _get_value(tx_date_raw)
    if not date_str:
        return None

    coding: dict[str, Any] = tx.get("transactionCoding", {})
    code: str = coding.get("transactionCode", "")

    amounts: dict[str, Any] = tx.get("transactionAmounts", {})
    shares_raw = _get_value(amounts.get("transactionShares", {}), "0")
    price_raw = _get_value(amounts.get("transactionPricePerShare", {}), "0")
    ad_code = _get_value(
        amounts.get("transactionAcquiredDisposedCode", {}), "A"
    )

    try:
        shares = int(float(shares_raw))
    except (ValueError, TypeError):
        shares = 0

    try:
        price = float(price_raw)
    except (ValueError, TypeError):
        price = 0.0

    if ad_code == "D":
        shares = -abs(shares)

    value = shares * price
    label = _TX_CODE_LABELS.get(code, code)

    return Transaction(
        insider=insider,
        role=role,
        date=date.fromisoformat(str(date_str)),
        type=label,
        shares=shares,
        price=price,
        value=value,
    )
