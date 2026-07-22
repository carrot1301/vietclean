from decimal import Decimal

import pytest

from vietclean.text import (
    canonicalize_missing_token,
    is_missing,
    normalize_email,
    normalize_missing,
    normalize_phone,
    normalize_unicode,
    normalize_whitespace,
    parse_vietnamese_currency,
    parse_vietnamese_number,
    remove_invisible_chars,
    repair_mojibake,
)


def test_unicode_nfc_preserves_valid_vietnamese() -> None:
    decomposed = "Tie\u0302\u0301ng Vie\u0323\u0302t"
    assert normalize_unicode(decomposed) == "Tiếng Việt"
    assert repair_mojibake("Đặng Thị Hồng – Hà Nội") == "Đặng Thị Hồng – Hà Nội"
    assert normalize_unicode("Ａ", form="NFKC") == "A"


@pytest.mark.parametrize(
    ("broken", "expected"),
    [
        ("Tiáº¿ng Viá»‡t", "Tiếng Việt"),
        ("CafÃ©", "Café"),
        ("Cá»­a hÃ ng", "Cửa hàng"),
        ("TiÃ¡ÂºÂ¿ng", "Tiếng"),
    ],
)
def test_repair_common_mojibake(broken: str, expected: str) -> None:
    assert repair_mojibake(broken) == expected


def test_remove_invisible_and_controls_safely() -> None:
    assert remove_invisible_chars("\ufeffA\u200bB\x00\tC\nD") == "AB\tC\nD"
    # Joiners are meaningful in other scripts and emoji, so remain by default.
    assert remove_invisible_chars("a\u200db") == "a\u200db"
    assert remove_invisible_chars("a\u200db", remove_joiners=True) == "ab"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("keep", "a b\nc\n\nd"), ("space", "a b c d"), ("remove", "a bcd")],
)
def test_whitespace_modes(mode: str, expected: str) -> None:
    raw = "  a\t b \r\n c\n\n d  "
    assert normalize_whitespace(raw, line_breaks=mode) == expected


def test_missing_tokens_are_canonical_and_configurable() -> None:
    assert canonicalize_missing_token(" N.A. ") == "na"
    assert is_missing("  CHƯA   CÓ ")
    assert is_missing("?")
    assert is_missing(float("nan"))
    assert not is_missing(0)
    assert is_missing("unknown", ["UNKNOWN"])
    assert not is_missing("UNKNOWN", ["unknown"], case_sensitive=True)


def test_email_normalization_is_conservative() -> None:
    assert normalize_email(" MailTo:User @ GMAIL．COM ") == "User@gmail.com"
    assert normalize_email("first..last@example.com") is None
    assert normalize_email("not an email") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0912 345 678", "+84912345678"),
        ("(+84) (0) 912-345-678", "+84912345678"),
        ("0084.912.345.678", "+84912345678"),
        ("+1 (202) 555-0123", "+12025550123"),
    ],
)
def test_phone_normalization(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


def test_phone_extension_can_be_kept() -> None:
    assert normalize_phone("028 1234 5678 x123", keep_extension=True) == "+842812345678 x123"
    assert normalize_phone("phone: 0912345678") is None
    assert normalize_phone("0912345678", default_country="VN") == "+84912345678"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("1 234 567,89", Decimal("1234567.89")),
        ("12.50", Decimal("12.50")),
        ("(1.000)", Decimal("-1000")),
        ("１２３,４５", Decimal("123.45")),
    ],
)
def test_parse_vietnamese_number(raw: str, expected: Decimal) -> None:
    assert parse_vietnamese_number(raw) == expected


def test_number_parser_rejects_bad_grouping_and_handles_percent_opt_in() -> None:
    assert parse_vietnamese_number("12.34,56") is None
    assert parse_vietnamese_number("12,5%") is None
    assert parse_vietnamese_number("12,5%", percent_as_fraction=True) == Decimal("0.125")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.250.000 ₫", Decimal("1250000")),
        ("850,000 VND", Decimal("850000")),
        ("VND 1,5 triệu", Decimal("1500000.0")),
        ("250k đ", Decimal("250000")),
        ("(2,5 tỷ đồng)", Decimal("-2500000000.0")),
    ],
)
def test_parse_vietnamese_currency(raw: str, expected: Decimal) -> None:
    assert parse_vietnamese_currency(raw) == expected


