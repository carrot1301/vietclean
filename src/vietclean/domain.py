"""Conservative, report-only validation rules for built-in business profiles.

The engine never changes a value.  Rules run only when all required input
columns are present, which keeps a profile useful for partial exports (for
example, a product table using the e-commerce profile).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, cast

import pandas as pd

from .profiles import normalize_column_name


@dataclass(frozen=True, slots=True)
class DomainValidationResult:
    """PII-safe aggregate result from domain validation."""

    profile: str
    violations: dict[str, int]
    rows_checked: int

    @property
    def passed(self) -> bool:
        """Return ``True`` when no configured domain rule was violated."""

        return not any(self.violations.values())


def _column_map(frame: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for column in frame.columns:
        normalized = normalize_column_name(str(column))
        if normalized:
            result.setdefault(normalized, column)
    return result


def _find(columns: Mapping[str, Any], *aliases: str) -> Any | None:
    for alias in aliases:
        found = columns.get(normalize_column_name(alias))
        if found is not None:
            return found
    return None


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        if bool(pd.isna(cast(Any, value))):
            return None
    except (TypeError, ValueError):
        return None
    try:
        converted = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return converted if converted.is_finite() else None


def _missing_count(series: pd.Series) -> int:
    return int(
        series.map(
            lambda value: value is None
            or (isinstance(value, str) and not value.strip())
            or _is_scalar_na(value)
        ).sum()
    )


def _is_scalar_na(value: object) -> bool:
    try:
        return bool(pd.isna(cast(Any, value)))
    except (TypeError, ValueError):
        return False


def _negative_count(series: pd.Series) -> int:
    return int(
        series.map(
            lambda value: (number := _decimal(value)) is not None and number < 0
        ).sum()
    )


def _non_integer_count(series: pd.Series) -> int:
    return int(
        series.map(
            lambda value: (number := _decimal(value)) is not None
            and number != number.to_integral_value()
        ).sum()
    )


def _mismatch(
    observed: Decimal,
    expected: Decimal,
    *,
    absolute_tolerance: Decimal,
    relative_tolerance: Decimal,
) -> bool:
    allowed = max(absolute_tolerance, abs(expected) * relative_tolerance)
    return abs(observed - expected) > allowed


def _reconciliation_count(
    frame: pd.DataFrame,
    observed_column: Any,
    component_columns: tuple[Any, ...],
    calculate: Any,
    *,
    absolute_tolerance: Decimal,
    relative_tolerance: Decimal,
) -> int:
    count = 0
    selected = frame.loc[:, [observed_column, *component_columns]]
    for values in selected.itertuples(index=False, name=None):
        decimals = tuple(_decimal(value) for value in values)
        if any(value is None for value in decimals):
            continue
        observed = decimals[0]
        components = decimals[1:]
        assert observed is not None
        expected = calculate(*(value for value in components if value is not None))
        if _mismatch(
            observed,
            expected,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
        ):
            count += 1
    return count


def _allowed_count(series: pd.Series, allowed: object) -> int:
    if not isinstance(allowed, (list, tuple, set, frozenset)):
        return 0
    normalized = {normalize_column_name(str(value)) for value in allowed}
    return int(
        series.map(
            lambda value: not _is_scalar_na(value)
            and normalize_column_name(str(value)) not in normalized
        ).sum()
    )


def _record(violations: dict[str, int], rule: str, count: int) -> None:
    if count:
        violations[rule] = count


def _validate_fnb(
    frame: pd.DataFrame,
    columns: Mapping[str, Any],
    options: Mapping[str, Any],
    absolute: Decimal,
    relative: Decimal,
) -> dict[str, int]:
    violations: dict[str, int] = {}
    order_id = _find(columns, "order_id", "ma_don_hang", "ma_hoa_don")
    quantity = _find(columns, "quantity", "qty", "so_luong", "so_luong_mon")
    unit_price = _find(columns, "unit_price", "don_gia", "gia_mon")
    discount = _find(columns, "discount", "tien_giam", "discount_amount")
    tax = _find(columns, "tax", "thue", "tax_amount", "tien_thue")
    total = _find(columns, "total", "line_total", "thanh_tien", "tong_tien")
    payment = _find(columns, "payment_method", "phuong_thuc_thanh_toan")

    if order_id is not None:
        _record(violations, "fnb.order_id_missing", _missing_count(frame[order_id]))
    if quantity is not None:
        _record(violations, "fnb.quantity_negative", _negative_count(frame[quantity]))
        _record(violations, "fnb.quantity_non_integer", _non_integer_count(frame[quantity]))
    if unit_price is not None:
        _record(violations, "fnb.unit_price_negative", _negative_count(frame[unit_price]))
    if all(column is not None for column in (quantity, unit_price, total)):
        discount_series = (
            frame[discount] if discount is not None else pd.Series(0, index=frame.index)
        )
        tax_series = frame[tax] if tax is not None else pd.Series(0, index=frame.index)
        temporary = frame.assign(__discount=discount_series, __tax=tax_series)

        def expected_total(
            qty: Decimal, price: Decimal, reduction: Decimal, levy: Decimal
        ) -> Decimal:
            subtotal = qty * price
            discount_amount = (
                subtotal * reduction
                if options.get("discount_mode", "amount") == "rate"
                else reduction
            )
            after_discount = subtotal - discount_amount
            tax_amount = (
                after_discount * levy
                if options.get("tax_mode", "amount") == "rate"
                else levy
            )
            return after_discount + tax_amount

        _record(
            violations,
            "fnb.total_mismatch",
            _reconciliation_count(
                temporary,
                total,
                (quantity, unit_price, "__discount", "__tax"),
                expected_total,
                absolute_tolerance=absolute,
                relative_tolerance=relative,
            ),
        )
    if payment is not None:
        allowed = options.get(
            "payment_methods",
            [
                "cash",
                "card",
                "bank_transfer",
                "cod",
                "momo",
                "zalopay",
                "tiền mặt",
                "thẻ",
                "chuyển khoản",
            ],
        )
        _record(
            violations,
            "fnb.payment_method_invalid",
            _allowed_count(frame[payment], allowed),
        )
    return violations


def _validate_finance(
    frame: pd.DataFrame,
    columns: Mapping[str, Any],
    options: Mapping[str, Any],
    absolute: Decimal,
    relative: Decimal,
) -> dict[str, int]:
    violations: dict[str, int] = {}
    transaction_id = _find(columns, "transaction_id", "ma_giao_dich")
    debit = _find(columns, "debit", "debit_amount", "phat_sinh_no")
    credit = _find(columns, "credit", "credit_amount", "phat_sinh_co")
    amount = _find(columns, "amount", "so_tien")
    currency = _find(columns, "currency", "currency_code", "ma_tien_te")

    if transaction_id is not None:
        series = frame[transaction_id]
        _record(violations, "finance.transaction_id_missing", _missing_count(series))
        _record(
            violations,
            "finance.transaction_id_duplicate",
            int(series.notna().where(series.astype("string").str.strip().ne(""), False).mul(
                series.duplicated(keep=False)
            ).sum()),
        )
    if debit is not None:
        _record(violations, "finance.debit_negative", _negative_count(frame[debit]))
    if credit is not None:
        _record(violations, "finance.credit_negative", _negative_count(frame[credit]))
    if debit is not None and credit is not None:
        if options.get("debit_credit_rule", "one_sided") == "one_sided":
            both_nonzero = sum(
                1
                for debit_value, credit_value in frame[[debit, credit]].itertuples(
                    index=False, name=None
                )
                if (left := _decimal(debit_value)) is not None
                and (right := _decimal(credit_value)) is not None
                and left != 0
                and right != 0
            )
            _record(violations, "finance.debit_credit_both_nonzero", both_nonzero)
        amount_formula = options.get(
            "finance_amount_formula", "debit_minus_credit"
        )
        if amount is not None and amount_formula != "disabled":
            def calculate(
                debit_value: Decimal, credit_value: Decimal
            ) -> Decimal:
                difference = debit_value - credit_value
                return abs(difference) if amount_formula == "absolute_difference" else difference

            _record(
                violations,
                "finance.reconciliation_mismatch",
                _reconciliation_count(
                    frame,
                    amount,
                    (debit, credit),
                    calculate,
                    absolute_tolerance=absolute,
                    relative_tolerance=relative,
                ),
            )
    if currency is not None:
        supported = options.get("currencies", ["VND", "USD", "EUR", "GBP", "JPY", "CNY"])
        _record(
            violations,
            "finance.currency_invalid",
            _allowed_count(frame[currency], supported),
        )
    return violations


def _validate_ecommerce(
    frame: pd.DataFrame,
    columns: Mapping[str, Any],
    options: Mapping[str, Any],
    absolute: Decimal,
    relative: Decimal,
) -> dict[str, int]:
    violations: dict[str, int] = {}
    order_id = _find(columns, "order_id", "order_number", "ma_don_hang")
    sku = _find(columns, "sku", "product_sku", "ma_sku")
    quantity = _find(columns, "quantity", "order_quantity", "so_luong_dat")
    price = _find(columns, "unit_price", "price", "don_gia")
    discount = _find(columns, "discount", "discount_amount", "tien_giam")
    shipping = _find(columns, "shipping_fee", "phi_van_chuyen")
    total = _find(columns, "order_total", "grand_total", "tong_thanh_toan")

    if order_id is not None:
        _record(violations, "ecommerce.order_id_missing", _missing_count(frame[order_id]))
    if sku is not None:
        _record(violations, "ecommerce.sku_missing", _missing_count(frame[sku]))
    if quantity is not None:
        _record(violations, "ecommerce.quantity_negative", _negative_count(frame[quantity]))
        _record(
            violations,
            "ecommerce.quantity_non_integer",
            _non_integer_count(frame[quantity]),
        )
    if price is not None:
        _record(violations, "ecommerce.unit_price_negative", _negative_count(frame[price]))
    if discount is not None:
        _record(violations, "ecommerce.discount_negative", _negative_count(frame[discount]))
    if all(column is not None for column in (quantity, price, total)):
        discount_series = (
            frame[discount] if discount is not None else pd.Series(0, index=frame.index)
        )
        shipping_series = (
            frame[shipping] if shipping is not None else pd.Series(0, index=frame.index)
        )
        temporary = frame.assign(__discount=discount_series, __shipping=shipping_series)

        def expected_total(
            qty: Decimal, unit_price: Decimal, reduction: Decimal, fee: Decimal
        ) -> Decimal:
            subtotal = qty * unit_price
            discount_amount = (
                subtotal * reduction
                if options.get("discount_mode", "amount") == "rate"
                else reduction
            )
            return subtotal - discount_amount + fee

        _record(
            violations,
            "ecommerce.order_total_mismatch",
            _reconciliation_count(
                temporary,
                total,
                (quantity, price, "__discount", "__shipping"),
                expected_total,
                absolute_tolerance=absolute,
                relative_tolerance=relative,
            ),
        )
    status_rules = (
        (
            "order_status",
            "ecommerce.order_status_invalid",
            ["pending", "confirmed", "processing", "shipped", "delivered", "cancelled", "returned"],
        ),
        (
            "payment_status",
            "ecommerce.payment_status_invalid",
            ["pending", "paid", "failed", "refunded", "partial_refund"],
        ),
        (
            "shipping_status",
            "ecommerce.shipping_status_invalid",
            ["pending", "ready", "shipped", "in_transit", "delivered", "failed", "returned"],
        ),
    )
    for field, rule, defaults in status_rules:
        column = _find(columns, field)
        if column is not None:
            _record(
                violations,
                rule,
                _allowed_count(frame[column], options.get(f"{field}es", defaults)),
            )
    return violations


def _ratio_mismatch_count(
    frame: pd.DataFrame,
    observed_column: Any,
    numerator_column: Any,
    denominator_column: Any,
    multiplier: Decimal,
    absolute: Decimal,
    relative: Decimal,
) -> int:
    return _reconciliation_count(
        frame,
        observed_column,
        (numerator_column, denominator_column),
        lambda numerator, denominator: (
            numerator / denominator * multiplier if denominator != 0 else Decimal(0)
        ),
        absolute_tolerance=absolute,
        relative_tolerance=relative,
    )


def _validate_marketing(
    frame: pd.DataFrame,
    columns: Mapping[str, Any],
    options: Mapping[str, Any],
    absolute: Decimal,
    relative: Decimal,
) -> dict[str, int]:
    violations: dict[str, int] = {}
    campaign_id = _find(columns, "campaign_id", "ma_chien_dich")
    spend = _find(columns, "spend", "ad_spend", "chi_phi_quang_cao")
    impressions = _find(columns, "impressions", "luot_hien_thi")
    clicks = _find(columns, "clicks", "luot_nhap")
    revenue = _find(columns, "revenue", "doanh_thu")
    ctr = _find(columns, "ctr", "click_through_rate")
    cpc = _find(columns, "cpc", "cost_per_click")
    cpm = _find(columns, "cpm", "cost_per_mille")
    roas = _find(columns, "roas")

    if campaign_id is not None:
        _record(
            violations,
            "marketing.campaign_id_missing",
            _missing_count(frame[campaign_id]),
        )
    if spend is not None:
        _record(violations, "marketing.spend_negative", _negative_count(frame[spend]))
    if impressions is not None and clicks is not None:
        count = sum(
            1
            for impression_value, click_value in frame[[impressions, clicks]].itertuples(
                index=False, name=None
            )
            if (views := _decimal(impression_value)) is not None
            and (interactions := _decimal(click_value)) is not None
            and interactions > views
        )
        _record(violations, "marketing.clicks_exceed_impressions", count)
        if ctr is not None:
            multiplier = (
                Decimal(100)
                if options.get("kpi_scale", "fraction") == "percent"
                else Decimal(1)
            )
            _record(
                violations,
                "marketing.ctr_mismatch",
                _ratio_mismatch_count(
                    frame, ctr, clicks, impressions, multiplier, absolute, relative
                ),
            )
    if spend is not None and clicks is not None and cpc is not None:
        _record(
            violations,
            "marketing.cpc_mismatch",
            _ratio_mismatch_count(frame, cpc, spend, clicks, Decimal(1), absolute, relative),
        )
    if spend is not None and impressions is not None and cpm is not None:
        _record(
            violations,
            "marketing.cpm_mismatch",
            _ratio_mismatch_count(
                frame, cpm, spend, impressions, Decimal(1000), absolute, relative
            ),
        )
    if revenue is not None and spend is not None and roas is not None:
        _record(
            violations,
            "marketing.roas_mismatch",
            _ratio_mismatch_count(frame, roas, revenue, spend, Decimal(1), absolute, relative),
        )
    return violations


def validate_domain_rules(
    frame: pd.DataFrame,
    profile: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> DomainValidationResult:
    """Validate cross-column rules without mutating ``frame``.

    The returned dictionary contains counts only; it never exposes cell values.
    Unknown/generic profiles produce an empty, successful result.
    """

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("frame must be a pandas.DataFrame")
    if not isinstance(profile, str):
        raise TypeError("profile must be a string")
    options = dict(config or {})
    if options.get("mode", "report_only") != "report_only":
        raise ValueError("domain validation supports report_only mode only")
    absolute = Decimal(str(options.get("absolute_tolerance", 1.0)))
    relative = Decimal(str(options.get("relative_tolerance", 0.001)))
    if absolute < 0 or relative < 0:
        raise ValueError("domain tolerances must be non-negative")
    columns = _column_map(frame)
    canonical = normalize_column_name(profile)
    validators = {
        "fnb": _validate_fnb,
        "finance": _validate_finance,
        "ecommerce": _validate_ecommerce,
        "marketing": _validate_marketing,
    }
    validator = validators.get(canonical)
    violations = (
        validator(frame, columns, options, absolute, relative) if validator else {}
    )
    return DomainValidationResult(
        profile=canonical,
        violations=violations,
        rows_checked=len(frame),
    )


__all__ = ["DomainValidationResult", "validate_domain_rules"]
