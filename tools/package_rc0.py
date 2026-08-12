#!/usr/bin/env python3
"""Build and verify deterministic SonicMatter Gate A release-candidate archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
PRIVATE_PREFIXES = ("spec/", "planning-private/", ".local/")
RIGHTS_ACTIONS = (
    "local_playback",
    "game_distribution_unchanged",
    "baked_derivative_publication",
    "ml_parameter_fitting",
    "evaluation",
    "private_embedding",
    "index_redistribution",
)
INVENTORY_ORACLES = {
    "addon": "tests/runtime_v2/golden/addon_inventory_v1.json",
    "demo": "tests/runtime_v2/golden/demo_inventory_v1.json",
}


class AuditError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_bytes(relative_path: str) -> bytes:
    path = ROOT / relative_path
    if not path.is_file():
        raise AuditError(f"required source file is missing: {relative_path}")
    if path.is_symlink():
        raise AuditError(f"package sources may not be symlinks: {relative_path}")
    return path.read_bytes()


def add_file(files: dict[str, bytes], archive_path: str, source_path: str) -> None:
    normalized = PurePosixPath(archive_path).as_posix()
    if normalized.startswith("/") or ".." in PurePosixPath(normalized).parts:
        raise AuditError(f"unsafe archive path: {archive_path}")
    if normalized in files:
        raise AuditError(f"duplicate archive path: {normalized}")
    files[normalized] = read_bytes(source_path)


def add_tree(files: dict[str, bytes], source_root: str, archive_root: str) -> None:
    root_path = ROOT / source_root
    if not root_path.is_dir():
        raise AuditError(f"required source directory is missing: {source_root}")
    for path in sorted(root_path.rglob("*")):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise AuditError(f"package sources may not be symlinks: {path}")
        relative = path.relative_to(root_path).as_posix()
        add_file(
            files,
            PurePosixPath(archive_root, relative).as_posix(),
            path.relative_to(ROOT).as_posix(),
        )


def plugin_version() -> str:
    plugin = read_bytes("addons/sonic_matter/plugin.cfg").decode("utf-8")
    match = re.search(r'^version="([^"]+)"$', plugin, re.MULTILINE)
    if match is None:
        raise AuditError("addons/sonic_matter/plugin.cfg has no version")
    version = match.group(1)
    if re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.-]*", version) is None:
        raise AuditError(f"unsafe package version: {version}")
    return version


def audit_private_paths() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    tracked = [
        item.decode("utf-8")
        for item in result.stdout.split(b"\0")
        if item
    ]
    leaked = [
        path
        for path in tracked
        if any(path == prefix[:-1] or path.startswith(prefix) for prefix in PRIVATE_PREFIXES)
    ]
    if leaked:
        raise AuditError("private files are tracked: " + ", ".join(sorted(leaked)))


def validate_rights_manifest(relative_path: str, allow_empty: bool = False) -> dict:
    payload = json.loads(read_bytes(relative_path))
    if payload.get("schema_version") != 2:
        raise AuditError(f"{relative_path}: schema_version must be 2")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise AuditError(f"{relative_path}: assets must be an array")
    if not assets and not allow_empty:
        raise AuditError(f"{relative_path}: distributable demo has no rights records")

    for asset in assets:
        asset_id = asset.get("asset_id", "<missing>")
        source = asset.get("source", {})
        integrity = asset.get("integrity", {})
        license_record = asset.get("license", {})
        rights = asset.get("rights", {})

        source_path = source.get("path")
        expected_hash = str(integrity.get("sha256", "")).lower()
        if integrity.get("algorithm") != "sha256" or len(expected_hash) != 64:
            raise AuditError(f"{relative_path}: {asset_id} has invalid integrity")
        actual_hash = sha256_bytes(read_bytes(source_path))
        if actual_hash != expected_hash:
            raise AuditError(
                f"{relative_path}: {asset_id} hash mismatch "
                f"(expected {expected_hash}, got {actual_hash})"
            )

        text_path = license_record.get("text_path")
        if not license_record.get("spdx") or not text_path:
            raise AuditError(f"{relative_path}: {asset_id} has incomplete license data")
        read_bytes(text_path)

        for action in RIGHTS_ACTIONS:
            decision = rights.get(action, {})
            value = decision.get("decision")
            evidence = decision.get("evidence")
            if value not in {"allow", "deny"} or not evidence:
                raise AuditError(
                    f"{relative_path}: {asset_id} right {action} "
                    "must be allow|deny with evidence"
                )
    return payload


def audit_source() -> None:
    audit_private_paths()
    repository_manifest = validate_rights_manifest("ASSET_MANIFEST.json")
    example_manifest = validate_rights_manifest(
        "examples/gate_a_3d/asset-rights.json"
    )
    if repository_manifest != example_manifest:
        raise AuditError(
            "ASSET_MANIFEST.json and examples/gate_a_3d/asset-rights.json drifted"
        )
    validate_rights_manifest(
        "packaging/addon/ASSET_MANIFEST.json",
        allow_empty=True,
    )
    read_bytes("THIRD_PARTY_NOTICES.md")


def exact_inventory_records(files: dict[str, bytes]) -> list[dict[str, object]]:
    return [
        {
            "path": path,
            "sha256": sha256_bytes(files[path]),
            "size": len(files[path]),
        }
        for path in sorted(files)
    ]


def assert_exact_inventory(
    label: str,
    expected: list[dict[str, object]],
    actual: list[dict[str, object]],
) -> None:
    if expected == actual:
        return
    expected_by_path = {str(record.get("path")): record for record in expected}
    actual_by_path = {str(record.get("path")): record for record in actual}
    missing = sorted(set(expected_by_path) - set(actual_by_path))
    extra = sorted(set(actual_by_path) - set(expected_by_path))
    changed = sorted(
        path
        for path in set(expected_by_path) & set(actual_by_path)
        if expected_by_path[path] != actual_by_path[path]
    )
    raise AuditError(
        f"{label}: exact inventory drift "
        f"missing={missing} extra={extra} changed={changed}"
    )


def validate_inventory_oracle(
    kind: str,
    files: dict[str, bytes],
    *,
    expected_version: str | None = None,
) -> None:
    relative_path = INVENTORY_ORACLES[kind]
    oracle = json.loads(read_bytes(relative_path))
    if oracle.get("schema_version") != 1:
        raise AuditError(f"{relative_path}: schema_version must be 1")
    if oracle.get("golden_kind") != f"{kind}_inventory_v1":
        raise AuditError(f"{relative_path}: golden kind drifted")
    version = expected_version or plugin_version()
    if oracle.get("release") != version:
        raise AuditError(f"{relative_path}: release does not match expected version")
    if oracle.get("package") != f"sonic-matter-{kind}":
        raise AuditError(f"{relative_path}: package identity drifted")
    expected = oracle.get("records")
    if not isinstance(expected, list):
        raise AuditError(f"{relative_path}: records must be an array")
    assert_exact_inventory(relative_path, expected, exact_inventory_records(files))


def collect_package(kind: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    add_tree(files, "addons/sonic_matter", "addons/sonic_matter")
    add_file(files, "LICENSE", "LICENSE")
    add_file(files, "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md")
    add_file(files, "docs/gate-a-contract.md", "docs/gate-a-contract.md")
    add_file(files, "docs/getting-started.md", "docs/getting-started.md")

    if kind == "addon":
        add_file(files, "README.md", "packaging/addon/README.md")
        add_file(
            files,
            "ASSET_MANIFEST.json",
            "packaging/addon/ASSET_MANIFEST.json",
        )
    elif kind == "demo":
        add_file(files, "README.md", "packaging/demo/README.md")
        add_file(files, "ASSET_MANIFEST.json", "ASSET_MANIFEST.json")
        add_file(files, "project.godot", "packaging/demo/project.godot.template")
        add_tree(files, "examples/gate_a_3d", "examples/gate_a_3d")
        add_tree(files, "tests/gate_a", "tests/gate_a")
    else:
        raise AuditError(f"unknown package kind: {kind}")

    forbidden = [
        path
        for path in files
        if any(path == prefix[:-1] or path.startswith(prefix) for prefix in PRIVATE_PREFIXES)
    ]
    if forbidden:
        raise AuditError("private files entered package: " + ", ".join(forbidden))
    return files


def package_manifest(kind: str, version: str, files: dict[str, bytes]) -> bytes:
    payload = {
        "schema_version": 1,
        "package": f"sonic-matter-{kind}",
        "version": version,
        "files": [
            {
                "path": path,
                "sha256": sha256_bytes(files[path]),
                "size": len(files[path]),
            }
            for path in sorted(files)
        ],
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_archive(kind: str, output_dir: Path) -> Path:
    version = plugin_version()
    files = collect_package(kind)
    validate_inventory_oracle(kind, files)
    files["PACKAGE_MANIFEST.json"] = package_manifest(kind, version, files)

    archive_root = f"sonic-matter-{kind}-{version}"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{archive_root}.zip"
    temporary = output.with_suffix(".zip.tmp")
    if temporary.exists():
        temporary.unlink()

    with zipfile.ZipFile(
        temporary,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for relative_path in sorted(files):
            info = zipfile.ZipInfo(
                PurePosixPath(archive_root, relative_path).as_posix(),
                date_time=FIXED_ZIP_TIME,
            )
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[relative_path])
    os.replace(temporary, output)
    verify_archive(output)
    return output


def verify_archive(path: Path) -> None:
    if not path.is_file():
        raise AuditError(f"archive does not exist: {path}")
    with zipfile.ZipFile(path, "r") as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != len(set(names)):
            raise AuditError(f"{path}: duplicate archive member")
        for name in names:
            member = PurePosixPath(name)
            if member.is_absolute() or ".." in member.parts:
                raise AuditError(f"{path}: unsafe archive member {name}")
            if not member.parts or member.parts[0] in {"", "."}:
                raise AuditError(f"{path}: invalid archive member {name}")
            if len(member.parts) < 2:
                raise AuditError(f"{path}: archive member has no relative path {name}")

        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            raise AuditError(f"{path}: archive must have one root directory")
        root = next(iter(roots))
        relative_names = {
            PurePosixPath(*PurePosixPath(name).parts[1:]).as_posix()
            for name in names
        }
        forbidden = [
            name
            for name in relative_names
            if any(
                name == prefix[:-1] or name.startswith(prefix)
                for prefix in PRIVATE_PREFIXES
            )
        ]
        if forbidden:
            raise AuditError(f"{path}: private paths found: {forbidden}")

        manifest_name = f"{root}/PACKAGE_MANIFEST.json"
        if manifest_name not in names:
            raise AuditError(f"{path}: PACKAGE_MANIFEST.json is missing")
        manifest = json.loads(archive.read(manifest_name))
        if manifest.get("schema_version") != 1:
            raise AuditError(f"{path}: package manifest schema must be 1")
        package_name = manifest.get("package")
        package_kinds = {
            "sonic-matter-addon": "addon",
            "sonic-matter-demo": "demo",
        }
        if package_name not in package_kinds:
            raise AuditError(f"{path}: unknown package identity {package_name!r}")
        kind = package_kinds[package_name]
        version = manifest.get("version")
        if (
            not isinstance(version, str)
            or re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.-]*", version) is None
        ):
            raise AuditError(f"{path}: package version is missing")
        if root != f"{package_name}-{version}":
            raise AuditError(f"{path}: archive root does not match package/version")
        records = manifest.get("files", [])
        if not isinstance(records, list):
            raise AuditError(f"{path}: package files must be an array")
        record_paths = [record.get("path") for record in records if isinstance(record, dict)]
        if (
            len(record_paths) != len(records)
            or any(not isinstance(item, str) or not item for item in record_paths)
            or len(record_paths) != len(set(record_paths))
        ):
            raise AuditError(f"{path}: invalid or duplicate manifest record")
        expected_names = {record["path"] for record in records}
        if relative_names != expected_names | {"PACKAGE_MANIFEST.json"}:
            raise AuditError(f"{path}: package file list does not match manifest")

        actual_files: dict[str, bytes] = {}
        for record in records:
            record_path = record["path"]
            member = PurePosixPath(record_path)
            if member.is_absolute() or ".." in member.parts:
                raise AuditError(f"{path}: unsafe manifest path {record_path}")
            payload = archive.read(f"{root}/{record['path']}")
            if len(payload) != record["size"]:
                raise AuditError(f"{path}: size mismatch for {record['path']}")
            if sha256_bytes(payload) != record["sha256"]:
                raise AuditError(f"{path}: hash mismatch for {record['path']}")
            actual_files[record_path] = payload
        validate_inventory_oracle(
            kind,
            actual_files,
            expected_version=version,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind",
        choices=("addon", "demo", "all"),
        default="all",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "artifacts" / "packages",
    )
    parser.add_argument(
        "--verify",
        type=Path,
        action="append",
        help="verify an existing archive instead of building",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.verify:
            for archive in args.verify:
                verify_archive(archive.resolve())
                print(f"PACKAGE_VERIFY_OK {archive}")
            return 0

        audit_source()
        kinds = ("addon", "demo") if args.kind == "all" else (args.kind,)
        for kind in kinds:
            output = write_archive(kind, args.output_dir.resolve())
            digest = sha256_bytes(output.read_bytes())
            print(f"PACKAGE_BUILD_OK {output} sha256={digest}")
        return 0
    except (AuditError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"PACKAGE_AUDIT_FAILED {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