def test_currency_parser_does_not_extract_numbers_from_arbitrary_text() -> None:
    assert parse_vietnamese_currency("tổng khoảng 1 triệu") is None


def test_currency_parser_does_not_silently_drop_units() -> None:
    assert parse_vietnamese_currency("1 USD", expected_currency="VND") is None
    assert parse_vietnamese_currency("1 USD", expected_currency="USD") == Decimal("1")
    assert parse_vietnamese_currency("1 USD + 1 VND") is None
    assert parse_vietnamese_currency("$1,200.50", expected_currency="USD") == Decimal(
        "1200.50"
    )
    with pytest.raises(ValueError, match="unsupported"):
        parse_vietnamese_currency("1 BTC", expected_currency="BTC")


def test_text_helpers_reject_invalid_arguments_and_control_modes() -> None:
    with pytest.raises(TypeError):
        normalize_unicode(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="form"):
        normalize_unicode("x", form="NFD")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        remove_invisible_chars(1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        repair_mojibake(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="non-negative"):
        repair_mojibake("x", max_passes=-1)

    assert remove_invisible_chars("a\tb\nc", keep_tabs=False, keep_newlines=False) == "abc"
    assert normalize_missing("N/A", replacement="missing") == "missing"
    assert normalize_missing("ok", replacement="missing") == "ok"


@pytest.mark.parametrize(
    "value",
    [
        1,
        "a b@example.com",
        ".a@example.com",
        "a..b@example.com",
        "a!🙂@example.com",
        "a@-example.com",
        "a@example..com",
    ],
)
def test_email_rejects_structurally_invalid_values(value: object) -> None:
    assert normalize_email(value) is None  # type: ignore[arg-type]


def test_email_idna_display_and_lowercase_local_are_explicit() -> None:
    assert normalize_email("<USER@café.vn>") == "USER@xn--caf-dma.vn"
    assert normalize_email(
        "USER@café.vn", lowercase_local=True, idna_domain=False
    ) == "user@café.vn"


def test_phone_edge_cases_are_explicit_and_bounded() -> None:
    assert normalize_phone(True) is None
    assert normalize_phone("tel: 0912 345 678") == "+84912345678"
    assert normalize_phone("+84 (0) 912345678") == "+84912345678"
    assert normalize_phone("84912345678") == "+84912345678"
    assert normalize_phone("12345678", default_country="none") == "12345678"
    assert normalize_phone("12+345678") is None
    assert normalize_phone("123") is None
    with pytest.raises(ValueError, match="min_digits"):
        normalize_phone("12345678", min_digits=10, max_digits=5)
    with pytest.raises(ValueError, match="default_country"):
        normalize_phone("0912345678", default_country="US")
    with pytest.raises(ValueError, match="country_code"):
        normalize_phone("0912345678", country_code="VN")


def test_number_and_currency_edge_cases_do_not_guess() -> None:
    assert parse_vietnamese_number(12) == Decimal("12")
    assert parse_vietnamese_number(float("inf")) is None
    assert parse_vietnamese_number(Decimal("NaN")) is None
    assert parse_vietnamese_number("(1.000") is None
    assert parse_vietnamese_number("1,2,34") is None
    assert parse_vietnamese_number("1.23.456,7") is None
    assert parse_vietnamese_number("--1") is None
    assert parse_vietnamese_number("-1%", percent_as_fraction=True) == Decimal("-0.01")
    assert parse_vietnamese_currency(Decimal("1.20")) == Decimal("1.20")
    assert parse_vietnamese_currency("(1.000") is None
    assert parse_vietnamese_currency("(-1.000)") is None
    assert parse_vietnamese_currency("không phải tiền") is None
