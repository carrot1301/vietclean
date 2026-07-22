"""Dependency-free helpers for cleaning Vietnamese text and scalar values.

The functions in this module are deliberately conservative.  In particular,
mojibake is repaired only when the source contains a known bad byte pattern and
the repaired candidate has a strictly lower mojibake score.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from numbers import Integral, Real
import re
import unicodedata
from typing import Iterable, Literal


WhitespaceMode = Literal[
    "preserve",
    "trim",
    "normalize_spaces",
    "single_line",
    "canonical_multiline",
]
LegacyLineBreakMode = Literal["keep", "space", "remove"]
LineBreakMode = WhitespaceMode | LegacyLineBreakMode


@dataclass(frozen=True, slots=True)
class MojibakeCandidate:
    """One bounded, reversible decoding candidate for a suspicious string.

    ``value`` is intentionally available only in this low-level API.  Audit
    writers must aggregate candidate counts instead of serialising values,
    because a text cell can contain PII.
    """

    value: str
    method: str
    penalty: int


@dataclass(frozen=True, slots=True)
class MojibakeRepairResult:
    """Decision and metadata from conservative mojibake analysis."""

    value: str
    confidence: float
    changed: bool
    needs_review: bool
    unrepaired: bool
    source_penalty: int
    candidates: tuple[MojibakeCandidate, ...]


# ZWNJ and ZWJ are not removed by default: although Vietnamese does not need
# them, they are meaningful in several writing systems and in emoji sequences.
_INVISIBLE_FORMAT_CHARS = frozenset(
    {
        "\u00ad",  # soft hyphen
        "\u180e",  # legacy Mongolian vowel separator
        "\u200b",  # zero-width space
        "\u2060",  # word joiner
        "\ufeff",  # BOM / zero-width no-break space
    }
)
_JOINERS = frozenset({"\u200c", "\u200d"})

_RAW_MISSING_TOKENS = (
    "",
    "-",
    "--",
    "---",
    "?",
    "n/a",
    "n.a.",
    "na",
    "#n/a",
    "#na",
    "null",
    "none",
    "nil",
    "nan",
    "nat",
    "missing",
    "unknown",
    "not available",
    "blank",
    "(blank)",
    "empty",
    "không có",
    "khong co",
    "chưa có",
    "chua co",
    "không rõ",
    "khong ro",
    "không xác định",
    "khong xac dinh",
    "trống",
    "trong",
    "thiếu",
    "thieu",
)

# Exposed as raw, human-readable values so callers can extend or display it.
DEFAULT_MISSING_TOKENS = frozenset(_RAW_MISSING_TOKENS)


def normalize_unicode(text: str, form: Literal["NFC", "NFKC"] = "NFC") -> str:
    """Return *text* in Unicode NFC form (or explicit NFKC form).

    NFC composes decomposed Vietnamese tone marks without using compatibility
    mappings, so meaningful characters and typography are left intact.  NFKC
    is available as an explicit opt-in for compatibility-width characters.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if form not in {"NFC", "NFKC"}:
        raise ValueError("form must be 'NFC' or 'NFKC'")
    return unicodedata.normalize(form, text)


