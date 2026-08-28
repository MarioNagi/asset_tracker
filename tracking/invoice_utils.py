"""Helpers for invoice identifiers used across import paths."""


def normalize_invoice_number(value) -> str:
    """
    Canonical form for upsert keys: strip whitespace and uppercase.

    Empty or whitespace-only input returns ''.
    """
    if value is None:
        return ""
    return str(value).strip().upper()
