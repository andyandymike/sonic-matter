from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ManifestError
from .io import load_json, safe_relative_path, sha256_file


SCHEMA = "sonic-material-rights/v1"
RIGHTS_ACTIONS = (
    "local_preview",
    "source_repo_distribution",
    "material_kit_distribution",
    "game_source_distribution",
    "game_binary_embedding",
    "unchanged_redistribution",
    "standalone_baked_audio_distribution",
    "parameter_fitting",
    "evaluation_use",
    "evaluation_stimulus_publication",
    "training",
    "private_embedding",
    "index_redistribution",
)
TARGET_ACTIONS = {
    "local-preview": ("local_preview",),
    "source-repo": ("source_repo_distribution",),
    "material-kit": ("material_kit_distribution",),
    "game-source": ("game_source_distribution",),
    "game-binary": ("game_binary_embedding",),
    "public-bake": ("standalone_baked_audio_distribution",),
    "parameter-fit": ("parameter_fitting",),
    "evaluation": ("evaluation_use",),
    "public-evaluation": ("evaluation_use", "evaluation_stimulus_publication"),
    "training": ("training",),
    "index-release": ("index_redistribution",),
}
INTAKE_TIERS = {"own", "cc0", "cc_by", "embedded_only"}
STATUSES = {"allow", "deny", "unknown"}
STATUS_RANK = {"deny": 0, "unknown": 1, "allow": 2}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]{2,127}$")


@dataclass(frozen=True)
class RightsAsset:
    asset_id: str
    file: str
    sha256: str
    intake_tier: str
    license_spdx: str
    parents: tuple[str, ...]
    actions: dict[str, str]


@dataclass(frozen=True)
class RightsReport:
    manifest_path: Path
    root: Path
    pack_id: str
    assets: tuple[RightsAsset, ...]
    target: str | None

    def asset_for_hash(self, digest: str) -> RightsAsset | None:
        matches = [asset for asset in self.assets if asset.sha256 == digest]
        if len(matches) > 1:
            raise ManifestError(f"multiple rights assets share SHA-256 {digest}")
        return matches[0] if matches else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "pack_id": self.pack_id,
            "asset_count": len(self.assets),
            "target": self.target,
            "status": "validated",
        }


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{label} must be a non-empty string")
    return value.strip()


def _require_sha(value: Any, label: str) -> str:
    digest = _require_text(value, label).lower()
    if not SHA256_RE.fullmatch(digest):
        raise ManifestError(f"{label} must be a lowercase SHA-256")
    return digest


def _validate_action_matrix(
    raw_actions: Any, evidence_ids: set[str], label: str
) -> dict[str, str]:
    if not isinstance(raw_actions, dict):
        raise ManifestError(f"{label}.actions must be an object")
    missing = sorted(set(RIGHTS_ACTIONS) - set(raw_actions))
    extra = sorted(set(raw_actions) - set(RIGHTS_ACTIONS))
    if missing or extra:
        raise ManifestError(
            f"{label}.actions must list every known action; missing={missing}, extra={extra}"
        )
    result: dict[str, str] = {}
    for action in RIGHTS_ACTIONS:
        decision = raw_actions[action]
        if not isinstance(decision, dict):
            raise ManifestError(f"{label}.actions.{action} must be an object")
        status = decision.get("status")
        if status not in STATUSES:
            raise ManifestError(f"{label}.actions.{action}.status is invalid: {status!r}")
        refs = decision.get("evidence_ids")
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ManifestError(f"{label}.actions.{action}.evidence_ids must be a list")
        unknown_refs = sorted(set(refs) - evidence_ids)
        if unknown_refs:
            raise ManifestError(
                f"{label}.actions.{action} references unknown evidence: {unknown_refs}"
            )
        if status in {"allow", "deny"} and not refs:
            raise ManifestError(
                f"{label}.actions.{action}={status} requires evidence"
            )
        conditions = decision.get("conditions", [])
        if not isinstance(conditions, list) or any(
            not isinstance(condition, str) for condition in conditions
        ):
            raise ManifestError(f"{label}.actions.{action}.conditions must be strings")
        result[action] = status
    return result


def _validate_evidence(raw: Any, root: Path, label: str) -> set[str]:
    if not isinstance(raw, list) or not raw:
        raise ManifestError(f"{label}.evidence must be a non-empty list")
    evidence_ids: set[str] = set()
    for index, item in enumerate(raw):
        item_label = f"{label}.evidence[{index}]"
        if not isinstance(item, dict):
            raise ManifestError(f"{item_label} must be an object")
        evidence_id = _require_text(item.get("evidence_id"), f"{item_label}.evidence_id")
        if evidence_id in evidence_ids:
            raise ManifestError(f"duplicate evidence id {evidence_id!r}")
        evidence_ids.add(evidence_id)
        _require_text(item.get("kind"), f"{item_label}.kind")
        _require_text(item.get("captured_at"), f"{item_label}.captured_at")
        path_value = item.get("path")
        url_value = item.get("canonical_url")
        if path_value is None and url_value is None:
            raise ManifestError(f"{item_label} needs retained path or canonical_url")
        if path_value is not None:
            evidence_path = safe_relative_path(root, path_value, label=f"{item_label}.path")
            if not evidence_path.is_file() or evidence_path.is_symlink():
                raise ManifestError(f"missing or unsafe retained evidence: {path_value}")
            expected = _require_sha(item.get("sha256"), f"{item_label}.sha256")
            actual = sha256_file(evidence_path)
            if actual != expected:
                raise ManifestError(
                    f"evidence hash mismatch for {path_value}: expected {expected}, got {actual}"
                )
        if url_value is not None:
            _require_text(url_value, f"{item_label}.canonical_url")
    return evidence_ids


