"""Built-in, dependency-free cleaning profiles for :mod:`vietclean`.

Profiles deliberately describe *what a column probably means*, not how values
must be parsed.  Name matching is accent-insensitive and conservative: an
unknown or ambiguous column returns ``None`` so that callers do not silently
apply a destructive conversion.

The dictionaries returned by :func:`get_profile` are JSON serialisable.  This
makes it possible to start from a built-in profile and overlay a local JSON
configuration while keeping the framework fully offline.
"""

from __future__ import annotations

from copy import deepcopy
import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any


SEMANTIC_TYPES: tuple[str, ...] = (
    "text",
    "identifier",
    "email",
    "phone",
    "integer",
    "number",
    "percentage",
    "currency",
    "date",
    "datetime",
    "boolean",
    "category",
    "address",
)


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Return a recursive, non-mutating merge of two configuration mappings.

    Mapping values are merged recursively.  Scalars and sequences (including
    alias/token lists) in ``override`` replace the corresponding base value.
    Replacing lists is intentional: a JSON override can remove an unsafe token
    or alias without needing special subtraction syntax.
    """

    if not isinstance(base, Mapping):
        raise TypeError("base must be a mapping")
    if not isinstance(override, Mapping):
        raise TypeError("override must be a mapping")

    result: dict[str, Any] = deepcopy(dict(base))
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = deep_merge(current, value)
        else:
            result[key] = deepcopy(value)
    return result


def normalize_column_name(name: object) -> str:
    """Return an accent-insensitive snake-case representation of a column name."""

    if not isinstance(name, str):
        return ""
    # Keep camelCase/PascalCase useful before lower-casing, then fold accents.
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name.strip())
    value = value.replace("Đ", "D").replace("đ", "d")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", "_", value)
    return value.strip("_")


_BASE_DEFAULTS: dict[str, Any] = {
    # This section intentionally mirrors config.BASE_CONFIG so a caller can do
    # deep_merge(BASE_CONFIG, profile["defaults"]) without translating keys.
    "text": {
        "unicode_form": "NFC",
        "repair_mojibake": True,
        "remove_invisible": True,
        "line_breaks": "keep",
        "trim": True,
        "collapse_whitespace": True,
        "normalize_non_breaking_space": True,
    },
    "missing": {
        "tokens": [
            "",
            "-",
            "--",
            "---",
            "?",
            "na",
            "n/a",
            "n.a.",
            "nan",
            "none",
            "null",
            "nil",
            "missing",
            "unknown",
            "not available",
            "#n/a",
            "#na",
            "không có",
            "khong co",
            "chưa có",
            "chua co",
            "không rõ",
            "khong ro",
            "không xác định",
            "khong xac dinh",
            "không có dữ liệu",
            "khong co du lieu",
            "chưa có dữ liệu",
            "chua co du lieu",
        ],
        "case_sensitive": False,
        "accent_sensitive": False,
        "strip_before_match": True,
    },
    "columns": {},
    "auto_types": True,
    "type_conversion": {
        "minimum_success_rate": 0.80,
        "day_first": True,
        "invalid": "keep",
    },
    "column_names": {
        "strip": True,
        "line_breaks": "space",
        "deduplicate": True,
        "lowercase": False,
        "snake_case": False,
    },
    "drop": {"empty_rows": False, "empty_columns": False},
    "duplicates": {
        "enabled": False,
        "subset": None,
        "keep": "first",
    },
}


def _rule(*aliases: str, patterns: Iterable[str] = ()) -> dict[str, list[str]]:
    return {"aliases": list(aliases), "patterns": list(patterns)}


_GENERIC_RULES: dict[str, dict[str, list[str]]] = {
    "text": _rule(
        "name",
        "full_name",
        "ten",
        "ho_ten",
        "description",
        "mo_ta",
        "note",
        "notes",
        "ghi_chu",
        "comment",
        "comments",
        "binh_luan",
        "content",
        "noi_dung",
        patterns=(r"(?:[a-z0-9]+_)*(?:name|description|note|comment|content)",),
    ),
    "identifier": _rule(
        "id",
        "uid",
        "uuid",
        "code",
        "ma",
        "record_id",
        "row_id",
        "ma_ban_ghi",
        "ma_dinh_danh",
        "user_id",
        "customer_id",
        "client_id",
        "product_id",
        "order_id",
        "transaction_id",
        "invoice_id",
        patterns=(
            r"(?:[a-z0-9]+_)+(?:id|uid|uuid)",
            r"(?:record|row|user|customer|client|product|order|transaction|invoice)_code",
        ),
    ),
    "email": _rule(
        "email",
        "e_mail",
        "email_address",
        "dia_chi_email",
        "thu_dien_tu",
        patterns=(r"(?:[a-z0-9]+_)*(?:email|e_mail)(?:_address)?",),
    ),
    "phone": _rule(
        "phone",
        "phone_number",
        "mobile",
        "mobile_number",
        "telephone",
        "tel",
        "so_dien_thoai",
        "dien_thoai",
        "sdt",
        patterns=(r"(?:[a-z0-9]+_)*(?:phone|mobile|telephone|tel|sdt)(?:_number)?",),
    ),
    "integer": _rule(
        "quantity",
        "qty",
        "so_luong",
        "count",
        "so_lan",
        "age",
        "tuoi",
        patterns=(r"(?:[a-z0-9]+_)*(?:quantity|qty|count)",),
    ),
    "number": _rule(
        "score",
        "diem",
        "rating",
        "danh_gia",
        "weight",
        "trong_luong",
        "height",
        "chieu_cao",
        "latitude",
        "longitude",
        patterns=(r"(?:[a-z0-9]+_)*(?:score|rating|weight|height)",),
    ),
    "percentage": _rule(
        "percent",
        "percentage",
        "ty_le",
        "ratio",
        patterns=(r"(?:[a-z0-9]+_)*(?:percent|percentage|rate|ratio)",),
    ),
    "currency": _rule(
        "amount",
        "so_tien",
        "price",
        "gia",
        "unit_price",
        "don_gia",
        "cost",
        "chi_phi",
        "revenue",
        "doanh_thu",
        "total_amount",
        "tong_tien",
        "balance",
        "so_du",
        patterns=(r"(?:[a-z0-9]+_)*(?:amount|price|cost|revenue|balance)",),
    ),
    "date": _rule(
        "date",
        "ngay",
        "birth_date",
        "date_of_birth",
        "ngay_sinh",
        "dob",
        "start_date",
        "ngay_bat_dau",
        "end_date",
        "ngay_ket_thuc",
        "order_date",
        "ngay_dat_hang",
        patterns=(r"(?:[a-z0-9]+_)*date",),
    ),
    "datetime": _rule(
        "datetime",
        "date_time",
        "timestamp",
        "thoi_gian",
        "created_at",
        "updated_at",
        "deleted_at",
        "ngay_gio",
        "ngay_tao",
        "ngay_cap_nhat",
        patterns=(
            r"(?:[a-z0-9]+_)*(?:datetime|timestamp)",
            r"(?:created|updated|deleted|modified|processed)_at",
        ),
    ),
    "boolean": _rule(
        "active",
        "is_active",
        "enabled",
        "is_enabled",
        "valid",
        "is_valid",
        "deleted",
        "is_deleted",
        "verified",
        "is_verified",
        "kich_hoat",
        "hop_le",
        "da_xoa",
        "da_xac_minh",
        patterns=(r"(?:is|has|can|allow|was|were)_[a-z0-9_]+",),
    ),
    "category": _rule(
        "category",
        "danh_muc",
        "type",
        "loai",
        "status",
        "trang_thai",
        "group",
        "nhom",
        "segment",
        "phan_khuc",
        "label",
        "nhan",
        patterns=(r"(?:[a-z0-9]+_)*(?:category|type|status|segment)",),
    ),
    "address": _rule(
        "address",
        "dia_chi",
        "full_address",
        "street_address",
        "mailing_address",
        patterns=(r"(?:[a-z0-9]+_)*(?:address|dia_chi)",),
    ),
}


def _extend_profile(
    name: str,
    description: str,
    *,
    defaults: Mapping[str, Any] | None = None,
    rules: Mapping[str, Mapping[str, Iterable[str]]] | None = None,
) -> dict[str, Any]:
    """Build a profile by extending generic aliases without changing them."""

    profile: dict[str, Any] = {
        "name": name,
        "description": description,
        "defaults": deep_merge(_BASE_DEFAULTS, defaults or {}),
        "column_types": deepcopy(_GENERIC_RULES),
    }
    for semantic_type, additions in (rules or {}).items():
        if semantic_type not in SEMANTIC_TYPES:
            raise ValueError(f"unsupported semantic type: {semantic_type}")
        target = profile["column_types"][semantic_type]
        for field in ("aliases", "patterns"):
            for item in additions.get(field, ()):
                if item not in target[field]:
                    target[field].append(item)
    return profile


_BUILTIN_PROFILES: dict[str, dict[str, Any]] = {
    "generic": _extend_profile(
        "generic",
        "Common Vietnamese and English business data.",
    ),
    "fnb": _extend_profile(
        "fnb",
        "Restaurants, cafes, menus, bookings, and point-of-sale exports.",
        defaults={"domain_rules": {"enabled": True, "mode": "report_only"}},
        rules={
            "text": _rule(
                "ten_mon",
                "ten_do_uong",
                "ten_nha_hang",
                "ten_chi_nhanh",
                "kitchen_note",
                "ghi_chu_bep",
                "item_name",
                "staff",
            ),
            "identifier": _rule(
                "menu_item_id",
                "ma_mon",
                "ma_thuc_don",
                "table_id",
                "ma_ban",
                "branch_id",
                "ma_chi_nhanh",
                "reservation_id",
                "ma_dat_ban",
                "sku",
            ),
            "integer": _rule(
                "item_quantity",
                "so_luong_mon",
                "guest_count",
                "so_khach",
                "table_number",
                "so_ban",
                "quantity",
            ),
            "number": _rule("volume", "dung_tich", "food_rating", "diem_mon"),
            "currency": _rule(
                "menu_price",
                "gia_mon",
                "line_total",
                "thanh_tien",
                "service_charge",
                "phi_dich_vu",
                "tip_amount",
                "tien_tip",
                "unit_price",
                "discount",
                "tax",
                "total",
            ),
            "date": _rule(
                "sale_date",
                "ngay_ban",
                "expiry_date",
                "expiration_date",
                "ngay_het_han",
            ),
            "datetime": _rule(
                "reservation_time",
                "thoi_gian_dat_ban",
                "order_time",
                "thoi_gian_goi_mon",
            ),
            "boolean": _rule(
                "is_available",
                "con_hang",
                "is_vegetarian",
                "mon_chay",
                "is_takeaway",
                "mang_di",
            ),
            "category": _rule(
                "food_category",
                "danh_muc_mon",
                "meal_type",
                "loai_bua_an",
                "order_status",
                "trang_thai_don",
                "branch",
                "store",
                "payment_method",
                "channel",
            ),
            "address": _rule("restaurant_address", "dia_chi_quan", "branch_address"),
        },
    ),
    "finance": _extend_profile(
        "finance",
        "Transactions, accounts, invoices, loans, and accounting exports.",
        defaults={"domain_rules": {"enabled": True, "mode": "report_only"}},
        rules={
            "text": _rule(
                "transaction_description",
                "dien_giai",
                "payment_note",
                "description",
                "counterparty",
            ),
            "identifier": _rule(
                "account_id",
                "account_number",
                "so_tai_khoan",
                "tax_code",
                "ma_so_thue",
                "loan_id",
                "ma_khoan_vay",
                "voucher_number",
                "so_chung_tu",
                "account",
                "account_code",
                "reference",
                "cost_center",
            ),
            "integer": _rule(
                "installment_count",
                "so_ky_tra",
                "term_months",
                "ky_han_thang",
            ),
            "number": _rule(
                "exchange_rate",
                "ty_gia",
            ),
            "percentage": _rule(
                "interest_rate",
                "lai_suat",
                "debt_ratio",
                "ty_le_no",
            ),
            "currency": _rule(
                "debit",
                "debit_amount",
                "phat_sinh_no",
                "credit",
                "credit_amount",
                "phat_sinh_co",
                "opening_balance",
                "so_du_dau_ky",
                "closing_balance",
                "so_du_cuoi_ky",
                "principal_amount",
                "tien_goc",
                "interest_amount",
                "tien_lai",
                "tax_amount",
                "tien_thue",
                "amount",
            ),
            "date": _rule(
                "posting_date",
                "ngay_hach_toan",
                "due_date",
                "ngay_den_han",
                "maturity_date",
                "ngay_dao_han",
                "invoice_date",
                "ngay_hoa_don",
                "transaction_date",
            ),
            "datetime": _rule("transaction_time", "thoi_gian_giao_dich"),
            "boolean": _rule("is_approved", "da_duyet", "is_reconciled", "da_doi_soat"),
            "category": _rule(
                "transaction_type",
                "loai_giao_dich",
                "account_type",
                "loai_tai_khoan",
                "currency_code",
                "ma_tien_te",
                "payment_method",
                "phuong_thuc_thanh_toan",
                "currency",
            ),
        },
    ),
    "ecommerce": _extend_profile(
        "ecommerce",
        "Online orders, products, inventory, customers, and fulfilment.",
        defaults={"domain_rules": {"enabled": True, "mode": "report_only"}},
        rules={
            "text": _rule(
                "product_name",
                "ten_san_pham",
                "product_description",
                "mo_ta_san_pham",
                "review_text",
                "noi_dung_danh_gia",
                "product_name",
            ),
            "identifier": _rule(
                "sku",
                "product_sku",
                "ma_sku",
                "order_number",
                "ma_don_hang",
                "tracking_number",
                "ma_van_don",
                "cart_id",
                "ma_gio_hang",
                "seller_id",
                "ma_nguoi_ban",
                "order_id",
                "customer_id",
                "product_id",
            ),
            "integer": _rule(
                "order_quantity",
                "so_luong_dat",
                "stock_quantity",
                "ton_kho",
                "inventory_count",
                "quantity",
            ),
            "number": _rule(
                "product_rating",
                "shipping_weight",
                "can_nang_van_chuyen",
            ),
            "percentage": _rule("discount_rate", "discount_percent", "ty_le_giam"),
            "currency": _rule(
                "subtotal",
                "tam_tinh",
                "shipping_fee",
                "phi_van_chuyen",
                "discount_amount",
                "tien_giam",
                "refund_amount",
                "tien_hoan",
                "grand_total",
                "tong_thanh_toan",
                "unit_price",
                "discount",
                "order_total",
            ),
            "date": _rule("delivery_date", "ngay_giao_hang", "return_date", "ngay_tra_hang"),
            "datetime": _rule(
                "ordered_at",
                "thoi_gian_dat_hang",
                "shipped_at",
                "thoi_gian_gui_hang",
                "delivered_at",
                "thoi_gian_giao_hang",
            ),
            "boolean": _rule(
                "is_cod",
                "thanh_toan_cod",
                "is_returned",
                "da_tra_hang",
                "is_in_stock",
                "con_hang",
            ),
            "category": _rule(
                "product_category",
                "danh_muc_san_pham",
                "fulfilment_status",
                "fulfillment_status",
                "trang_thai_xu_ly",
                "shipping_method",
                "phuong_thuc_van_chuyen",
                "order_status",
                "payment_status",
                "shipping_status",
                "channel",
            ),
            "address": _rule(
                "shipping_address",
                "dia_chi_giao_hang",
                "billing_address",
                "dia_chi_thanh_toan",
                "address",
                "province",
                "district",
            ),
        },
    ),
    "marketing": _extend_profile(
        "marketing",
        "Campaign, advertising, lead, audience, and engagement data.",
        defaults={"domain_rules": {"enabled": True, "mode": "report_only"}},
        rules={
            "text": _rule(
                "ad_copy",
                "noi_dung_quang_cao",
                "subject_line",
                "tieu_de_email",
                "campaign_name",
                "ten_chien_dich",
                "campaign",
                "content",
            ),
            "identifier": _rule(
                "campaign_id",
                "ma_chien_dich",
                "ad_id",
                "ma_quang_cao",
                "creative_id",
                "lead_id",
                "ma_khach_hang_tiem_nang",
            ),
            "integer": _rule(
                "impressions",
                "luot_hien_thi",
                "clicks",
                "luot_nhap",
                "conversions",
                "luot_chuyen_doi",
                "opens",
                "luot_mo",
                "reach",
                "tiep_can",
                "leads",
            ),
            "percentage": _rule(
                "ctr",
                "click_through_rate",
                "conversion_rate",
                "ty_le_chuyen_doi",
                "open_rate",
                "ty_le_mo",
                "bounce_rate",
                "ty_le_thoat",
            ),
            "currency": _rule(
                "ad_spend",
                "chi_phi_quang_cao",
                "campaign_budget",
                "ngan_sach_chien_dich",
                "cpc",
                "cost_per_click",
                "cpm",
                "cost_per_mille",
                "cost_per_acquisition",
                "cpa",
                "spend",
                "cpl",
            ),
            "number": _rule("roas"),
            "date": _rule(
                "campaign_start_date",
                "ngay_bat_dau_chien_dich",
                "campaign_end_date",
                "ngay_ket_thuc_chien_dich",
                "date",
            ),
            "datetime": _rule("event_time", "thoi_gian_su_kien", "sent_at", "thoi_gian_gui"),
            "boolean": _rule(
                "is_subscribed",
                "da_dang_ky",
                "is_opted_out",
                "da_huy_dang_ky",
                "is_converted",
                "da_chuyen_doi",
            ),
            "category": _rule(
                "channel",
                "kenh",
                "marketing_channel",
                "kenh_marketing",
                "source",
                "nguon",
                "medium",
                "utm_source",
                "utm_medium",
                "audience_segment",
                "phan_khuc_doi_tuong",
                "lead_status",
                "trang_thai_lead",
                "medium",
            ),
        },
    ),
}


_PROFILE_ALIASES = {
    "general": "generic",
    "default": "generic",
    "fb": "fnb",
    "food_beverage": "fnb",
    "food_and_beverage": "fnb",
    "financial": "finance",
    "accounting": "finance",
    "e_commerce": "ecommerce",
    "online_shopping": "ecommerce",
    "online_shop": "ecommerce",
    "mkt": "marketing",
}


def list_profiles() -> list[str]:
    """Return canonical built-in profile names in stable order."""

    return list(_BUILTIN_PROFILES)


def _canonical_profile_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("profile name must be a string")
    key = normalize_column_name(name)
    return _PROFILE_ALIASES.get(key, key)


def get_profile(
    name: str = "generic", overrides: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Return an isolated built-in profile, optionally merged with JSON overrides.

    The returned dictionary is a deep copy and can be modified safely.  Unknown
    profile names raise ``ValueError`` with the available canonical names.
    """

    key = _canonical_profile_name(name)
    try:
        profile = deepcopy(_BUILTIN_PROFILES[key])
    except KeyError as exc:
        choices = ", ".join(list_profiles())
        raise ValueError(f"unknown profile {name!r}; choose one of: {choices}") from exc
    if overrides is not None:
        profile = deep_merge(profile, overrides)
    return profile


