from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ManifestError
from .io import load_json, safe_relative_path, sha256_file
from .rights import (
    RightsReport,
    validate_recipe_publication_rights,
    validate_rights,
)


SCHEMA = "sonic-material-kit/v1"
SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?$")
KIT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")
MAX_FILES = 512
MAX_TOTAL_BYTES = 512 * 1024 * 1024
COVERAGE_STATES = {"verified", "fallback", "unsupported"}
AUDIO_EXTENSIONS = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".pcm",
    ".wav",
}


@dataclass(frozen=True)
class KitReport:
    manifest_path: Path
    kit_id: str
    version: str
    file_count: int
    total_bytes: int
    rights: RightsReport
    profile: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "kit_id": self.kit_id,
            "version": self.version,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "profile": self.profile,
            "status": "validated",
        }


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{label} must be a non-empty string")
    return value.strip()


def validate_kit(
    manifest_path: Path,
    *,
    profile: str = "community",
    rights_target: str = "material-kit",
) -> KitReport:
    manifest_path = manifest_path.resolve()
    root = manifest_path.parent
    data = load_json(manifest_path)
    if data.get("schema") != SCHEMA:
        raise ManifestError(f"kit schema must be {SCHEMA!r}")
    kit_id = _text(data.get("kit_id"), "kit_id")
    if not KIT_ID_RE.fullmatch(kit_id):
        raise ManifestError(f"kit_id must be a stable lowercase namespace: {kit_id!r}")
    version = _text(data.get("version"), "version")
    if not SEMVER_RE.fullmatch(version):
        raise ManifestError(f"version must be semantic: {version!r}")
    if data.get("status") not in {"experimental", "supported"}:
        raise ManifestError("status must be experimental or supported")
    rights_value = _text(data.get("rights_manifest"), "rights_manifest")
    rights_path = safe_relative_path(root, rights_value, label="rights_manifest")
    if not rights_path.is_file() or rights_path.is_symlink():
        raise ManifestError(f"missing rights manifest: {rights_value}")
    files = data.get("files")
    if not isinstance(files, list) or not files:
        raise ManifestError("kit files must be a non-empty exact inventory")
    if len(files) > MAX_FILES:
        raise ManifestError(f"kit has {len(files)} files; limit is {MAX_FILES}")
    declared: dict[str, tuple[str, int]] = {}
    total_bytes = 0
    for index, item in enumerate(files):
        label = f"files[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{label} must be an object")
        rel = _text(item.get("path"), f"{label}.path").replace("\\", "/")
        if rel in declared:
            raise ManifestError(f"duplicate file inventory entry: {rel}")
        path = safe_relative_path(root, rel, label=f"{label}.path")
        if not path.is_file() or path.is_symlink():
            raise ManifestError(f"missing or unsafe kit file: {rel}")
        expected_sha = _text(item.get("sha256"), f"{label}.sha256").lower()
        actual_sha = sha256_file(path)
        if expected_sha != actual_sha:
            raise ManifestError(
                f"kit hash mismatch for {rel}: expected {expected_sha}, got {actual_sha}"
            )
        expected_bytes = item.get("bytes")
        actual_bytes = path.stat().st_size
        if not isinstance(expected_bytes, int) or expected_bytes != actual_bytes:
            raise ManifestError(
                f"kit byte count mismatch for {rel}: expected {expected_bytes}, got {actual_bytes}"
            )
        total_bytes += actual_bytes
        declared[rel] = (actual_sha, actual_bytes)
    if total_bytes > MAX_TOTAL_BYTES:
        raise ManifestError(f"kit size {total_bytes} exceeds {MAX_TOTAL_BYTES} bytes")
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.resolve() != manifest_path
    }
    if actual_files != set(declared):
        missing = sorted(set(declared) - actual_files)
        unexpected = sorted(actual_files - set(declared))
        raise ManifestError(
            f"kit inventory is not exact; missing={missing}, unexpected={unexpected}"
        )
    rights = validate_rights(rights_path, root=root, target=rights_target)
    declared_audio = {
        rel for rel in declared if Path(rel).suffix.lower() in AUDIO_EXTENSIONS
    }
    rights_files = {asset.file.replace("\\", "/") for asset in rights.assets}
    missing_rights = sorted(declared_audio - rights_files)
    unpackaged_rights = sorted(rights_files - set(declared))
    if missing_rights or unpackaged_rights:
        raise ManifestError(
            "kit audio rights coverage is not exact; "
            f"missing_rights={missing_rights}, unpackaged_rights={unpackaged_rights}"
        )
    coverage = data.get("coverage")
    if not isinstance(coverage, list) or not coverage:
        raise ManifestError("coverage must explicitly mark verified/fallback/unsupported pairs")
    coverage_keys: set[tuple[str, str, str]] = set()
    for index, item in enumerate(coverage):
        label = f"coverage[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{label} must be an object")
        event = _text(item.get("event"), f"{label}.event")
        source = _text(item.get("source"), f"{label}.source")
        target = _text(item.get("target"), f"{label}.target")
        state = item.get("state")
        if state not in COVERAGE_STATES:
            raise ManifestError(f"invalid {label}.state: {state!r}")
        key = (event, source, target)
        if key in coverage_keys:
            raise ManifestError(f"duplicate coverage selector: {key}")
        coverage_keys.add(key)
        recipe_value = item.get("recipe")
        if state == "verified":
            recipe_path = safe_relative_path(
                root, _text(recipe_value, f"{label}.recipe"), label=f"{label}.recipe"
            )
            if not recipe_path.is_file():
                raise ManifestError(f"verified coverage is missing recipe: {recipe_value}")
            recipe = load_json(recipe_path)
            if recipe.get("schema") != "sonic-impact-recipe/v1":
                raise ManifestError(
                    f"verified coverage has an unsupported recipe schema: {recipe_value}"
                )
            if rights_target != "local-preview":
                publication = validate_recipe_publication_rights(recipe.get("rights"))
                if not publication["publication_eligible"]:
                    raise ManifestError(
                        f"verified coverage is not publication-eligible: {recipe_value}"
                    )
        elif recipe_value is not None:
            raise ManifestError(f"{label}.recipe is only valid for verified coverage")
    if profile not in {"community", "official-cc0"}:
        raise ManifestError("profile must be community or official-cc0")
    if profile == "official-cc0":
        for asset in rights.assets:
            if asset.intake_tier not in {"own", "cc0"}:
                raise ManifestError(
                    f"official-cc0 rejects intake tier {asset.intake_tier}: {asset.asset_id}"
                )
            if asset.license_spdx != "CC0-1.0":
                raise ManifestError(
                    f"official-cc0 requires CC0-1.0 outbound media: {asset.asset_id}"
                )
    return KitReport(
        manifest_path=manifest_path,
        kit_id=kit_id,
        version=version,
        file_count=len(files),
        total_bytes=total_bytes,
        rights=rights,
        profile=profile,
    )
