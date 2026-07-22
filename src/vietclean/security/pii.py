"""Small PII classifiers and masking helpers for logs/reports."""

from __future__ import annotations

import re
from typing import Literal

from ..profiles import normalize_column_name


PIIType = Literal["email", "phone", "account", "identifier", "address", "name"]

_ALIASES: dict[PIIType, set[str]] = {
    "email": {"email", "e_mail", "email_address", "dia_chi_email"},
    "phone": {"phone", "mobile", "telephone", "tel", "sdt", "so_dien_thoai"},
    "account": {"account_number", "so_tai_khoan", "bank_account", "credit_card"},
    "identifier": {"tax_code", "ma_so_thue", "citizen_id", "cccd", "cmnd", "passport"},
    "address": {"address", "dia_chi", "shipping_address", "billing_address"},
    "name": {"name", "full_name", "ho_ten", "customer_name", "ten_khach_hang"},
}


def infer_pii_type(column_name: object) -> PIIType | None:
    """Infer a broad PII class from a column label; never inspect raw values."""

    normalized = normalize_column_name(column_name)
    if not normalized:
        return None
    matches = [kind for kind, aliases in _ALIASES.items() if normalized in aliases]
    return matches[0] if len(matches) == 1 else None


def mask_pii(value: object, kind: PIIType | None = None) -> str:
    """Return a deterministic masked representation safe for diagnostic output."""

    if value is None:
        return "[NULL]"
    text = str(value)
    if not text:
        return "[EMPTY]"
    if kind == "email" or (kind is None and "@" in text):
        local, _, domain = text.partition("@")
        return f"{local[:1]}***@{domain}" if domain else "***"
    if kind in {"phone", "account", "identifier"}:
        digits = re.sub(r"\D", "", text)
        return f"***{digits[-4:]}" if digits else "***"
    if kind in {"address", "name"}:
        return f"{text[:1]}***"
    return "***"
