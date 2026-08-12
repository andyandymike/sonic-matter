from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

from .analysis import RECIPE_SCHEMA
from .errors import ManifestError
from .io import stable_json_bytes
from .render import _validate_recipe
from .rights import validate_recipe_publication_rights


PROPOSAL_SCHEMA = "sonic-authoring-proposal/v1"
PROPOSAL_PROFILE = "material-lab-impact-mix/v1"
VALIDATION_SCHEMA = "sonic-authoring-proposal-validation/v1"
MAX_PROPOSAL_BYTES = 64 * 1024
MAX_BASE_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 200_000
MIN_GAIN_DB = -96.0
MAX_GAIN_DB = 12.0

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LAYER_ORDER = ("transient", "body", "roughness", "master")
_MIX_FIELD_BY_LAYER = {
    "transient": "transient_gain_db",
    "body": "body_gain_db",
    "roughness": "roughness_gain_db",
    "master": "master_gain_db",
}
_TOP_LEVEL_KEYS = {
    "schema",
    "status",
    "profile",
    "proposal_id",
    "base",
    "summary",
    "changes",
}
_BASE_KEYS = {"artifact_schema", "sha256"}
_CHANGE_KEYS = {"kind", "layer", "from_db", "to_db", "reason"}


class _DuplicateKeyError(ValueError):
    pass


def _object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def _validate_json_shape(value: Any, label: str = "JSON") -> None:
    node_count = 0
    stack: list[tuple[Any, int, str]] = [(value, 0, label)]
    while stack:
        current, depth, current_label = stack.pop()
        node_count += 1
        if node_count > MAX_JSON_NODES:
            raise ManifestError(f"{label} exceeds {MAX_JSON_NODES} JSON values")
        if depth > MAX_JSON_DEPTH:
            raise ManifestError(f"{label} exceeds {MAX_JSON_DEPTH} nesting levels")
        if isinstance(current, float) and not math.isfinite(current):
            raise ManifestError(f"{current_label} contains a non-finite number")
        if isinstance(current, dict):
            stack.extend(
                (child, depth + 1, f"{current_label}.{key}")
                for key, child in current.items()
            )
        elif isinstance(current, list):
            stack.extend(
                (child, depth + 1, f"{current_label}[{index}]")
                for index, child in enumerate(current)
            )


def _read_strict_json(path: Path, *, label: str, max_bytes: int | None = None) -> tuple[dict[str, Any], bytes, str]:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ManifestError(f"{label} must be a regular non-symlink file: {path}")
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise ManifestError(f"cannot read {label} {path}: {error}") from error
    if max_bytes is not None and len(raw) > max_bytes:
        raise ManifestError(f"{label} exceeds {max_bytes} bytes: {path}")
    digest = hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise ManifestError(f"cannot read strict JSON {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise ManifestError(f"{label} JSON root must be an object: {path}")
    _validate_json_shape(value, label)
    return value, raw, digest


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ManifestError(f"{label} keys must be exact; missing={missing}, extra={extra}")


def _require_bounded_text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"{label} must be a non-empty string")
    if len(value) > maximum:
        raise ManifestError(f"{label} exceeds {maximum} characters")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise ManifestError(f"{label} contains a control character")
    return value


def _require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{label} must be a finite JSON number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ManifestError(f"{label} must fit a finite binary64 number") from error
    if not math.isfinite(number):
        raise ManifestError(f"{label} must be finite")
    return number


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json_bytes(value)).hexdigest()


def _diff_paths(before: Any, after: Any, prefix: tuple[Any, ...] = ()) -> set[tuple[Any, ...]]:
    if isinstance(before, dict) and isinstance(after, dict):
        differences: set[tuple[Any, ...]] = set()
        for key in set(before) | set(after):
            if key not in before or key not in after:
                differences.add(prefix + (key,))
            else:
                differences.update(_diff_paths(before[key], after[key], prefix + (key,)))
        return differences
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return {prefix}
        differences = set()
        for index, (before_item, after_item) in enumerate(zip(before, after)):
            differences.update(_diff_paths(before_item, after_item, prefix + (index,)))
        return differences
    return set() if before == after else {prefix}


def _protected_projection(value: dict[str, Any], mutable_paths: Iterable[tuple[str, str]]) -> dict[str, Any]:
    projection = copy.deepcopy(value)
    for section, field in mutable_paths:
        container = projection.get(section)
        if not isinstance(container, dict) or field not in container:
            raise ManifestError(f"base recipe is missing protected projection path {section}.{field}")
        container[field] = {"sonic_authoring_proposed_value": True}
    return projection


