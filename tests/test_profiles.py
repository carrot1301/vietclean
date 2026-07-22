import pytest

from vietclean.profiles import (
    deep_merge,
    get_profile,
    list_profiles,
    merge_profile_config,
    normalize_column_name,
    resolve_column_type,
    resolve_semantic_type,
    resolve_semantic_types,
)


def test_lists_five_canonical_profiles_in_stable_order() -> None:
    assert list_profiles() == [
        "generic",
        "fnb",
        "finance",
        "ecommerce",
        "marketing",
    ]


@pytest.mark.parametrize(
    ("profile", "vietnamese_name", "english_name", "expected_vi", "expected_en"),
    [
        ("generic", "Số điện thoại", "customer_email", "phone", "email"),
        ("fnb", "Giá món", "reservation_time", "currency", "datetime"),
        ("finance", "Số tài khoản", "interest_rate", "identifier", "percentage"),
        ("ecommerce", "Mã vận đơn", "shipping_fee", "identifier", "currency"),
        ("marketing", "Lượt hiển thị", "conversion_rate", "integer", "percentage"),
    ],
)
def test_resolves_vietnamese_and_english_names_for_each_profile(
    profile: str,
    vietnamese_name: str,
    english_name: str,
    expected_vi: str,
    expected_en: str,
) -> None:
    assert resolve_semantic_type(vietnamese_name, profile) == expected_vi
    assert resolve_semantic_type(english_name, profile) == expected_en


def test_unknown_and_ambiguous_names_are_not_guessed() -> None:
    assert resolve_semantic_type("cột nghiệp vụ riêng của công ty", "generic") is None
    overrides = {
        "column_types": {
            "text": {"aliases": ["shared"]},
            "identifier": {"aliases": ["shared"]},
        }
    }
    assert resolve_semantic_type("shared", "generic", overrides=overrides) is None


def test_get_profile_supports_aliases_and_returns_a_deep_copy() -> None:
    marketing = get_profile("mkt")
    ecommerce = get_profile("online_shopping")

    assert marketing["name"] == "marketing"
    assert ecommerce["name"] == "ecommerce"

    marketing["defaults"]["missing"]["tokens"].append("private-token")
    assert "private-token" not in get_profile("marketing")["defaults"]["missing"]["tokens"]


def test_json_override_deep_merges_mappings_and_replaces_lists() -> None:
    profile = get_profile(
        "generic",
        overrides={
            "defaults": {
                "missing": {"tokens": ["?"]},
                "duplicates": {"enabled": True},
            }
        },
    )

    assert profile["defaults"]["missing"]["tokens"] == ["?"]
    assert profile["defaults"]["missing"]["case_sensitive"] is False
    assert profile["defaults"]["duplicates"] == {
        "enabled": True,
        "subset": None,
        "keep": "first",
    }


def test_profile_public_helpers_validate_inputs_and_batch_resolution() -> None:
    assert normalize_column_name("OrderID / Mã Đơn") == "order_id_ma_don"
    assert normalize_column_name(123) == ""
    with pytest.raises(TypeError, match="base"):
        deep_merge([], {})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="override"):
        deep_merge({}, [])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="profile name"):
        get_profile(1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="choose one"):
        get_profile("missing-profile")
    with pytest.raises(TypeError, match="profile"):
        merge_profile_config(1, {})  # type: ignore[arg-type]

    merged = merge_profile_config("generic", {"description": "custom"})
    assert merged["description"] == "custom"
    assert resolve_column_type("email") == "email"
    assert resolve_semantic_types(
        ["email", "unknown business field"], include_unknown=False
    ) == {"email": "email"}


def test_profile_resolver_handles_malformed_or_ambiguous_custom_rules_safely() -> None:
    assert resolve_semantic_type("", "generic") is None
    assert resolve_semantic_type("x", {"column_types": []}) is None
    assert (
        resolve_semantic_type(
            "shared",
            {
                "column_types": {
                    "text": {"patterns": r"shared"},
                    "identifier": {"patterns": [r"sha.*"]},
                    "unsupported": {"aliases": ["shared"]},
                }
            },
        )
        is None
    )
    assert resolve_semantic_type("mail", {"column_types": {"email": {"aliases": "mail"}}}) == "email"
    with pytest.raises(ValueError, match="invalid"):
        resolve_semantic_type(
            "x",
            {"column_types": {"text": {"patterns": "["}}},
        )
    with pytest.raises(TypeError, match="profile"):
        resolve_semantic_type("x", 1)  # type: ignore[arg-type]