def _check_parent_graph(assets: dict[str, RightsAsset]) -> None:
    state: dict[str, int] = {}

    def visit(asset_id: str) -> None:
        marker = state.get(asset_id, 0)
        if marker == 1:
            raise ManifestError(f"rights parent graph contains a cycle at {asset_id}")
        if marker == 2:
            return
        state[asset_id] = 1
        asset = assets[asset_id]
        for parent_id in asset.parents:
            if parent_id not in assets:
                raise ManifestError(f"{asset_id} references missing parent {parent_id}")
            visit(parent_id)
            parent = assets[parent_id]
            for action in RIGHTS_ACTIONS:
                if STATUS_RANK[asset.actions[action]] > STATUS_RANK[parent.actions[action]]:
                    raise ManifestError(
                        f"{asset_id} cannot upgrade inherited {action} from "
                        f"{parent.actions[action]} to {asset.actions[action]}"
                    )
        state[asset_id] = 2

    for asset_id in assets:
        visit(asset_id)


def validate_rights(
    manifest_path: Path, *, root: Path | None = None, target: str | None = None
) -> RightsReport:
    manifest_path = manifest_path.resolve()
    root = (root or manifest_path.parent).resolve()
    data = load_json(manifest_path)
    if data.get("schema") != SCHEMA:
        raise ManifestError(f"rights schema must be {SCHEMA!r}")
    pack_id = _require_text(data.get("pack_id"), "pack_id")
    if not ID_RE.fullmatch(pack_id):
        raise ManifestError(f"invalid namespaced pack_id: {pack_id!r}")
    raw_assets = data.get("assets")
    if not isinstance(raw_assets, list) or not raw_assets:
        raise ManifestError("rights manifest needs at least one asset")
    assets: dict[str, RightsAsset] = {}
    seen_files: set[str] = set()
    for index, raw_asset in enumerate(raw_assets):
        label = f"assets[{index}]"
        if not isinstance(raw_asset, dict):
            raise ManifestError(f"{label} must be an object")
        asset_id = _require_text(raw_asset.get("asset_id"), f"{label}.asset_id")
        if not ID_RE.fullmatch(asset_id):
            raise ManifestError(f"invalid {label}.asset_id: {asset_id!r}")
        if asset_id in assets:
            raise ManifestError(f"duplicate asset_id {asset_id!r}")
        file_value = _require_text(raw_asset.get("file"), f"{label}.file")
        if file_value in seen_files:
            raise ManifestError(f"multiple assets claim the same file: {file_value}")
        seen_files.add(file_value)
        audio_path = safe_relative_path(root, file_value, label=f"{label}.file")
        if not audio_path.is_file() or audio_path.is_symlink():
            raise ManifestError(f"missing or unsafe asset file: {file_value}")
        expected_sha = _require_sha(raw_asset.get("sha256"), f"{label}.sha256")
        actual_sha = sha256_file(audio_path)
        if expected_sha != actual_sha:
            raise ManifestError(
                f"asset hash mismatch for {file_value}: expected {expected_sha}, got {actual_sha}"
            )
        intake_tier = raw_asset.get("intake_tier")
        if intake_tier not in INTAKE_TIERS:
            raise ManifestError(f"invalid {label}.intake_tier: {intake_tier!r}")
        license_data = raw_asset.get("license")
        if not isinstance(license_data, dict):
            raise ManifestError(f"{label}.license must be an object")
        license_spdx = _require_text(license_data.get("spdx"), f"{label}.license.spdx")
        _require_text(license_data.get("name"), f"{label}.license.name")
        _require_text(license_data.get("canonical_url"), f"{label}.license.canonical_url")
        evidence_ids = _validate_evidence(raw_asset.get("evidence"), root, label)
        actions = _validate_action_matrix(raw_asset.get("actions"), evidence_ids, label)
        raw_parents = raw_asset.get("parent_asset_ids", [])
        if not isinstance(raw_parents, list) or any(
            not isinstance(parent, str) for parent in raw_parents
        ):
            raise ManifestError(f"{label}.parent_asset_ids must be strings")
        assets[asset_id] = RightsAsset(
            asset_id=asset_id,
            file=file_value,
            sha256=expected_sha,
            intake_tier=intake_tier,
            license_spdx=license_spdx,
            parents=tuple(raw_parents),
            actions=actions,
        )
    _check_parent_graph(assets)
    if target is not None:
        if target not in TARGET_ACTIONS:
            raise ManifestError(
                f"unknown rights target {target!r}; expected one of {sorted(TARGET_ACTIONS)}"
            )
        for asset in assets.values():
            for action in TARGET_ACTIONS[target]:
                status = asset.actions[action]
                if target == "local-preview":
                    if status == "deny":
                        raise ManifestError(f"{asset.asset_id} denies {action}")
                elif status != "allow":
                    raise ManifestError(
                        f"{asset.asset_id} is not publishable for {target}: {action}={status}"
                    )
    return RightsReport(
        manifest_path=manifest_path,
        root=root,
        pack_id=pack_id,
        assets=tuple(assets.values()),
        target=target,
    )