def _validate_proposal_document(proposal: dict[str, Any], base: dict[str, Any], base_sha256: str) -> tuple[dict[str, Any], tuple[str, ...], set[tuple[str, str]]]:
    _require_exact_keys(proposal, _TOP_LEVEL_KEYS, "proposal")
    if proposal.get("schema") != PROPOSAL_SCHEMA:
        raise ManifestError(f"proposal schema must be {PROPOSAL_SCHEMA!r}")
    if proposal.get("status") != "draft":
        raise ManifestError("proposal status must be the literal 'draft'")
    if proposal.get("profile") != PROPOSAL_PROFILE:
        raise ManifestError(f"proposal profile must be {PROPOSAL_PROFILE!r}")

    proposal_id = _require_bounded_text(proposal.get("proposal_id"), "proposal_id", maximum=128)
    if not _ID_RE.fullmatch(proposal_id):
        raise ManifestError(f"proposal_id has an invalid format: {proposal_id!r}")
    _require_bounded_text(proposal.get("summary"), "summary", maximum=500)

    base_binding = proposal.get("base")
    if not isinstance(base_binding, dict):
        raise ManifestError("proposal.base must be an object")
    _require_exact_keys(base_binding, _BASE_KEYS, "proposal.base")
    if base_binding.get("artifact_schema") != RECIPE_SCHEMA:
        raise ManifestError(f"proposal.base.artifact_schema must be {RECIPE_SCHEMA!r}")
    declared_sha = base_binding.get("sha256")
    if not isinstance(declared_sha, str) or not _SHA256_RE.fullmatch(declared_sha):
        raise ManifestError("proposal.base.sha256 must be a lowercase SHA-256")
    if declared_sha != base_sha256:
        raise ManifestError(
            f"proposal base SHA-256 mismatch: expected {declared_sha}, got {base_sha256}"
        )

    if base.get("schema") != RECIPE_SCHEMA:
        raise ManifestError(f"base recipe schema must be {RECIPE_SCHEMA!r}")
    if base.get("status") != "experimental":
        raise ManifestError("proposal v1 accepts only an experimental base recipe")
    mix = base.get("mix")
    if not isinstance(mix, dict):
        raise ManifestError("base recipe mix must be an object")

    raw_changes = proposal.get("changes")
    if not isinstance(raw_changes, list) or not 1 <= len(raw_changes) <= len(_LAYER_ORDER):
        raise ManifestError("proposal.changes must contain one to four changes")

    changes_by_layer: dict[str, tuple[float, float]] = {}
    for index, raw_change in enumerate(raw_changes):
        label = f"proposal.changes[{index}]"
        if not isinstance(raw_change, dict):
            raise ManifestError(f"{label} must be an object")
        _require_exact_keys(raw_change, _CHANGE_KEYS, label)
        if raw_change.get("kind") != "set_layer_gain_db":
            raise ManifestError(f"{label}.kind must be 'set_layer_gain_db'")
        layer = raw_change.get("layer")
        if layer not in _MIX_FIELD_BY_LAYER:
            raise ManifestError(f"{label}.layer must be one of {list(_LAYER_ORDER)}")
        if layer in changes_by_layer:
            raise ManifestError(f"proposal has duplicate change for layer {layer!r}")
        _require_bounded_text(raw_change.get("reason"), f"{label}.reason", maximum=500)

        field = _MIX_FIELD_BY_LAYER[layer]
        current = _require_number(mix.get(field), f"base.mix.{field}")
        from_db = _require_number(raw_change.get("from_db"), f"{label}.from_db")
        to_db = _require_number(raw_change.get("to_db"), f"{label}.to_db")
        if from_db != current:
            raise ManifestError(
                f"{label}.from_db is stale for {layer}: expected {current}, got {from_db}"
            )
        if to_db == current:
            raise ManifestError(f"{label} is a no-op for layer {layer!r}")
        if not MIN_GAIN_DB <= to_db <= MAX_GAIN_DB:
            raise ManifestError(
                f"{label}.to_db is outside [{MIN_GAIN_DB:g}, {MAX_GAIN_DB:g}] dB"
            )
        changes_by_layer[layer] = (from_db, to_db)

    candidate = copy.deepcopy(base)
    mutable_paths: set[tuple[str, str]] = set()
    changed_layers: list[str] = []
    for layer in _LAYER_ORDER:
        if layer not in changes_by_layer:
            continue
        field = _MIX_FIELD_BY_LAYER[layer]
        candidate["mix"][field] = changes_by_layer[layer][1]
        mutable_paths.add(("mix", field))
        changed_layers.append(layer)

    actual_diff = _diff_paths(base, candidate)
    if actual_diff != set(mutable_paths):
        raise ManifestError(
            "candidate diff is not exactly the declared mix changes: "
            f"expected={sorted(mutable_paths)!r}, actual={sorted(actual_diff)!r}"
        )
    return candidate, tuple(changed_layers), mutable_paths


