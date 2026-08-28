"""Parser for the common MechanicDesk-style tax invoice layout."""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

from .types import InvoiceData, InvoiceItem


_LAYOUT_MARKERS = (
    "tax invoice number:",
    "kms make/model reg no. vin",
    "description qty. unit price amount",
)


def parse_mechanicdesk_invoice(text: str) -> Optional[InvoiceData]:
    """Parse extracted text only when all stable layout markers are present."""
    normalized = " ".join(text.lower().split())
    if not all(marker in normalized for marker in _LAYOUT_MARKERS):
        return None

    invoice_match = re.search(
        r"tax\s+invoice\s+number:\s*([A-Z0-9-]+)", text, re.IGNORECASE
    )
    date_match = re.search(
        r"^\s*date\s*:\s*(\d{1,2}/\d{1,2}/\d{4})\s*$",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not invoice_match or not date_match:
        return None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    vehicle_index = next(
        (index for index, line in enumerate(lines) if "KMs Make/Model Reg No. VIN" in line),
        None,
    )
    if vehicle_index is None or vehicle_index + 1 >= len(lines):
        return None

    vehicle_match = re.match(
        r"^([0-9,]+(?:\.\d+)?)\s+.+?\s+([A-Z0-9]{3,8})"
        r"(?:\s+([A-HJ-NPR-Z0-9]{17}))?$",
        lines[vehicle_index + 1],
        re.IGNORECASE,
    )
    if not vehicle_match:
        return None

    provider = _extract_provider(lines)
    items = _extract_items(lines)

    return InvoiceData(
        invoice_number=invoice_match.group(1).upper(),
        date=datetime.strptime(date_match.group(1), "%d/%m/%Y").date(),
        vehicle_rego=vehicle_match.group(2).upper(),
        vehicle_vin=(vehicle_match.group(3) or "").upper(),
        odometer_reading=int(Decimal(vehicle_match.group(1).replace(",", ""))),
        service_provider=provider,
        subtotal=_extract_amount(text, "subtotal"),
        tax_amount=_extract_amount(text, "gst"),
        total_cost=_extract_amount(text, "total") or Decimal("0.00"),
        items=items,
    )


def _extract_provider(lines):
    bill_to_index = next(
        (index for index, line in enumerate(lines) if line.upper() == "BILL TO:"),
        len(lines),
    )
    provider_lines = [
        line
        for line in lines[:bill_to_index]
        if re.search(
            r"\b(?:AUTOMOTIVE|MECHANICAL|MOTORS?|REPAIRS?|SERVICES?|STEERING|TYRES?)\b",
            line,
            re.IGNORECASE,
        )
        and not re.search(r"\b(?:ABN|LICEN[CS]E|RTA\s+NO)\b", line, re.IGNORECASE)
        and not re.search(
            r"(?:^\d+[\d/ -]*\s|\b(?:AVENUE|DRIVE|HIGHWAY|LANE|ROAD|STREET)\b)",
            line,
            re.IGNORECASE,
        )
    ]
    return " ".join(provider_lines).strip()


def _extract_items(lines):
    try:
        start = next(
            index
            for index, line in enumerate(lines)
            if "Description Qty. Unit Price Amount" in line
        ) + 1
    except StopIteration:
        return []

    items = []
    pattern = re.compile(
        r"^(.*?)\s+(\d+(?:\.\d+)?)\s+\$?([0-9,]+\.\d{2})"
        r"\s+\$?([0-9,]+\.\d{2})$"
    )
    for line in lines[start:]:
        if re.match(r"^(?:sub\s*total|subtotal)\b", line, re.IGNORECASE):
            break
        match = pattern.match(line)
        if not match:
            continue
        description = match.group(1).strip()
        items.append(InvoiceItem(
            description=description,
            quantity=float(match.group(2)),
            unit_cost=Decimal(match.group(3).replace(",", "")),
            item_type="labor" if re.search(r"labou?r", description, re.IGNORECASE) else "parts",
        ))
    return items


def _extract_amount(text, label):
    match = re.search(
        rf"^\s*{label}\s+\$?([0-9,]+\.\d{{2}})\s*$",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
