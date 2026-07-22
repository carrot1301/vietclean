from email import message_from_string
import hashlib
from pathlib import Path
import re
from zipfile import ZipFile

from tools.check_release_governance import active_codeowners, validate_release
from tools.check_release_artifacts import inspect_artifact
from tools.create_hash_lock import build_lock
from tools import generate_spdx_sbom


ROOT = Path(__file__).resolve().parents[1]


def test_all_github_actions_are_pinned_to_full_commit_sha() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows
    for workflow in workflows:
        content = workflow.read_text(encoding="utf-8")
        assert re.search(r"(?m)^permissions:\s*$", content), workflow.name
        for action, reference in re.findall(r"(?m)^\s*uses:\s*([^@\s]+)@([^\s#]+)", content):
            assert re.fullmatch(r"[0-9a-f]{40}", reference), f"{workflow.name}: {action}@{reference}"


def test_release_requires_a_real_codeowner_and_accepts_repository_owner(
    tmp_path: Path,
) -> None:
    assert "carrot1301" in active_codeowners(ROOT / ".github" / "CODEOWNERS")
    assert validate_release(ROOT, "v0.1.0") == []

    (tmp_path / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True)
    (tmp_path / ".github" / "CODEOWNERS").write_text(
        "* @username\n", encoding="utf-8"
    )
    (tmp_path / ".github" / "ISSUE_TEMPLATE" / "config.yml").write_text(
        "blank_issues_enabled: false\n", encoding="utf-8"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "vietclean"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    errors = validate_release(tmp_path, "v0.1.0")
    assert any("CODEOWNERS" in error for error in errors)

    (tmp_path / ".github" / "CODEOWNERS").write_text(
        "* @maintainer-name\n/.github/ @maintainer-name\n", encoding="utf-8"
    )
    assert validate_release(tmp_path, "v0.1.0") == []
    assert validate_release(tmp_path, "release-0.1.0")


def test_hash_lock_is_deterministic_and_contains_actual_wheel_digest(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    wheel = wheelhouse / "example_pkg-1.2.3-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            "example_pkg-1.2.3.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: Example_Pkg\nVersion: 1.2.3\n\n",
        )

    content = build_lock(wheelhouse)

    assert content == build_lock(wheelhouse)
    assert "example-pkg==1.2.3" in content
    assert hashlib.sha256(wheel.read_bytes()).hexdigest() in content


class _FakeDistribution:
    def __init__(self, name: str, version: str, license_name: str, requires=None):
        self.version = version
        self.metadata = message_from_string(
            f"Name: {name}\nVersion: {version}\nLicense-Expression: {license_name}\n\n"
        )
        self.requires = requires or []


def test_spdx_generator_is_deterministic_with_source_date_epoch(monkeypatch, tmp_path: Path) -> None:
    distributions = [
        _FakeDistribution("vietclean", "0.1.0", "MIT", ["pandas>=1.5"]),
        _FakeDistribution("pandas", "2.3.3", "BSD-3-Clause"),
    ]
    monkeypatch.setattr(generate_spdx_sbom.metadata, "distributions", lambda: distributions)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    artifact = tmp_path / "vietclean.whl"
    artifact.write_bytes(b"synthetic wheel fixture")

    first = generate_spdx_sbom.build_sbom("vietclean", artifact)
    second = generate_spdx_sbom.build_sbom("vietclean", artifact)

    assert first == second
    assert first["spdxVersion"] == "SPDX-2.3"
    assert first["creationInfo"]["created"] == "1970-01-01T00:00:00Z"
    packages = {item["name"]: item for item in first["packages"]}
    assert packages["vietclean"]["licenseDeclared"] == "MIT"
    assert packages["vietclean"]["checksums"][0]["algorithm"] == "SHA256"
    assert any(item["relationshipType"] == "DEPENDS_ON" for item in first["relationships"])


def test_issue_template_config_disables_unstructured_public_issues() -> None:
    content = (ROOT / ".github" / "ISSUE_TEMPLATE" / "config.yml").read_text(
        encoding="utf-8"
    )
    assert content.strip() == "blank_issues_enabled: false"


def test_release_artifact_gate_accepts_package_and_rejects_sensitive_members(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "vietclean-0.1.0-py3-none-any.whl"
    with ZipFile(safe, "w") as archive:
        archive.writestr("vietclean/__init__.py", "")
        archive.writestr("vietclean-0.1.0.dist-info/METADATA", "Name: vietclean\n")
    assert inspect_artifact(safe) == []

    unsafe = tmp_path / "unsafe.whl"
    with ZipFile(unsafe, "w") as archive:
        archive.writestr("vietclean/__init__.py", "")
        archive.writestr("vietclean-0.1.0.dist-info/METADATA", "Name: vietclean\n")
        archive.writestr("../.env", "TOKEN=synthetic-not-a-secret")
        archive.writestr("fixtures/customer.xlsx", b"synthetic")
    errors = inspect_artifact(unsafe)
    assert any("path không an toàn" in error for error in errors)
    assert any("data/key artifact" in error for error in errors)