def merge_profile_config(
    profile: str | Mapping[str, Any], overrides: Mapping[str, Any]
) -> dict[str, Any]:
    """Overlay a user configuration on a profile name or profile dictionary."""

    base = get_profile(profile) if isinstance(profile, str) else profile
    if not isinstance(base, Mapping):
        raise TypeError("profile must be a profile name or mapping")
    return deep_merge(base, overrides)


def _coerce_profile(
    profile: str | Mapping[str, Any], overrides: Mapping[str, Any] | None
) -> dict[str, Any]:
    if isinstance(profile, str):
        # Resolver calls are read-only and may happen once per DataFrame column;
        # avoid deep-copying the complete built-in profile on every lookup.
        if overrides is None:
            key = _canonical_profile_name(profile)
            try:
                return _BUILTIN_PROFILES[key]
            except KeyError as exc:
                choices = ", ".join(list_profiles())
                raise ValueError(
                    f"unknown profile {profile!r}; choose one of: {choices}"
                ) from exc
        return get_profile(profile, overrides)
    if not isinstance(profile, Mapping):
        raise TypeError("profile must be a profile name or mapping")
    return deep_merge(profile, overrides or {})


def resolve_semantic_type(
    column_name: object,
    profile: str | Mapping[str, Any] = "generic",
    *,
    overrides: Mapping[str, Any] | None = None,
) -> str | None:
    """Infer one semantic type from a Vietnamese or English column name.

    Exact aliases take precedence over regular expressions.  If aliases or
    patterns produce more than one semantic type, ``None`` is returned.  Value
    sampling is intentionally outside this module; callers should treat this as
    a safe hint, not a schema guarantee.
    """

    normalized = normalize_column_name(column_name)
    if not normalized:
        return None

    selected_profile = _coerce_profile(profile, overrides)
    rules = selected_profile.get("column_types", {})
    if not isinstance(rules, Mapping):
        return None

    exact_matches: set[str] = set()
    for semantic_type, rule in rules.items():
        if semantic_type not in SEMANTIC_TYPES or not isinstance(rule, Mapping):
            continue
        aliases = rule.get("aliases", ())
        if isinstance(aliases, str):
            aliases = (aliases,)
        if any(normalize_column_name(alias) == normalized for alias in aliases):
            exact_matches.add(semantic_type)
    if len(exact_matches) == 1:
        return exact_matches.pop()
    if exact_matches:
        return None

    pattern_matches: set[str] = set()
    for semantic_type, rule in rules.items():
        if semantic_type not in SEMANTIC_TYPES or not isinstance(rule, Mapping):
            continue
        patterns = rule.get("patterns", ())
        if isinstance(patterns, str):
            patterns = (patterns,)
        for pattern in patterns:
            try:
                if re.fullmatch(str(pattern), normalized, flags=re.IGNORECASE):
                    pattern_matches.add(semantic_type)
                    break
            except re.error as exc:
                raise ValueError(
                    f"invalid {semantic_type!r} column-name pattern {pattern!r}"
                ) from exc
    return pattern_matches.pop() if len(pattern_matches) == 1 else None