def validate_proposal(proposal_path: Path, base_path: Path) -> dict[str, Any]:
    """Validate a mix-only authoring draft without writing or authorizing it.

    The returned receipt describes an in-memory candidate only.  It is not an
    approval, publication decision, render-safety result, or applied recipe.
    Invalid input raises :class:`ManifestError` (or an existing Material Lab
    validation error from the bound base recipe).
    """

    proposal_path = Path(proposal_path)
    base_path = Path(base_path)
    proposal, proposal_raw, proposal_sha256 = _read_strict_json(
        proposal_path,
        label="proposal",
        max_bytes=MAX_PROPOSAL_BYTES,
    )
    base, base_raw, base_sha256 = _read_strict_json(
        base_path,
        label="base recipe",
        max_bytes=MAX_BASE_BYTES,
    )

    candidate, changed_layers, mutable_paths = _validate_proposal_document(
        proposal,
        base,
        base_sha256,
    )

    validated_base, _samples, _transients = _validate_recipe(base_path)
    if validated_base != base:
        raise ManifestError("base recipe changed or parsed inconsistently during validation")
    validate_recipe_publication_rights(validated_base.get("rights"))

    expected_diff = set(mutable_paths)
    actual_diff = _diff_paths(validated_base, candidate)
    if actual_diff != expected_diff:
        raise ManifestError(
            "validated candidate diff is not exactly the declared mix changes: "
            f"expected={sorted(expected_diff)!r}, actual={sorted(actual_diff)!r}"
        )

    protected_before = _protected_projection(validated_base, mutable_paths)
    protected_after = _protected_projection(candidate, mutable_paths)
    protected_before_sha256 = _sha256_json(protected_before)
    protected_after_sha256 = _sha256_json(protected_after)
    if protected_before_sha256 != protected_after_sha256:
        raise ManifestError("candidate modified a protected recipe field")

    protected = {
        "algorithm": candidate.get("algorithm") == validated_base.get("algorithm"),
        "rights": candidate.get("rights") == validated_base.get("rights"),
        "safety": candidate.get("safety") == validated_base.get("safety"),
        "audio_paths_and_hashes": (
            candidate.get("sample_pool") == validated_base.get("sample_pool")
            and candidate.get("transients") == validated_base.get("transients")
        ),
        "remaining_recipe": protected_before_sha256 == protected_after_sha256,
    }
    if not all(protected.values()):
        raise ManifestError("candidate failed protected-field equality checks")

    current_proposal_raw = proposal_path.read_bytes()
    current_base_raw = base_path.read_bytes()
    if current_proposal_raw != proposal_raw:
        raise ManifestError("proposal changed during validation")
    if current_base_raw != base_raw:
        raise ManifestError("base recipe changed during validation")

    return {
        "schema": VALIDATION_SCHEMA,
        "result": "valid_draft",
        "proposal_id": proposal["proposal_id"],
        "profile": PROPOSAL_PROFILE,
        "proposal_sha256": proposal_sha256,
        "base": {
            "artifact_schema": RECIPE_SCHEMA,
            "sha256": base_sha256,
            "sha256_verified": True,
        },
        "candidate_canonical_sha256": _sha256_json(candidate),
        "changed_layers": list(changed_layers),
        "protected_sha256": protected_before_sha256,
        "protected": protected,
        "protected_fields_unchanged": True,
        "base_unchanged": True,
        "applied": False,
        "authorization": "none",
        "render_safety_evaluated": False,
    }


__all__ = [
    "MAX_BASE_BYTES",
    "MAX_JSON_DEPTH",
    "MAX_JSON_NODES",
    "MAX_PROPOSAL_BYTES",
    "PROPOSAL_PROFILE",
    "PROPOSAL_SCHEMA",
    "VALIDATION_SCHEMA",
    "validate_proposal",
]