def remove_invisible_chars(
    text: str,
    *,
    keep_newlines: bool = True,
    keep_tabs: bool = True,
    remove_joiners: bool = False,
) -> str:
    """Remove BOM, common zero-width artifacts, and unsafe control characters.

    Newlines and tabs are retained by default for later whitespace handling.
    ZWNJ/ZWJ are also retained by default because they can be semantically
    meaningful outside Vietnamese; pass ``remove_joiners=True`` for datasets
    known to contain only plain Vietnamese text.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")

    result: list[str] = []
    for char in text:
        if char in _INVISIBLE_FORMAT_CHARS:
            continue
        if remove_joiners and char in _JOINERS:
            continue
        if unicodedata.category(char) == "Cc":
            if keep_newlines and char in "\r\n":
                result.append(char)
            elif keep_tabs and char == "\t":
                result.append(char)
            # Other C0/C1 controls are data artifacts in ordinary text.
            continue
        result.append(char)
    return "".join(result)


def _mojibake_penalty(text: str) -> int:
    """Score common UTF-8-as-Latin-1/CP1252 artifacts (lower is better)."""

    penalty = text.count("\ufffd") * 20
    penalty += sum(
        8
        for char in text
        if unicodedata.category(char) == "Cc" and char not in "\t\r\n"
    )

    # These characters/fragments are the characteristic leading pieces of
    # UTF-8 bytes viewed as Latin-1 or Windows-1252.  Conditions avoid treating
    # the valid Vietnamese letter Â as suspicious in normal words such as "Âm".
    penalty += text.count("Ã") * 5
    penalty += text.count("Æ") * 5
    penalty += text.count("ðŸ") * 8
    penalty += text.count("ï»¿") * 10
    penalty += text.count("áº") * 8
    penalty += text.count("á»") * 8

    for index, char in enumerate(text[:-1]):
        following = text[index + 1]
        if char == "Â" and not (following.isascii() and following.isalnum()):
            penalty += 4
        elif char == "Ä" and not (following.isascii() and following.isalpha()):
            penalty += 5
        elif char == "â" and not following.isascii():
            penalty += 5
        elif char == "ð" and not following.isascii():
            penalty += 5
    return penalty


def _utf8_sequence_length(first_byte: int) -> int:
    if 0xC2 <= first_byte <= 0xDF:
        return 2
    if 0xE0 <= first_byte <= 0xEF:
        return 3
    if 0xF0 <= first_byte <= 0xF4:
        return 4
    return 0


def _repair_with_codec(text: str, codec: str) -> str:
    """Decode suspicious UTF-8 byte sequences embedded in a Unicode string."""

    output: list[str] = []
    index = 0
    while index < len(text):
        try:
            encoded_first = text[index].encode(codec)
        except UnicodeEncodeError:
            output.append(text[index])
            index += 1
            continue

        if len(encoded_first) != 1:
            output.append(text[index])
            index += 1
            continue

        sequence_length = _utf8_sequence_length(encoded_first[0])
        if sequence_length == 0 or index + sequence_length > len(text):
            output.append(text[index])
            index += 1
            continue

        byte_values = bytearray(encoded_first)
        valid_sequence = True
        for offset in range(1, sequence_length):
            try:
                encoded_char = text[index + offset].encode(codec)
            except UnicodeEncodeError:
                valid_sequence = False
                break
            if (
                len(encoded_char) != 1
                or not 0x80 <= encoded_char[0] <= 0xBF
            ):
                valid_sequence = False
                break
            byte_values.extend(encoded_char)

        if not valid_sequence:
            output.append(text[index])
            index += 1
            continue

        source_fragment = text[index : index + sequence_length]
        try:
            decoded_fragment = bytes(byte_values).decode("utf-8")
        except UnicodeDecodeError:
            output.append(text[index])
            index += 1
            continue

        source_penalty = _mojibake_penalty(source_fragment)
        repaired_penalty = _mojibake_penalty(decoded_fragment)
        if source_penalty >= 4 and repaired_penalty < source_penalty:
            output.append(decoded_fragment)
            index += sequence_length
        else:
            output.append(text[index])
            index += 1

    return "".join(output)


def _recover_lost_nbsp_artifact(text: str) -> str:
    """Recover UTF-8 ``C3 A0`` when a transport changed NBSP to ASCII space.

    The malformed sequence appears as ``Ã `` inside a word (for example
    ``ThÃ nh``).  It is not byte-for-byte reversible after that transport
    damage, so this bounded candidate is considered only when the same value
    contains another strong mojibake marker.  The rule is linguistic-neutral:
    it requires letters on both sides and does not match a standalone ``Ã``.
    """

    if _mojibake_penalty(text) < 10:
        return text
    return re.sub(r"(?<=[A-Za-zÀ-ỹ])Ã (?=[A-Za-zÀ-ỹ])", "à", text)


def analyze_mojibake(
    text: str,
    *,
    confidence_threshold: float = 0.90,
    max_passes: int = 3,
) -> MojibakeRepairResult:
    """Analyse and optionally repair common Vietnamese mojibake.

    Only CP1252 and Latin-1 interpretations are attempted, so work is bounded.
    A candidate must strictly reduce known artifact/replacement penalties and
    meet ``confidence_threshold``.  Low-confidence values remain unchanged and
    are marked for review.  Calling this function again on its accepted output
    is idempotent.
    """

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if not isinstance(max_passes, int) or isinstance(max_passes, bool) or max_passes < 0:
        raise ValueError("max_passes must be non-negative")
    if (
        not isinstance(confidence_threshold, (int, float))
        or isinstance(confidence_threshold, bool)
        or not 0 <= float(confidence_threshold) <= 1
    ):
        raise ValueError("confidence_threshold must be in [0, 1]")

    original = normalize_unicode(text)
    source_penalty = _mojibake_penalty(original)
    current = original
    methods: list[str] = []
    all_candidates: dict[str, MojibakeCandidate] = {}

    for _ in range(max_passes):
        recovered_space = _recover_lost_nbsp_artifact(current)
        generated = {
            "cp1252": _repair_with_codec(current, "cp1252"),
            "latin-1": _repair_with_codec(current, "latin-1"),
            "lost-nbsp": recovered_space,
            "lost-nbsp+cp1252": _repair_with_codec(recovered_space, "cp1252"),
            "lost-nbsp+latin-1": _repair_with_codec(recovered_space, "latin-1"),
        }
        for method, value in generated.items():
            normalized = normalize_unicode(value)
            if normalized != current:
                all_candidates.setdefault(
                    normalized,
                    MojibakeCandidate(
                        value=normalized,
                        method=method,
                        penalty=_mojibake_penalty(normalized),
                    ),
                )
        best_method, best = min(
            generated.items(),
            key=lambda item: (_mojibake_penalty(item[1]), len(item[1]), item[0]),
        )
        if best == current or _mojibake_penalty(best) >= _mojibake_penalty(current):
            break
        current = normalize_unicode(best)
        methods.append(best_method)

    final_penalty = _mojibake_penalty(current)
    if source_penalty > 0 and final_penalty < source_penalty:
        # A complete removal is high-confidence.  Partial repairs are scored by
        # the fraction of known corruption removed, never by a vague label.
        confidence = (source_penalty - final_penalty) / source_penalty
    else:
        confidence = 0.0
    accepted = current != original and confidence >= float(confidence_threshold)
    value = current if accepted else original
    remaining_penalty = _mojibake_penalty(value)
    suspicious = source_penalty > 0
    candidates = tuple(
        sorted(all_candidates.values(), key=lambda item: (item.penalty, item.method, item.value))
    )
    return MojibakeRepairResult(
        value=value,
        confidence=confidence,
        changed=accepted,
        needs_review=suspicious and not accepted,
        unrepaired=suspicious and remaining_penalty > 0,
        source_penalty=source_penalty,
        candidates=candidates,
    )


def repair_mojibake(
    text: str,
    *,
    confidence_threshold: float = 0.90,
    max_passes: int = 3,
) -> str:
    """Return the conservative value selected by :func:`analyze_mojibake`."""

    return analyze_mojibake(
        text,
        confidence_threshold=confidence_threshold,
        max_passes=max_passes,
    ).value


def normalize_whitespace(
    text: str,
    *,
    line_breaks: LineBreakMode = "space",
    trim: bool = True,
    mode: WhitespaceMode | None = None,
    tabs_to_spaces: bool = True,
    collapse_spaces: bool = True,
    normalize_non_breaking_space: bool = True,
) -> str:
    """Normalize whitespace using the five modes required by the framework.

    New code should pass ``mode`` (or one of the same values through
    ``line_breaks``): ``preserve``, ``trim``, ``normalize_spaces``,
    ``single_line`` or ``canonical_multiline``.  Legacy modes remain aliases:
    ``keep`` maps to ``normalize_spaces`` and ``space`` maps to ``single_line``;
    ``remove`` retains its historical join-without-a-separator behaviour.
    """

    valid_modes = {
        "preserve",
        "trim",
        "normalize_spaces",
        "single_line",
        "canonical_multiline",
    }
    legacy_modes = {"keep", "space", "remove"}
    selected = mode if mode is not None else line_breaks
    if selected not in valid_modes | legacy_modes:
        raise ValueError(
            "whitespace mode must be preserve, trim, normalize_spaces, "
            "single_line, canonical_multiline, keep, space, or remove"
        )
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if any(
        not isinstance(option, bool)
        for option in (
            trim,
            tabs_to_spaces,
            collapse_spaces,
            normalize_non_breaking_space,
        )
    ):
        raise TypeError("whitespace switches must be booleans")

    if selected == "preserve":
        return text
    if selected == "trim":
        return text.strip()

    if selected == "keep":
        selected = "normalize_spaces"
    elif selected == "space":
        selected = "single_line"

    # Convert all common logical separators before control-character cleanup.
    cleaned = normalize_unicode(text)
    if normalize_non_breaking_space:
        cleaned = cleaned.replace("\u00a0", " ")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[\u000b\u000c\u0085\u2028\u2029]", "\n", cleaned)
    cleaned = remove_invisible_chars(cleaned, keep_newlines=True, keep_tabs=True)
    if tabs_to_spaces:
        cleaned = cleaned.replace("\t", " ")
    if collapse_spaces:
        cleaned = re.sub(r"[^\S\n]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)

    if selected == "single_line":
        cleaned = re.sub(r"\n+", " ", cleaned)
        if collapse_spaces:
            cleaned = re.sub(r" +", " ", cleaned)
    elif selected == "remove":
        cleaned = cleaned.replace("\n", "")
        if collapse_spaces:
            cleaned = re.sub(r" +", " ", cleaned)
    elif selected == "canonical_multiline":
        # Preserve a paragraph boundary (two newlines), while removing repeated
        # blank rows and whitespace-only lines.
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip() if trim else cleaned


def canonicalize_missing_token(
    token: str,
    *,
    case_sensitive: bool = False,
    accent_sensitive: bool = False,
    strip_before_match: bool = True,
) -> str:
    """Return a stable representation used to compare missing-value tokens."""

    if not isinstance(token, str):
        raise TypeError("token must be a string")
    leading_space = not strip_before_match and bool(token[:1].isspace())
    trailing_space = not strip_before_match and bool(token[-1:].isspace())
    canonical = normalize_whitespace(
        token,
        line_breaks="space",
        trim=strip_before_match,
    )
    canonical = canonical.translate(str.maketrans("‐‑‒–—−", "------"))
    if not case_sensitive:
        canonical = canonical.casefold()
    if not accent_sensitive:
        canonical = canonical.replace("đ", "d").replace("Đ", "D")
        canonical = "".join(
            char
            for char in unicodedata.normalize("NFD", canonical)
            if unicodedata.category(char) != "Mn"
        )
    # N/A, n.a., n-a, and internal whitespace variants compare identically.
    # When stripping is disabled, retain explicit edge markers so `` unknown ``
    # does not silently match the token ``unknown``.
    canonical = re.sub(r"[\s._/\\-]+", "", canonical)
    return (" " if leading_space else "") + canonical + (" " if trailing_space else "")


@lru_cache(maxsize=64)
def _canonical_missing_tokens(
    tokens: tuple[str, ...],
    case_sensitive: bool,
    accent_sensitive: bool,
    strip_before_match: bool,
) -> frozenset[str]:
    return frozenset(
        canonicalize_missing_token(
            item,
            case_sensitive=case_sensitive,
            accent_sensitive=accent_sensitive,
            strip_before_match=strip_before_match,
        )
        for item in tokens
    )


def is_missing(
    value: object,
    tokens: Iterable[str] | None = None,
    *,
    case_sensitive: bool = False,
    accent_sensitive: bool = False,
    strip_before_match: bool = True,
) -> bool:
    """Return whether *value* is null-like or a configured missing token.

    ``None``, NaN/NaT-like scalar values, empty strings, and the default English
    and Vietnamese tokens are recognized.  Passing ``tokens`` replaces the
    default token set.  Array-like objects are safely treated as non-missing.
    """

    if value is None:
        return True
    if not isinstance(value, str):
        try:
            unequal_to_self = value != value
            if bool(unequal_to_self):
                return True
        except (TypeError, ValueError):
            # pandas.NA has an intentionally ambiguous truth value.
            value_type = type(value)
            if value_type.__name__ in {"NAType", "NaTType"} and value_type.__module__.startswith(
                ("pandas", "numpy")
            ):
                return True
        return False

    selected_tokens = DEFAULT_MISSING_TOKENS if tokens is None else tokens
    if isinstance(selected_tokens, str):
        selected_tokens = (selected_tokens,)
    token_set = _canonical_missing_tokens(
        tuple(selected_tokens),
        case_sensitive,
        accent_sensitive,
        strip_before_match,
    )
    return canonicalize_missing_token(
        value,
        case_sensitive=case_sensitive,
        accent_sensitive=accent_sensitive,
        strip_before_match=strip_before_match,
    ) in token_set


def normalize_missing(
    value: object,
    replacement: object = None,
    tokens: Iterable[str] | None = None,
    *,
    case_sensitive: bool = False,
    accent_sensitive: bool = False,
    strip_before_match: bool = True,
) -> object:
    """Replace a recognized missing scalar; otherwise return it unchanged."""

    if is_missing(
        value,
        tokens,
        case_sensitive=case_sensitive,
        accent_sensitive=accent_sensitive,
        strip_before_match=strip_before_match,
    ):
        return replacement
    return value


_ASCII_LOCAL_EMAIL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.!#$%&'*+/=?^_`{|}~-"
)


def normalize_email(
    value: str,
    *,
    lowercase_local: bool = False,
    idna_domain: bool = True,
) -> str | None:
    """Normalize a practical email address, returning ``None`` when invalid.

    Surrounding whitespace, ``mailto:``, full-width separators, and accidental
    spaces around ``@``/``.`` are fixed.  The domain is lowercased and converted
    to offline IDNA form by default.  The local part keeps its case unless
    ``lowercase_local=True`` because it is technically case-sensitive.
    """

    if not isinstance(value, str):
        return None
    email = normalize_unicode(remove_invisible_chars(value)).strip()
    if email[:7].casefold() == "mailto:":
        email = email[7:].strip()
    if email.startswith("<") and email.endswith(">"):
        email = email[1:-1].strip()
    email = email.translate(str.maketrans("＠。．｡", "@..."))
    email = re.sub(r"\s*@\s*", "@", email)
    email = re.sub(r"\s*\.\s*", ".", email)

    if email.count("@") != 1 or any(char.isspace() for char in email):
        return None
    local, domain = email.rsplit("@", 1)
    if (
        not local
        or len(local.encode("utf-8")) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
    ):
        return None

    for char in local:
        if char.isascii():
            if char not in _ASCII_LOCAL_EMAIL_CHARS:
                return None
        elif unicodedata.category(char)[0] not in {"L", "M", "N"}:
            return None

    domain = domain.rstrip()  # do not silently remove a meaningful trailing dot
    if not domain or domain.startswith(".") or domain.endswith(".") or ".." in domain:
        return None
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None

    labels = ascii_domain.split(".")
    if any(
        not label
        or len(label.encode("ascii", "ignore")) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label, flags=re.IGNORECASE)
        for label in labels
    ):
        return None

    if lowercase_local:
        local = local.lower()
    normalized_domain = ascii_domain if idna_domain else normalize_unicode(domain).lower()
    result = f"{local}@{normalized_domain}"
    return result if len(result.encode("utf-8")) <= 254 else None


def _ascii_digits(value: str) -> str:
    output: list[str] = []
    for char in value:
        try:
            output.append(str(unicodedata.decimal(char)))
        except (TypeError, ValueError):
            output.append(char)
    return "".join(output)


def normalize_phone(
    value: str | int,
    *,
    country_code: str | None = "84",
    default_country: str | None = None,
    keep_extension: bool = False,
    min_digits: int = 8,
    max_digits: int = 15,
) -> str | None:
    """Normalize a phone number, using Vietnamese E.164 form when possible.

    Local numbers beginning with ``0`` become ``+84...`` by default; ``00``
    international prefixes become ``+``.  Numbers without a recognizable
    trunk/country prefix remain digits-only rather than having a country guessed.
    Formatting noise is removed, while unexpected letters cause ``None``.
    ``default_country='VN'`` is a keyword-compatible alias for country code 84.
    """

    if isinstance(value, bool) or not isinstance(value, (str, Integral)):
        return None
    if min_digits < 1 or max_digits < min_digits:
        raise ValueError("invalid min_digits/max_digits")

    phone = _ascii_digits(str(value if isinstance(value, str) else int(value)))
    phone = normalize_unicode(remove_invisible_chars(phone)).strip()
    if phone[:4].casefold() == "tel:":
        phone = phone[4:].strip()

    extension: str | None = None
    extension_match = re.search(
        r"(?:ext\.?|x|máy\s*lẻ|may\s*le)\s*[:.]?\s*(\d{1,6})\s*$",
        phone,
        flags=re.IGNORECASE,
    )
    if extension_match:
        extension = extension_match.group(1)
        phone = phone[: extension_match.start()].rstrip()

    if not re.fullmatch(r"[+\d\s()./\-]+", phone) or phone.count("+") > 1:
        return None
    compact = re.sub(r"[\s()./\-]", "", phone)
    if "+" in compact and not compact.startswith("+"):
        return None
    if compact.startswith("00"):
        compact = "+" + compact[2:]

    if default_country is not None:
        country_alias = normalize_unicode(default_country).strip().casefold()
        if country_alias in {"vn", "vietnam", "việt nam", "viet nam", "+84", "0084", "84"}:
            country_code = "84"
        elif country_alias in {"", "none"}:
            country_code = None
        else:
            raise ValueError("only default_country='VN' is currently supported")

    normalized_country: str | None = None
    if country_code is not None:
        normalized_country = re.sub(r"^(?:\+|00)", "", _ascii_digits(country_code).strip())
        if not normalized_country.isdigit():
            raise ValueError("country_code must contain digits only")

    if compact.startswith("+"):
        digits = compact[1:]
        if normalized_country and digits.startswith(normalized_country + "0"):
            digits = normalized_country + digits[len(normalized_country) + 1 :]
        normalized = "+" + digits
    elif normalized_country and compact.startswith("0"):
        normalized = "+" + normalized_country + compact[1:]
    elif (
        normalized_country
        and compact.startswith(normalized_country)
        and len(compact) >= len(normalized_country) + min_digits
    ):
        normalized = "+" + compact
    else:
        normalized = compact

    digits_only = normalized.lstrip("+")
    if not digits_only.isdigit() or not min_digits <= len(digits_only) <= max_digits:
        return None
    if keep_extension and extension:
        return f"{normalized} x{extension}"
    return normalized


def _coerce_decimal_scalar(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, Integral):
        return Decimal(int(value))
    if isinstance(value, Real):
        numeric_value = float(value)
        if numeric_value != numeric_value or numeric_value in {float("inf"), float("-inf")}:
            return None
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    return None


def _normalize_number_separators(
    number: str,
    decimal_comma: bool,
    *,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> str | None:
    if decimal_separator is not None or thousands_separator is not None:
        decimal = decimal_separator if decimal_separator is not None else (
            "," if decimal_comma else "."
        )
        thousands = thousands_separator or ""
        if decimal not in {",", "."}:
            raise ValueError("decimal_separator must be ',' or '.'")
        if thousands not in {",", ".", " "}:
            raise ValueError("thousands_separator must be ',', '.', space, or empty")
        if thousands and decimal == thousands:
            raise ValueError("decimal_separator and thousands_separator must differ")

        normalized = number.strip()
        if not normalized:
            return None
        allowed = {decimal, thousands} - {""}
        if any(char in ",." and char not in allowed for char in normalized):
            return None
        if re.search(r"\s", normalized) and thousands != " ":
            # Grouped spaces are unambiguous and common in Vietnamese exports,
            # so accept them as an alternate grouping glyph without guessing a
            # dot/comma meaning.  Mixing space groups with another thousands
            # glyph remains invalid.
            escaped_decimal = re.escape(decimal)
            if thousands and thousands in normalized:
                return None
            if not re.fullmatch(
                rf"\d{{1,3}}(?:\s+\d{{3}})+(?:{escaped_decimal}\d+)?",
                normalized,
            ):
                return None
            normalized = re.sub(r"\s+", "", normalized)
        elif thousands == " ":
            normalized = re.sub(r"\s+", " ", normalized)

        if normalized.count(decimal) > 1:
            return None
        if decimal in normalized:
            integer_part, fractional_part = normalized.rsplit(decimal, 1)
            if not fractional_part.isdigit() or not fractional_part:
                return None
        else:
            integer_part, fractional_part = normalized, None

        if thousands:
            groups = integer_part.split(thousands)
            if len(groups) > 1:
                if (
                    not groups[0].isdigit()
                    or not 1 <= len(groups[0]) <= 3
                    or any(not group.isdigit() or len(group) != 3 for group in groups[1:])
                ):
                    return None
                integer_part = "".join(groups)
        if not integer_part.isdigit():
            return None
        return integer_part + ("." + fractional_part if fractional_part is not None else "")

    # Space-separated thousands are accepted only with valid 3-digit groups.
    if re.search(r"\s", number):
        normalized_spaces = re.sub(r"\s+", " ", number.strip())
        if not re.fullmatch(r"\d{1,3}(?: \d{3})+(?:[.,]\d+)?", normalized_spaces):
            return None
        number = normalized_spaces.replace(" ", "")

    if not number or not re.fullmatch(r"[0-9.,]+", number):
        return None

    dot_count = number.count(".")
    comma_count = number.count(",")
    if dot_count and comma_count:
        decimal_separator = "." if number.rfind(".") > number.rfind(",") else ","
        grouping_separator = "," if decimal_separator == "." else "."
        if number.count(decimal_separator) != 1:
            return None
        integer_part, fractional_part = number.rsplit(decimal_separator, 1)
        groups = integer_part.split(grouping_separator)
        if (
            not fractional_part.isdigit()
            or not groups[0].isdigit()
            or not 1 <= len(groups[0]) <= 3
            or any(len(group) != 3 or not group.isdigit() for group in groups[1:])
        ):
            return None
        return "".join(groups) + "." + fractional_part

    separator = "." if dot_count else "," if comma_count else None
    if separator is None:
        return number if number.isdigit() else None

    parts = number.split(separator)
    if len(parts) > 2:
        if (
            parts[0].isdigit()
            and 1 <= len(parts[0]) <= 3
            and all(part.isdigit() and len(part) == 3 for part in parts[1:])
        ):
            return "".join(parts)
        return None

    integer_part, fractional_part = parts
    if not fractional_part.isdigit() or (integer_part and not integer_part.isdigit()):
        return None

    preferred_decimal = "," if decimal_comma else "."
    if separator == preferred_decimal:
        return (integer_part or "0") + "." + fractional_part

    # The locale's grouping separator is considered grouping only for the
    # unambiguous x.xxx / xx.xxx / xxx.xxx shape; otherwise it is a decimal.
    if integer_part and 1 <= len(integer_part) <= 3 and len(fractional_part) == 3:
        return integer_part + fractional_part
    return (integer_part or "0") + "." + fractional_part


def parse_vietnamese_number(
    value: object,
    *,
    decimal_comma: bool = True,
    percent_as_fraction: bool = False,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal | None:
    """Parse a conservatively formatted number into an exact ``Decimal``.

    Vietnamese forms such as ``1.234,56`` and ``1 234 567,89`` are accepted.
    With the default locale, a single comma is decimal while a single dot with
    exactly three trailing digits is a thousands separator.  Ambiguous or
    malformed grouping returns ``None``.  A percent sign is accepted only when
    ``percent_as_fraction=True`` and is then divided by 100.
    """

    scalar = _coerce_decimal_scalar(value)
    if scalar is not None:
        return scalar
    if not isinstance(value, str) or is_missing(value):
        return None

    number = _ascii_digits(normalize_whitespace(value, line_breaks="space", trim=True))
    number = number.translate(str.maketrans("−–—﹣", "----"))

    negative_parentheses = number.startswith("(") and number.endswith(")")
    if negative_parentheses:
        number = number[1:-1].strip()
    elif "(" in number or ")" in number:
        return None

    sign = 1
    if number.startswith(("+", "-")):
        if number[0] == "-":
            sign = -1
        number = number[1:].strip()
    if negative_parentheses:
        if sign == -1:
            return None
        sign = -1

    has_percent = number.endswith("%")
    if has_percent:
        if not percent_as_fraction:
            return None
        number = number[:-1].strip()
    if "%" in number:
        return None

    canonical = _normalize_number_separators(
        number,
        decimal_comma,
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
    )
    if canonical is None:
        return None
    try:
        parsed = Decimal(canonical)
    except InvalidOperation:
        return None
    if sign < 0:
        parsed = -parsed
    if has_percent:
        parsed /= Decimal(100)
    return parsed


_CURRENCY_WORD_RE = re.compile(
    r"(?<![^\W\d_])(?:vnd|vnđ|đồng|dong|usd|eur|gbp|jpy|cny|rmb)(?![^\W\d_])",
    flags=re.IGNORECASE,
)
_VND_MARKER_RE = re.compile(
    r"₫|(?<![^\W\d_])(?:vnd|vnđ|đồng|dong|đ)(?![^\W\d_])",
    flags=re.IGNORECASE,
)
_MULTIPLIERS = {
    "k": Decimal(1_000),
    "nghìn": Decimal(1_000),
    "nghin": Decimal(1_000),
    "ngàn": Decimal(1_000),
    "ngan": Decimal(1_000),
    "tr": Decimal(1_000_000),
    "triệu": Decimal(1_000_000),
    "trieu": Decimal(1_000_000),
    "tỷ": Decimal(1_000_000_000),
    "tỉ": Decimal(1_000_000_000),
    "ty": Decimal(1_000_000_000),
    "ti": Decimal(1_000_000_000),
}
_MULTIPLIER_RE = re.compile(
    r"(nghìn|nghin|ngàn|ngan|triệu|trieu|tỷ|tỉ|ty|ti|tr|k)\s*$",
    flags=re.IGNORECASE,
)


def _normalize_currency_code(value: str) -> str:
    aliases = {"VNĐ": "VND", "Đ": "VND", "RMB": "CNY"}
    code = normalize_whitespace(value, line_breaks="space", trim=True).upper()
    code = aliases.get(code, code)
    if code not in {"VND", "USD", "EUR", "GBP", "JPY", "CNY"}:
        raise ValueError(f"unsupported expected currency: {value!r}")
    return code


def _detect_currency_markers(value: str, expected: str | None) -> set[str]:
    markers: set[str] = set()
    if _VND_MARKER_RE.search(value):
        markers.add("VND")
    for code in ("USD", "EUR", "GBP", "JPY", "CNY", "RMB"):
        if re.search(rf"(?<![^\W\d_]){code}(?![^\W\d_])", value, re.IGNORECASE):
            markers.add("CNY" if code == "RMB" else code)
    if "$" in value:
        markers.add("USD")
    if "€" in value:
        markers.add("EUR")
    if "£" in value:
        markers.add("GBP")
    if "¥" in value:
        markers.add(expected if expected in {"JPY", "CNY"} else "JPY/CNY")
    return markers


def parse_vietnamese_currency(
    value: object,
    *,
    decimal_comma: bool = True,
    expected_currency: str | None = None,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal | None:
    """Parse a Vietnamese-style currency string into an exact ``Decimal``.

    Currency codes/symbols may be before or after the amount.  The common
    suffixes ``k``, ``nghìn/ngàn``, ``tr/triệu``, and ``tỷ/tỉ`` are supported.
    No exchange-rate conversion is attempted, and malformed mixed text returns
    ``None``.
    """

    scalar = _coerce_decimal_scalar(value)
    if scalar is not None:
        return scalar
    if not isinstance(value, str) or is_missing(value):
        return None

    amount = normalize_whitespace(value, line_breaks="space", trim=True)
    expected = (
        _normalize_currency_code(expected_currency)
        if expected_currency is not None
        else None
    )
    currency_markers = _detect_currency_markers(amount, expected)
    if len(currency_markers) > 1:
        return None
    if expected is not None and currency_markers and expected not in currency_markers:
        return None
    has_grouping_currency_marker = bool(currency_markers & {"VND", "USD"})
    amount = _CURRENCY_WORD_RE.sub(" ", amount)
    amount = re.sub(r"[₫đ$€£¥]", " ", amount, flags=re.IGNORECASE)
    amount = normalize_whitespace(amount, line_breaks="space", trim=True)

    negative_parentheses = amount.startswith("(") and amount.endswith(")")
    if negative_parentheses:
        amount = amount[1:-1].strip()
    elif "(" in amount or ")" in amount:
        return None

    multiplier = Decimal(1)
    multiplier_match = _MULTIPLIER_RE.search(amount)
    if multiplier_match:
        multiplier = _MULTIPLIERS[multiplier_match.group(1).casefold()]
        amount = amount[: multiplier_match.start()].strip()

    # Exports and bank files often use ``850,000 VND`` even though ordinary
    # Vietnamese decimals use commas.  An explicit VND marker makes a lone
    # comma followed by three digits a strong thousands signal.  Other shapes
    # (for example ``12,50 VND``) remain decimal under the general parser.
    amount_decimal_comma = decimal_comma
    if has_grouping_currency_marker and amount.count(",") == 1 and "." not in amount:
        amount_decimal_comma = False
    explicit_decimal = decimal_separator
    explicit_thousands = thousands_separator
    # An explicit currency marker is not allowed to override an explicitly
    # configured locale.  The legacy heuristic is retained only when separator
    # arguments are omitted.
    if explicit_decimal is None and explicit_thousands is None:
        parsed = parse_vietnamese_number(amount, decimal_comma=amount_decimal_comma)
    else:
        parsed = parse_vietnamese_number(
            amount,
            decimal_comma=amount_decimal_comma,
            decimal_separator=explicit_decimal,
            thousands_separator=explicit_thousands,
        )
    if parsed is None:
        return None
    if negative_parentheses:
        if parsed < 0:
            return None
        parsed = -parsed
    return parsed * multiplier


__all__ = [
    "DEFAULT_MISSING_TOKENS",
    "LineBreakMode",
    "MojibakeCandidate",
    "MojibakeRepairResult",
    "WhitespaceMode",
    "analyze_mojibake",
    "canonicalize_missing_token",
    "is_missing",
    "normalize_email",
    "normalize_missing",
    "normalize_phone",
    "normalize_unicode",
    "normalize_whitespace",
    "parse_vietnamese_currency",
    "parse_vietnamese_number",
    "remove_invisible_chars",
    "repair_mojibake",
]
