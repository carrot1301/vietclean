"""Generate a minimal SPDX 2.3 JSON SBOM from an isolated environment."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import re
from typing import Any


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _spdx_id(name: str) -> str:
    return "SPDXRef-Package-" + re.sub(r"[^A-Za-z0-9.-]", "-", name)


def _license(metadata_map: metadata.PackageMetadata) -> str:
    declared = metadata_map.get("License-Expression") or metadata_map.get("License")
    if declared and re.fullmatch(r"[A-Za-z0-9.+-]+", declared) and declared != "UNKNOWN":
        return declared
    classifiers = metadata_map.get_all("Classifier") or []
    known = {
        "License :: OSI Approved :: MIT License": "MIT",
        "License :: OSI Approved :: Apache Software License": "Apache-2.0",
        "License :: OSI Approved :: BSD License": "BSD-3-Clause",
        "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
    }
    for classifier in classifiers:
        if classifier in known:
            return known[classifier]
    return "NOASSERTION"


def _created_at() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    timestamp = int(epoch) if epoch and epoch.isdigit() else int(datetime.now(timezone.utc).timestamp())
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_sbom(root_package: str, artifact: Path | None = None) -> dict[str, Any]:
    """Build an aggregate SBOM without reading application data or secret values."""

    distributions: dict[str, metadata.Distribution] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if name:
            distributions[_canonical_name(name)] = distribution
    root_name = _canonical_name(root_package)
    if root_name not in distributions:
        raise ValueError(f"Package {root_package!r} chưa được cài trong môi trường SBOM.")

    package_items: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = []
    for name, distribution in sorted(distributions.items()):
        version = distribution.version
        item: dict[str, Any] = {
            "SPDXID": _spdx_id(name),
            "name": name,
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": _license(distribution.metadata),
            "copyrightText": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:pypi/{name}@{version}",
                }
            ],
        }
        if name == root_name and artifact is not None:
            item["checksums"] = [
                {
                    "algorithm": "SHA256",
                    "checksumValue": hashlib.sha256(artifact.read_bytes()).hexdigest(),
                }
            ]
        package_items.append(item)
        for requirement in distribution.requires or []:
            dependency_match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
            if dependency_match is None:
                continue
            dependency = _canonical_name(dependency_match.group(1))
            if dependency in distributions:
                relationships.append(
                    {
                        "spdxElementId": _spdx_id(name),
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": _spdx_id(dependency),
                    }
                )

    fingerprint = hashlib.sha256(
        "\n".join(f"{item['name']}=={item['versionInfo']}" for item in package_items).encode()
    ).hexdigest()
    relationships.insert(
        0,
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": _spdx_id(root_name),
        },
    )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{root_name}-release-environment",
        "documentNamespace": f"https://vietclean.invalid/spdx/{root_name}/{fingerprint}",
        "creationInfo": {
            "created": _created_at(),
            "creators": ["Tool: vietclean-generate-spdx-sbom-1"],
        },
        "packages": package_items,
        "relationships": relationships,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-package", default="vietclean")
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sbom = build_sbom(args.root_package, args.artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