def resolve_column_type(
    column_name: object,
    profile: str | Mapping[str, Any] = "generic",
    *,
    overrides: Mapping[str, Any] | None = None,
) -> str | None:
    """Alias for :func:`resolve_semantic_type`."""

    return resolve_semantic_type(column_name, profile, overrides=overrides)


def resolve_semantic_types(
    column_names: Iterable[object],
    profile: str | Mapping[str, Any] = "generic",
    *,
    overrides: Mapping[str, Any] | None = None,
    include_unknown: bool = True,
) -> dict[object, str | None]:
    """Resolve several column names using one materialised profile.

    ``include_unknown=False`` omits names that do not resolve.  As with a pandas
    column mapping, duplicate labels collapse to the final mapping entry.
    """

    selected_profile = _coerce_profile(profile, overrides)
    resolved: dict[object, str | None] = {}
    for name in column_names:
        semantic_type = resolve_semantic_type(name, selected_profile)
        if include_unknown or semantic_type is not None:
            resolved[name] = semantic_type
    return resolved


infer_semantic_types = resolve_semantic_types


__all__ = [
    "SEMANTIC_TYPES",
    "deep_merge",
    "get_profile",
    "infer_semantic_types",
    "list_profiles",
    "merge_profile_config",
    "normalize_column_name",
    "resolve_column_type",
    "resolve_semantic_type",
    "resolve_semantic_types",
]
