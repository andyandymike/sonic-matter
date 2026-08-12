from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
import sys
import wave
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from .errors import ManifestError
from .io import sha256_file
from .kit import MAX_FILES, MAX_TOTAL_BYTES, validate_kit


PLAN_SCHEMA = "sonic-godot-compile-plan/v1"
COMPILED_SCHEMA = "sonic-godot-compiled-impact-pack/v1"
COMPILER_ID = "sonic-matter/godot-sample-first-compiler/v1"
RUNTIME_CONTRACT = "sonic-matter/gate-a-impact/v1"
SONIC_MATTER_VERSION = "0.1.0-rc1"
GODOT_VERSION = "4.6"

MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 200_000
MAX_JSON_STRING = 65_536
MAX_MATERIALS = 128
MAX_PALETTES = 128
MAX_VARIANTS_PER_PALETTE = 32
MAX_VARIANTS = 512
MAX_EXACT_ROUTES = 256
MAX_FAMILY_FALLBACKS = 128

_KIT_SCHEMA = "sonic-material-kit/v1"
_RIGHTS_SCHEMA = "sonic-material-rights/v1"
_KIT_ID_RE = re.compile(
    r"^(0|[a-z][a-z0-9]*)(?:[._-][a-z0-9]+)*$"
)
_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z.-]+)?$"
)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ASSET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:/-]{2,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_RESERVED = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_GODOT_AUDIO_TYPES = {".wav": "AudioStreamWAV"}
_COMPILE_RIGHTS_TARGETS = {
    "game-binary",
    "game-source",
    "local-preview",
}


@dataclass(frozen=True)
class GodotPlanReport:
    kit_id: str
    kit_version: str
    kit_manifest_sha256: str
    plan_sha256: str
    rights_targets: tuple[str, ...]
    material_count: int
    palette_count: int
    route_count: int
    audio_asset_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "status": "validated",
            "kit_id": self.kit_id,
            "kit_version": self.kit_version,
            "kit_manifest_sha256": self.kit_manifest_sha256,
            "plan_sha256": self.plan_sha256,
            "rights_targets": list(self.rights_targets),
            "material_count": self.material_count,
            "palette_count": self.palette_count,
            "route_count": self.route_count,
            "audio_asset_count": self.audio_asset_count,
        }


@dataclass(frozen=True)
class GodotCompileReport:
    output_dir: Path
    manifest_path: Path
    manifest_sha256: str
    output_inventory_sha256: str
    kit_id: str
    kit_version: str
    rights_targets: tuple[str, ...]
    file_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": COMPILED_SCHEMA,
            "status": "compiled",
            "output_dir": str(self.output_dir),
            "manifest": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "output_inventory_sha256": self.output_inventory_sha256,
            "kit_id": self.kit_id,
            "kit_version": self.kit_version,
            "rights_targets": list(self.rights_targets),
            "file_count": self.file_count,
        }


@dataclass(frozen=True)
class _FileRecord:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class _Coverage:
    source: str
    target: str
    state: str


@dataclass(frozen=True)
class _Kit:
    manifest_path: Path
    root: Path
    kit_id: str
    version: str
    manifest_sha256: str
    rights_path: Path
    rights_relative_path: str
    files: dict[str, _FileRecord]
    coverage: dict[tuple[str, str], _Coverage]


@dataclass(frozen=True)
class _Material:
    material_id: str
    family_id: str
    roles: tuple[str, ...]


@dataclass(frozen=True)
class _Variant:
    slot: int
    asset_id: str
    weight: float
    gain_db: float
    pitch_scale: float


@dataclass(frozen=True)
class _Palette:
    palette_id: str
    family_id: str
    impact_gain_db: tuple[float, float]
    gain_variation_db: float
    pitch_variation: float
    variants: tuple[_Variant, ...]


@dataclass(frozen=True)
class _ExactRoute:
    route_id: str
    source_material_id: str
    target_material_id: str
    symmetric: bool
    palette_id: str


@dataclass(frozen=True)
class _Fallback:
    fallback_id: str
    family_id: str
    palette_id: str


@dataclass(frozen=True)
class _Plan:
    path: Path
    sha256: str
    materials: tuple[_Material, ...]
    palettes: tuple[_Palette, ...]
    exact_routes: tuple[_ExactRoute, ...]
    target_fallbacks: tuple[_Fallback, ...]
    source_fallbacks: tuple[_Fallback, ...]
    global_default: str | None


@dataclass(frozen=True)
class _AudioAsset:
    asset_id: str
    source_relative_path: str
    source_path: Path
    sha256: str
    bytes: int
    extension: str
    godot_type: str
    license_spdx: str

    @property
    def output_relative_path(self) -> str:
        return f"audio/{self.sha256}{self.extension}"


@dataclass(frozen=True)
class _Resolution:
    resolved: bool
    resolution: str
    palette_id: str | None
    definition_id: str | None


@dataclass(frozen=True)
class _Prepared:
    kit: _Kit
    plan: _Plan
    rights_manifest_sha256: str
    rights_targets: tuple[str, ...]
    audio_assets: dict[str, _AudioAsset]
    coverage_results: tuple[dict[str, Any], ...]

    def report(self) -> GodotPlanReport:
        return GodotPlanReport(
            kit_id=self.kit.kit_id,
            kit_version=self.kit.version,
            kit_manifest_sha256=self.kit.manifest_sha256,
            plan_sha256=self.plan.sha256,
            rights_targets=self.rights_targets,
            material_count=len(self.plan.materials),
            palette_count=len(self.plan.palettes),
            route_count=(
                len(self.plan.exact_routes)
                + len(self.plan.target_fallbacks)
                + len(self.plan.source_fallbacks)
                + (1 if self.plan.global_default is not None else 0)
            ),
            audio_asset_count=len(self.audio_assets),
        )


class _StrictJsonError(ValueError):
    pass


def _reject_constant(value: str) -> None:
    raise _StrictJsonError(f"non-finite JSON constant {value!r} is forbidden")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _StrictJsonError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _check_json_shape(value: Any) -> None:
    node_count = 0

    def visit(current: Any, depth: int) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_JSON_NODES:
            raise _StrictJsonError(
                f"JSON has more than {MAX_JSON_NODES} values"
            )
        if depth > MAX_JSON_DEPTH:
            raise _StrictJsonError(
                f"JSON nesting exceeds {MAX_JSON_DEPTH} levels"
            )
        if isinstance(current, str):
            if len(current) > MAX_JSON_STRING:
                raise _StrictJsonError(
                    f"JSON string exceeds {MAX_JSON_STRING} characters"
                )
            if unicodedata.normalize("NFC", current) != current:
                raise _StrictJsonError("JSON strings must use NFC normalization")
            return
        if isinstance(current, float):
            if not math.isfinite(current):
                raise _StrictJsonError("JSON numbers must be finite")
            return
        if isinstance(current, dict):
            for key, child in current.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
            return
        if isinstance(current, list):
            for child in current:
                visit(child, depth + 1)

    visit(value, 0)


def _load_strict_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    checked = _checked_regular_file(path, label)
    try:
        payload = checked.read_bytes()
    except OSError as error:
        raise ManifestError(f"cannot read {label} {checked}: {error}") from error
    if len(payload) > MAX_JSON_BYTES:
        raise ManifestError(
            f"{label} is {len(payload)} bytes; limit is {MAX_JSON_BYTES}"
        )
    try:
        text = payload.decode("utf-8")
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
        _check_json_shape(value)
    except (UnicodeError, json.JSONDecodeError, _StrictJsonError) as error:
        raise ManifestError(f"invalid strict JSON in {label}: {error}") from error
    if not isinstance(value, dict):
        raise ManifestError(f"{label} JSON root must be an object")
    return value, hashlib.sha256(payload).hexdigest()


def _object(
    value: Any,
    label: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must be an object")
    allowed = required | (optional or set())
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing or extra:
        raise ManifestError(
            f"{label} keys are not exact; missing={missing}, extra={extra}"
        )
    return value


def _list(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int,
) -> list[Any]:
    if not isinstance(value, list):
        raise ManifestError(f"{label} must be an array")
    if not minimum <= len(value) <= maximum:
        raise ManifestError(
            f"{label} must contain {minimum} through {maximum} entries"
        )
    return value


def _text(value: Any, label: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ManifestError(f"{label} must be a non-empty trimmed string")
    if len(value) > maximum:
        raise ManifestError(f"{label} exceeds {maximum} characters")
    if unicodedata.normalize("NFC", value) != value:
        raise ManifestError(f"{label} must use NFC normalization")
    if any(ord(character) < 0x20 for character in value):
        raise ManifestError(f"{label} contains a control character")
    return value


def _identifier(value: Any, label: str) -> str:
    identifier = _text(value, label, maximum=128)
    if not _ID_RE.fullmatch(identifier):
        raise ManifestError(
            f"{label} must match lowercase safe identifier syntax"
        )
    return identifier


def _asset_identifier(value: Any, label: str) -> str:
    identifier = _text(value, label, maximum=128)
    if not _ASSET_ID_RE.fullmatch(identifier):
        raise ManifestError(f"{label} is not a valid rights asset ID")
    return identifier


def _sha256(value: Any, label: str) -> str:
    digest = _text(value, label, maximum=64)
    if not _SHA256_RE.fullmatch(digest):
        raise ManifestError(f"{label} must be a lowercase SHA-256")
    return digest


def _integer(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ManifestError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise ManifestError(f"{label} must be in [{minimum}, {maximum}]")
    return value


def _finite_number(
    value: Any,
    label: str,
    *,
    minimum: float,
    maximum: float,
    minimum_exclusive: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ManifestError(f"{label} must be finite")
    lower_ok = number > minimum if minimum_exclusive else number >= minimum
    if not lower_ok or number > maximum:
        left = "(" if minimum_exclusive else "["
        raise ManifestError(
            f"{label} must be in {left}{minimum}, {maximum}]"
        )
    if number == 0.0:
        return 0.0
    return number


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _checked_regular_file(path: Path, label: str) -> Path:
    candidate = Path(path)
    if _is_reparse(candidate):
        raise ManifestError(f"{label} must not be a symlink or reparse point")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise ManifestError(f"missing {label}: {candidate}") from error
    if not resolved.is_file() or _is_reparse(resolved):
        raise ManifestError(f"{label} must be a regular file: {candidate}")
    return resolved


def _portable_relative_path(value: Any, label: str) -> str:
    raw = _text(value, label, maximum=512)
    if "\\" in raw:
        raise ManifestError(f"{label} must use canonical POSIX separators")
    pure = PurePosixPath(raw)
    if pure.is_absolute() or pure.as_posix() != raw:
        raise ManifestError(f"{label} must be a canonical relative path")
    if not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ManifestError(f"unsafe {label}: {raw!r}")
    for part in pure.parts:
        if ":" in part or part.endswith((" ", ".")):
            raise ManifestError(f"unsafe {label} component: {part!r}")
        stem = part.split(".", 1)[0].casefold()
        if stem in _WINDOWS_RESERVED:
            raise ManifestError(f"reserved Windows path component in {label}: {part!r}")
        if any(ord(character) < 0x20 for character in part):
            raise ManifestError(f"control character in {label}: {part!r}")
    return raw


def _safe_kit_file(root: Path, relative: str, label: str) -> Path:
    pure = PurePosixPath(relative)
    current = root
    for part in pure.parts:
        current = current / part
        if _is_reparse(current):
            raise ManifestError(f"{label} crosses a symlink or reparse point")
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ManifestError(f"{label} escapes the Kit root") from error
    if not resolved.is_file():
        raise ManifestError(f"missing {label}: {relative}")
    return resolved


def _strict_kit(manifest_path: Path) -> _Kit:
    checked_manifest = _checked_regular_file(manifest_path, "Kit manifest")
    raw, manifest_sha = _load_strict_json(checked_manifest, "Kit manifest")
    data = _object(
        raw,
        "Kit manifest",
        required={
            "schema",
            "kit_id",
            "version",
            "status",
            "rights_manifest",
            "files",
            "coverage",
        },
    )
    if data["schema"] != _KIT_SCHEMA:
        raise ManifestError(f"Kit schema must be {_KIT_SCHEMA!r}")
    kit_id = _text(data["kit_id"], "kit_id", maximum=128)
    if not _KIT_ID_RE.fullmatch(kit_id):
        raise ManifestError("kit_id must be a stable lowercase namespace")
    version = _text(data["version"], "version", maximum=128)
    if not _VERSION_RE.fullmatch(version):
        raise ManifestError("version must be semantic")
    if data["status"] not in {"experimental", "supported"}:
        raise ManifestError("Kit status must be experimental or supported")

    root = checked_manifest.parent.resolve(strict=True)
    raw_files = _list(
        data["files"], "files", minimum=1, maximum=MAX_FILES
    )
    files: dict[str, _FileRecord] = {}
    folded_paths: dict[str, str] = {}
    total_bytes = 0
    for index, raw_file in enumerate(raw_files):
        label = f"files[{index}]"
        item = _object(
            raw_file,
            label,
            required={"path", "sha256", "bytes"},
        )
        relative = _portable_relative_path(item["path"], f"{label}.path")
        folded = unicodedata.normalize("NFC", relative).casefold()
        if folded in folded_paths:
            raise ManifestError(
                f"portable path collision: {folded_paths[folded]!r} and {relative!r}"
            )
        folded_paths[folded] = relative
        if relative in files:
            raise ManifestError(f"duplicate Kit file path: {relative}")
        digest = _sha256(item["sha256"], f"{label}.sha256")
        byte_count = _integer(
            item["bytes"],
            f"{label}.bytes",
            minimum=0,
            maximum=MAX_TOTAL_BYTES,
        )
        total_bytes += byte_count
        if total_bytes > MAX_TOTAL_BYTES:
            raise ManifestError(
                f"Kit size exceeds {MAX_TOTAL_BYTES} bytes"
            )
        files[relative] = _FileRecord(relative, digest, byte_count)

    rights_relative = _portable_relative_path(
        data["rights_manifest"], "rights_manifest"
    )
    if rights_relative not in files:
        raise ManifestError("rights_manifest must be present in the exact Kit inventory")
    rights_path = _safe_kit_file(root, rights_relative, "rights manifest")

    raw_coverage = _list(
        data["coverage"], "coverage", minimum=1, maximum=MAX_EXACT_ROUTES * 2
    )
    coverage: dict[tuple[str, str], _Coverage] = {}
    for index, raw_entry in enumerate(raw_coverage):
        label = f"coverage[{index}]"
        entry = _object(
            raw_entry,
            label,
            required={"event", "source", "target", "state"},
            optional={"recipe"},
        )
        if entry["event"] != "impact":
            raise ManifestError(f"{label}.event must be 'impact'")
        source = _identifier(entry["source"], f"{label}.source")
        target = _identifier(entry["target"], f"{label}.target")
        state = entry["state"]
        if state not in {"verified", "fallback", "unsupported"}:
            raise ManifestError(f"invalid {label}.state: {state!r}")
        if state == "verified":
            if "recipe" not in entry:
                raise ManifestError(f"{label}.recipe is required for verified coverage")
            recipe = _portable_relative_path(entry["recipe"], f"{label}.recipe")
            if recipe not in files:
                raise ManifestError(
                    f"{label}.recipe is absent from the exact Kit inventory"
                )
        elif "recipe" in entry:
            raise ManifestError(
                f"{label}.recipe is only allowed for verified coverage"
            )
        key = (source, target)
        if key in coverage:
            raise ManifestError(f"duplicate impact coverage selector: {key}")
        coverage[key] = _Coverage(source, target, state)

    return _Kit(
        manifest_path=checked_manifest,
        root=root,
        kit_id=kit_id,
        version=version,
        manifest_sha256=manifest_sha,
        rights_path=rights_path,
        rights_relative_path=rights_relative,
        files=files,
        coverage=coverage,
    )


def _strict_plan(path: Path, kit: _Kit) -> _Plan:
    checked_path = _checked_regular_file(path, "compile plan")
    raw, plan_sha = _load_strict_json(checked_path, "compile plan")
    data = _object(
        raw,
        "compile plan",
        required={"schema", "kit", "runtime", "materials", "palettes", "routes"},
    )
    if data["schema"] != PLAN_SCHEMA:
        raise ManifestError(f"compile plan schema must be {PLAN_SCHEMA!r}")

    kit_lock = _object(
        data["kit"],
        "kit",
        required={"kit_id", "version", "manifest_sha256"},
    )
    if kit_lock["kit_id"] != kit.kit_id:
        raise ManifestError("compile plan kit_id does not match the Kit")
    if kit_lock["version"] != kit.version:
        raise ManifestError("compile plan version does not match the Kit")
    locked_sha = _sha256(kit_lock["manifest_sha256"], "kit.manifest_sha256")
    if locked_sha != kit.manifest_sha256:
        raise ManifestError(
            "compile plan is stale: Kit manifest SHA-256 does not match"
        )

    runtime = _object(
        data["runtime"],
        "runtime",
        required={"contract", "sonic_matter_version", "godot_version"},
    )
    expected_runtime = {
        "contract": RUNTIME_CONTRACT,
        "sonic_matter_version": SONIC_MATTER_VERSION,
        "godot_version": GODOT_VERSION,
    }
    if runtime != expected_runtime:
        raise ManifestError(
            f"runtime lock must exactly equal {expected_runtime!r}"
        )

    raw_materials = _list(
        data["materials"],
        "materials",
        minimum=2,
        maximum=MAX_MATERIALS,
    )
    materials: list[_Material] = []
    material_ids: set[str] = set()
    has_source = False
    has_target = False
    for index, raw_material in enumerate(raw_materials):
        label = f"materials[{index}]"
        item = _object(
            raw_material,
            label,
            required={"material_id", "family_id", "roles"},
        )
        material_id = _identifier(item["material_id"], f"{label}.material_id")
        family_id = _identifier(item["family_id"], f"{label}.family_id")
        _portable_relative_path(
            f"materials/{material_id}.tres", f"{label}.material_id output path"
        )
        if material_id in material_ids:
            raise ManifestError(f"duplicate material_id {material_id!r}")
        material_ids.add(material_id)
        raw_roles = _list(item["roles"], f"{label}.roles", minimum=1, maximum=2)
        if any(role not in {"source", "target"} for role in raw_roles):
            raise ManifestError(f"{label}.roles may contain only source and target")
        if len(set(raw_roles)) != len(raw_roles):
            raise ManifestError(f"{label}.roles contains a duplicate")
        roles = tuple(sorted(raw_roles))
        has_source = has_source or "source" in roles
        has_target = has_target or "target" in roles
        materials.append(_Material(material_id, family_id, roles))
    if not has_source or not has_target:
        raise ManifestError("materials must expose at least one source and one target")

    raw_palettes = _list(
        data["palettes"],
        "palettes",
        minimum=1,
        maximum=MAX_PALETTES,
    )
    palettes: list[_Palette] = []
    palette_ids: set[str] = set()
    total_variants = 0
    for index, raw_palette in enumerate(raw_palettes):
        label = f"palettes[{index}]"
        item = _object(
            raw_palette,
            label,
            required={
                "palette_id",
                "family_id",
                "impact_gain_db",
                "gain_variation_db",
                "pitch_variation",
                "variants",
            },
        )
        palette_id = _identifier(item["palette_id"], f"{label}.palette_id")
        if palette_id in palette_ids or palette_id in material_ids:
            raise ManifestError(f"duplicate or colliding palette_id {palette_id!r}")
        palette_ids.add(palette_id)
        family_id = _identifier(item["family_id"], f"{label}.family_id")
        gain_pair = _list(
            item["impact_gain_db"],
            f"{label}.impact_gain_db",
            minimum=2,
            maximum=2,
        )
        gain_low = _finite_number(
            gain_pair[0],
            f"{label}.impact_gain_db[0]",
            minimum=-80.0,
            maximum=6.0,
        )
        gain_high = _finite_number(
            gain_pair[1],
            f"{label}.impact_gain_db[1]",
            minimum=-80.0,
            maximum=6.0,
        )
        if gain_low > gain_high:
            raise ManifestError(f"{label}.impact_gain_db must be monotonic")
        gain_variation = _finite_number(
            item["gain_variation_db"],
            f"{label}.gain_variation_db",
            minimum=0.0,
            maximum=12.0,
        )
        pitch_variation = _finite_number(
            item["pitch_variation"],
            f"{label}.pitch_variation",
            minimum=0.0,
            maximum=0.5,
        )
        raw_variants = _list(
            item["variants"],
            f"{label}.variants",
            minimum=1,
            maximum=MAX_VARIANTS_PER_PALETTE,
        )
        total_variants += len(raw_variants)
        if total_variants > MAX_VARIANTS:
            raise ManifestError(f"plan exceeds {MAX_VARIANTS} total variants")
        variants: list[_Variant] = []
        seen_slots: set[int] = set()
        for variant_index, raw_variant in enumerate(raw_variants):
            variant_label = f"{label}.variants[{variant_index}]"
            variant = _object(
                raw_variant,
                variant_label,
                required={"slot", "asset_id", "weight", "gain_db", "pitch_scale"},
            )
            slot = _integer(
                variant["slot"],
                f"{variant_label}.slot",
                minimum=0,
                maximum=MAX_VARIANTS_PER_PALETTE - 1,
            )
            if slot in seen_slots:
                raise ManifestError(f"duplicate variant slot {slot} in {palette_id}")
            seen_slots.add(slot)
            variants.append(
                _Variant(
                    slot=slot,
                    asset_id=_asset_identifier(
                        variant["asset_id"], f"{variant_label}.asset_id"
                    ),
                    weight=_finite_number(
                        variant["weight"],
                        f"{variant_label}.weight",
                        minimum=0.0,
                        maximum=1000.0,
                        minimum_exclusive=True,
                    ),
                    gain_db=_finite_number(
                        variant["gain_db"],
                        f"{variant_label}.gain_db",
                        minimum=-24.0,
                        maximum=24.0,
                    ),
                    pitch_scale=_finite_number(
                        variant["pitch_scale"],
                        f"{variant_label}.pitch_scale",
                        minimum=0.25,
                        maximum=4.0,
                    ),
                )
            )
        variants.sort(key=lambda entry: entry.slot)
        if [entry.slot for entry in variants] != list(range(len(variants))):
            raise ManifestError(
                f"{label}.variants slots must be contiguous from zero"
            )
        palettes.append(
            _Palette(
                palette_id=palette_id,
                family_id=family_id,
                impact_gain_db=(gain_low, gain_high),
                gain_variation_db=gain_variation,
                pitch_variation=pitch_variation,
                variants=tuple(variants),
            )
        )

    routes = _object(
        data["routes"],
        "routes",
        required={"exact", "target_family", "source_family", "global_default"},
    )
    material_by_id = {entry.material_id: entry for entry in materials}

    raw_exact = _list(
        routes["exact"],
        "routes.exact",
        minimum=0,
        maximum=MAX_EXACT_ROUTES,
    )
    exact_routes: list[_ExactRoute] = []
    definition_ids: set[str] = set()
    for index, raw_route in enumerate(raw_exact):
        label = f"routes.exact[{index}]"
        item = _object(
            raw_route,
            label,
            required={
                "route_id",
                "source_material_id",
                "target_material_id",
                "symmetric",
                "palette_id",
            },
        )
        route_id = _identifier(item["route_id"], f"{label}.route_id")
        if route_id in definition_ids:
            raise ManifestError(f"duplicate route/fallback ID {route_id!r}")
        definition_ids.add(route_id)
        source = _identifier(
            item["source_material_id"], f"{label}.source_material_id"
        )
        target = _identifier(
            item["target_material_id"], f"{label}.target_material_id"
        )
        if source not in material_by_id or "source" not in material_by_id[source].roles:
            raise ManifestError(f"{label} references a non-source material")
        if target not in material_by_id or "target" not in material_by_id[target].roles:
            raise ManifestError(f"{label} references a non-target material")
        if not isinstance(item["symmetric"], bool):
            raise ManifestError(f"{label}.symmetric must be boolean")
        palette_id = _identifier(item["palette_id"], f"{label}.palette_id")
        if palette_id not in palette_ids:
            raise ManifestError(f"{label} references unknown palette {palette_id!r}")
        exact_routes.append(
            _ExactRoute(route_id, source, target, item["symmetric"], palette_id)
        )

    def parse_fallbacks(key: str) -> list[_Fallback]:
        raw_entries = _list(
            routes[key],
            f"routes.{key}",
            minimum=0,
            maximum=MAX_FAMILY_FALLBACKS,
        )
        result: list[_Fallback] = []
        seen_families: set[str] = set()
        for index, raw_entry in enumerate(raw_entries):
            label = f"routes.{key}[{index}]"
            item = _object(
                raw_entry,
                label,
                required={"fallback_id", "family_id", "palette_id"},
            )
            fallback_id = _identifier(
                item["fallback_id"], f"{label}.fallback_id"
            )
            if fallback_id in definition_ids:
                raise ManifestError(
                    f"duplicate route/fallback ID {fallback_id!r}"
                )
            definition_ids.add(fallback_id)
            family_id = _identifier(item["family_id"], f"{label}.family_id")
            if family_id in seen_families:
                raise ManifestError(
                    f"duplicate {key} fallback family {family_id!r}"
                )
            seen_families.add(family_id)
            palette_id = _identifier(item["palette_id"], f"{label}.palette_id")
            if palette_id not in palette_ids:
                raise ManifestError(
                    f"{label} references unknown palette {palette_id!r}"
                )
            result.append(_Fallback(fallback_id, family_id, palette_id))
        return result

    target_fallbacks = parse_fallbacks("target_family")
    source_fallbacks = parse_fallbacks("source_family")
    global_default_value = routes["global_default"]
    if global_default_value is None:
        global_default = None
    else:
        global_default = _identifier(
            global_default_value, "routes.global_default"
        )
        if global_default not in palette_ids:
            raise ManifestError(
                f"routes.global_default references unknown palette {global_default!r}"
            )

    return _Plan(
        path=checked_path,
        sha256=plan_sha,
        materials=tuple(sorted(materials, key=lambda entry: entry.material_id)),
        palettes=tuple(sorted(palettes, key=lambda entry: entry.palette_id)),
        exact_routes=tuple(sorted(exact_routes, key=lambda entry: entry.route_id)),
        target_fallbacks=tuple(
            sorted(target_fallbacks, key=lambda entry: entry.fallback_id)
        ),
        source_fallbacks=tuple(
            sorted(source_fallbacks, key=lambda entry: entry.fallback_id)
        ),
        global_default=global_default,
    )


def _normalize_rights_targets(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ManifestError("rights_targets must be an explicit sequence")
    raw = list(values)
    if not raw:
        raise ManifestError("at least one explicit rights target is required")
    if any(not isinstance(value, str) for value in raw):
        raise ManifestError("rights_targets entries must be strings")
    if len(set(raw)) != len(raw):
        raise ManifestError("rights_targets contains a duplicate")
    unknown = sorted(set(raw) - _COMPILE_RIGHTS_TARGETS)
    if unknown:
        raise ManifestError(
            f"unsupported Godot compile rights targets: {unknown}"
        )
    return tuple(sorted(raw))


def _resolve(plan: _Plan, source_id: str, target_id: str) -> _Resolution:
    material_by_id = {entry.material_id: entry for entry in plan.materials}
    ordered = [
        route
        for route in plan.exact_routes
        if route.source_material_id == source_id
        and route.target_material_id == target_id
    ]
    if len(ordered) > 1:
        raise ManifestError(
            f"ambiguous exact ordered route for {source_id}->{target_id}"
        )
    if ordered:
        route = ordered[0]
        return _Resolution(True, "exact_ordered", route.palette_id, route.route_id)

    symmetric = [
        route
        for route in plan.exact_routes
        if route.symmetric
        and route.source_material_id == target_id
        and route.target_material_id == source_id
    ]
    if len(symmetric) > 1:
        raise ManifestError(
            f"ambiguous exact symmetric route for {source_id}->{target_id}"
        )
    if symmetric:
        route = symmetric[0]
        return _Resolution(True, "exact_symmetric", route.palette_id, route.route_id)

    target_family = material_by_id[target_id].family_id
    target_matches = [
        fallback
        for fallback in plan.target_fallbacks
        if fallback.family_id == target_family
    ]
    if len(target_matches) > 1:
        raise ManifestError(
            f"ambiguous target family fallback for {source_id}->{target_id}"
        )
    if target_matches:
        fallback = target_matches[0]
        return _Resolution(
            True, "target_family", fallback.palette_id, fallback.fallback_id
        )

    source_family = material_by_id[source_id].family_id
    source_matches = [
        fallback
        for fallback in plan.source_fallbacks
        if fallback.family_id == source_family
    ]
    if len(source_matches) > 1:
        raise ManifestError(
            f"ambiguous source family fallback for {source_id}->{target_id}"
        )
    if source_matches:
        fallback = source_matches[0]
        return _Resolution(
            True, "source_family", fallback.palette_id, fallback.fallback_id
        )

    if plan.global_default is not None:
        return _Resolution(True, "global_default", plan.global_default, "global-default")
    return _Resolution(False, "drop", None, None)


def _validate_coverage(plan: _Plan, kit: _Kit) -> tuple[dict[str, Any], ...]:
    sources = [
        material.material_id
        for material in plan.materials
        if "source" in material.roles
    ]
    targets = [
        material.material_id
        for material in plan.materials
        if "target" in material.roles
    ]
    matrix = {(source, target) for source in sources for target in targets}
    declared = set(kit.coverage)
    if matrix != declared:
        missing = sorted(matrix - declared)
        extra = sorted(declared - matrix)
        raise ManifestError(
            f"compile matrix and Kit coverage differ; missing={missing}, extra={extra}"
        )

    results: list[dict[str, Any]] = []
    used_definitions: set[str] = set()
    used_palettes: set[str] = set()
    for source, target in sorted(matrix):
        coverage = kit.coverage[(source, target)]
        resolution = _resolve(plan, source, target)
        if coverage.state == "verified":
            if resolution.resolution not in {"exact_ordered", "exact_symmetric"}:
                raise ManifestError(
                    f"verified coverage {source}->{target} must resolve exactly"
                )
        elif coverage.state == "fallback":
            if resolution.resolution not in {
                "target_family",
                "source_family",
                "global_default",
            }:
                raise ManifestError(
                    f"fallback coverage {source}->{target} must resolve through a fallback"
                )
        elif resolution.resolved:
            raise ManifestError(
                f"unsupported coverage {source}->{target} unexpectedly resolves"
            )
        if resolution.definition_id is not None:
            used_definitions.add(resolution.definition_id)
        if resolution.palette_id is not None:
            used_palettes.add(resolution.palette_id)
        results.append(
            {
                "event": "impact",
                "source": source,
                "target": target,
                "state": coverage.state,
                "resolved": resolution.resolved,
                "resolution": resolution.resolution,
                "palette_id": resolution.palette_id,
                "definition_id": resolution.definition_id,
            }
        )

    declared_definitions = {
        route.route_id for route in plan.exact_routes
    } | {
        fallback.fallback_id for fallback in plan.target_fallbacks
    } | {
        fallback.fallback_id for fallback in plan.source_fallbacks
    }
    if plan.global_default is not None:
        declared_definitions.add("global-default")
    unused_definitions = sorted(declared_definitions - used_definitions)
    if unused_definitions:
        raise ManifestError(
            f"route plan contains unexercised definitions: {unused_definitions}"
        )
    unused_palettes = sorted(
        {palette.palette_id for palette in plan.palettes} - used_palettes
    )
    if unused_palettes:
        raise ManifestError(
            f"route plan contains unexercised palettes: {unused_palettes}"
        )
    return tuple(results)


def _validate_rights_manifest_json(kit: _Kit) -> str:
    raw, rights_sha = _load_strict_json(kit.rights_path, "rights manifest")
    if raw.get("schema") != _RIGHTS_SCHEMA:
        raise ManifestError(f"rights schema must be {_RIGHTS_SCHEMA!r}")
    record = kit.files[kit.rights_relative_path]
    if rights_sha != record.sha256:
        raise ManifestError(
            "rights manifest hash conflicts with the exact Kit inventory"
        )
    if kit.rights_path.stat().st_size != record.bytes:
        raise ManifestError(
            "rights manifest byte count conflicts with the exact Kit inventory"
        )
    return rights_sha


def _validate_pcm_wav(path: Path, label: str) -> None:
    _validate_pcm_wav_container(path, label)
    try:
        with wave.open(os.fspath(path), "rb") as source:
            if source.getcomptype() != "NONE":
                raise ManifestError(f"{label} must be uncompressed PCM WAV")
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            sample_width = source.getsampwidth()
            frame_count = source.getnframes()
            if channels not in {1, 2}:
                raise ManifestError(f"{label} must be mono or stereo PCM WAV")
            if not 8_000 <= sample_rate <= 192_000:
                raise ManifestError(f"{label} sample rate is unsupported: {sample_rate}")
            if sample_width not in {1, 2, 3, 4}:
                raise ManifestError(
                    f"{label} sample width is unsupported: {sample_width} bytes"
                )
            if frame_count < 1:
                raise ManifestError(f"{label} must contain at least one frame")
            expected_bytes = frame_count * channels * sample_width
            decoded_bytes = 0
            while True:
                payload = source.readframes(4096)
                if not payload:
                    break
                decoded_bytes += len(payload)
            if decoded_bytes != expected_bytes:
                raise ManifestError(f"{label} has truncated PCM frame data")
    except (EOFError, OSError, wave.Error) as error:
        raise ManifestError(f"{label} is not a readable PCM WAV: {error}") from error


def _validate_pcm_wav_container(path: Path, label: str) -> None:
    try:
        file_size = path.stat().st_size
        with path.open("rb") as source:
            header = source.read(12)
            if (
                len(header) != 12
                or header[:4] != b"RIFF"
                or header[8:] != b"WAVE"
            ):
                raise ManifestError(f"{label} must be a RIFF/WAVE file")
            riff_end = 8 + int.from_bytes(header[4:8], "little")
            if riff_end < 12 or riff_end > file_size:
                raise ManifestError(f"{label} has a truncated RIFF container")

            found_format = False
            while source.tell() + 8 <= riff_end:
                chunk_header = source.read(8)
                chunk_id = chunk_header[:4]
                chunk_size = int.from_bytes(chunk_header[4:8], "little")
                payload_start = source.tell()
                payload_end = payload_start + chunk_size
                padded_end = payload_end + (chunk_size & 1)
                if padded_end > riff_end:
                    raise ManifestError(f"{label} has a truncated RIFF chunk")
                if chunk_id == b"fmt " and not found_format:
                    if chunk_size < 16:
                        raise ManifestError(f"{label} has an invalid WAV fmt chunk")
                    format_tag = int.from_bytes(source.read(2), "little")
                    if format_tag != 1:
                        raise ManifestError(
                            f"{label} WAV format tag must be PCM 1, got {format_tag}"
                        )
                    found_format = True
                elif chunk_id == b"data":
                    if not found_format:
                        raise ManifestError(f"{label} must place fmt before data")
                    return
                source.seek(padded_end)
    except OSError as error:
        raise ManifestError(
            f"{label} is not a readable RIFF/WAVE file: {error}"
        ) from error

    if not found_format:
        raise ManifestError(f"{label} is missing a WAV fmt chunk")
    raise ManifestError(f"{label} is missing a WAV data chunk")


def _resolve_audio_assets(
    plan: _Plan,
    kit: _Kit,
    rights_assets: Sequence[Any],
) -> dict[str, _AudioAsset]:
    assets_by_id: dict[str, Any] = {}
    assets_by_hash: dict[str, list[Any]] = {}
    for asset in rights_assets:
        if asset.asset_id in assets_by_id:
            raise ManifestError(f"duplicate rights asset ID {asset.asset_id!r}")
        assets_by_id[asset.asset_id] = asset
        assets_by_hash.setdefault(asset.sha256, []).append(asset)

    referenced_ids = {
        variant.asset_id
        for palette in plan.palettes
        for variant in palette.variants
    }
    result: dict[str, _AudioAsset] = {}
    folded_outputs: set[str] = set()
    for asset_id in sorted(referenced_ids):
        asset = assets_by_id.get(asset_id)
        if asset is None:
            raise ManifestError(f"plan references unknown rights asset {asset_id!r}")
        if len(assets_by_hash[asset.sha256]) != 1:
            raise ManifestError(
                f"selected SHA-256 {asset.sha256} belongs to multiple rights assets"
            )
        relative = _portable_relative_path(
            asset.file, f"rights asset {asset_id}.file"
        )
        record = kit.files.get(relative)
        if record is None:
            raise ManifestError(
                f"rights asset {asset_id!r} is absent from the Kit inventory"
            )
        if asset.sha256 != record.sha256:
            raise ManifestError(
                f"rights and Kit hashes differ for asset {asset_id!r}"
            )
        source_path = _safe_kit_file(
            kit.root, relative, f"rights asset {asset_id}"
        )
        if source_path.stat().st_size != record.bytes:
            raise ManifestError(
                f"rights asset byte count differs for {asset_id!r}"
            )
        actual_sha = sha256_file(source_path)
        if actual_sha != record.sha256:
            raise ManifestError(
                f"rights asset hash changed for {asset_id!r}"
            )
        extension = source_path.suffix.lower()
        godot_type = _GODOT_AUDIO_TYPES.get(extension)
        if godot_type is None:
            raise ManifestError(
                f"Godot compiler supports only validated PCM WAV: {relative}"
            )
        _validate_pcm_wav(source_path, f"rights asset {asset_id!r}")
        output_relative = f"audio/{record.sha256}{extension}"
        folded_output = output_relative.casefold()
        if folded_output in folded_outputs:
            raise ManifestError(
                f"compiled audio path collision for {output_relative}"
            )
        folded_outputs.add(folded_output)
        result[asset_id] = _AudioAsset(
            asset_id=asset_id,
            source_relative_path=relative,
            source_path=source_path,
            sha256=record.sha256,
            bytes=record.bytes,
            extension=extension,
            godot_type=godot_type,
            license_spdx=asset.license_spdx,
        )
    return result


def _prepare(
    kit_manifest_path: Path,
    plan_path: Path,
    rights_targets: Sequence[str],
) -> _Prepared:
    targets = _normalize_rights_targets(rights_targets)
    kit = _strict_kit(Path(kit_manifest_path))
    plan = _strict_plan(Path(plan_path), kit)
    if _path_is_within(plan.path, kit.root):
        raise ManifestError(
            "compile plan must be a frozen input outside the Kit root"
        )

    reports = []
    for target in targets:
        reports.append(
            validate_kit(
                kit.manifest_path,
                profile="official-cc0",
                rights_target=target,
            )
        )
    if sha256_file(kit.manifest_path) != kit.manifest_sha256:
        raise ManifestError("Kit manifest changed during validation")
    if sha256_file(plan.path) != plan.sha256:
        raise ManifestError("compile plan changed during validation")
    rights_sha = _validate_rights_manifest_json(kit)

    for report in reports:
        if report.kit_id != kit.kit_id or report.version != kit.version:
            raise ManifestError("Kit identity changed during rights validation")
    rights_assets = reports[0].rights.assets
    audio_assets = _resolve_audio_assets(plan, kit, rights_assets)
    coverage_results = _validate_coverage(plan, kit)
    return _Prepared(
        kit=kit,
        plan=plan,
        rights_manifest_sha256=rights_sha,
        rights_targets=targets,
        audio_assets=audio_assets,
        coverage_results=coverage_results,
    )


def validate_godot_compile_plan(
    kit_manifest_path: Path,
    plan_path: Path,
    *,
    rights_targets: Sequence[str],
) -> GodotPlanReport:
    """Validate a frozen sample-first Godot compile plan without writing output."""

    return _prepare(
        Path(kit_manifest_path), Path(plan_path), rights_targets
    ).report()


def _gd_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _gd_string_name(value: str) -> str:
    return "&" + _gd_quote(value)


def _gd_float(value: float) -> str:
    if not math.isfinite(value):
        raise ManifestError("refusing to serialize a non-finite Godot number")
    if value == 0.0:
        return "0.0"
    rendered = repr(float(value))
    if "." not in rendered and "e" not in rendered.lower():
        rendered += ".0"
    return rendered


def _subresource_id(prefix: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"


def _typed_subresources(script_id: str, resource_ids: Sequence[str]) -> str:
    values = ", ".join(
        f"SubResource({_gd_quote(resource_id)})" for resource_id in resource_ids
    )
    return f"Array[ExtResource({_gd_quote(script_id)})]([{values}])"


def _material_tres(material: _Material) -> bytes:
    lines = [
        '[gd_resource type="Resource" script_class="SonicAcousticMaterial" format=3]',
        "",
        (
            '[ext_resource type="Script" '
            'path="res://addons/sonic_matter/runtime/sonic_acoustic_material.gd" '
            'id="1_material"]'
        ),
        "",
        "[resource]",
        'script = ExtResource("1_material")',
        f"material_id = {_gd_string_name(material.material_id)}",
        f"family_id = {_gd_string_name(material.family_id)}",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def _route_map_tres(prepared: _Prepared) -> bytes:
    plan = prepared.plan
    palette_by_id = {palette.palette_id: palette for palette in plan.palettes}
    audio_by_id = prepared.audio_assets
    lines = [
        '[gd_resource type="Resource" script_class="SonicImpactRouteMap" format=3]',
        "",
        (
            '[ext_resource type="Script" '
            'path="res://addons/sonic_matter/runtime/sonic_impact_route_map.gd" '
            'id="1_route_map"]'
        ),
        (
            '[ext_resource type="Script" '
            'path="res://addons/sonic_matter/runtime/sonic_acoustic_material.gd" '
            'id="2_material"]'
        ),
        (
            '[ext_resource type="Script" '
            'path="res://addons/sonic_matter/runtime/sonic_sample_variant.gd" '
            'id="3_variant"]'
        ),
        (
            '[ext_resource type="Script" '
            'path="res://addons/sonic_matter/runtime/sonic_impact_route.gd" '
            'id="4_route"]'
        ),
        (
            '[ext_resource type="Script" '
            'path="res://addons/sonic_matter/runtime/sonic_impact_family_fallback.gd" '
            'id="5_fallback"]'
        ),
    ]

    distinct_audio = sorted(
        {asset.sha256: asset for asset in audio_by_id.values()}.values(),
        key=lambda asset: asset.output_relative_path,
    )
    audio_ext_ids: dict[str, str] = {}
    for asset in distinct_audio:
        ext_id = f"audio_{asset.sha256}"
        audio_ext_ids[asset.sha256] = ext_id
        lines.append(
            f'[ext_resource type="{asset.godot_type}" '
            f'path={_gd_quote(asset.output_relative_path)} '
            f'id={_gd_quote(ext_id)}]'
        )
    lines.append("")

    variant_resource_ids: dict[tuple[str, int], str] = {}
    for palette in plan.palettes:
        for variant in palette.variants:
            resource_id = _subresource_id(
                "Variant", f"{palette.palette_id}:{variant.slot}"
            )
            variant_resource_ids[(palette.palette_id, variant.slot)] = resource_id
            asset = audio_by_id[variant.asset_id]
            lines.extend(
                [
                    f'[sub_resource type="Resource" id={_gd_quote(resource_id)}]',
                    'script = ExtResource("3_variant")',
                    f'stream = ExtResource({_gd_quote(audio_ext_ids[asset.sha256])})',
                    f"weight = {_gd_float(variant.weight)}",
                    f"gain_db = {_gd_float(variant.gain_db)}",
                    f"pitch_scale = {_gd_float(variant.pitch_scale)}",
                    "",
                ]
            )

    palette_resource_ids: dict[str, str] = {}
    for palette in plan.palettes:
        resource_id = _subresource_id("Palette", palette.palette_id)
        palette_resource_ids[palette.palette_id] = resource_id
        variant_ids = [
            variant_resource_ids[(palette.palette_id, variant.slot)]
            for variant in palette.variants
        ]
        lines.extend(
            [
                f'[sub_resource type="Resource" id={_gd_quote(resource_id)}]',
                'script = ExtResource("2_material")',
                f"material_id = {_gd_string_name(palette.palette_id)}",
                f"family_id = {_gd_string_name(palette.family_id)}",
                (
                    "impact_variants = "
                    + _typed_subresources("3_variant", variant_ids)
                ),
                (
                    "impact_gain_db = Vector2("
                    f"{_gd_float(palette.impact_gain_db[0])}, "
                    f"{_gd_float(palette.impact_gain_db[1])})"
                ),
                f"gain_variation_db = {_gd_float(palette.gain_variation_db)}",
                f"pitch_variation = {_gd_float(palette.pitch_variation)}",
                "",
            ]
        )

    route_resource_ids: list[str] = []
    for route in plan.exact_routes:
        resource_id = _subresource_id("Route", route.route_id)
        route_resource_ids.append(resource_id)
        lines.extend(
            [
                f'[sub_resource type="Resource" id={_gd_quote(resource_id)}]',
                'script = ExtResource("4_route")',
                f"route_id = {_gd_string_name(route.route_id)}",
                (
                    "source_material_id = "
                    + _gd_string_name(route.source_material_id)
                ),
                (
                    "target_material_id = "
                    + _gd_string_name(route.target_material_id)
                ),
                f"symmetric = {'true' if route.symmetric else 'false'}",
                (
                    "output_material = SubResource("
                    + _gd_quote(palette_resource_ids[route.palette_id])
                    + ")"
                ),
                "",
            ]
        )

    target_resource_ids: list[str] = []
    for fallback in plan.target_fallbacks:
        resource_id = _subresource_id("TargetFallback", fallback.fallback_id)
        target_resource_ids.append(resource_id)
        lines.extend(
            _fallback_tres_lines(fallback, resource_id, palette_resource_ids)
        )

    source_resource_ids: list[str] = []
    for fallback in plan.source_fallbacks:
        resource_id = _subresource_id("SourceFallback", fallback.fallback_id)
        source_resource_ids.append(resource_id)
        lines.extend(
            _fallback_tres_lines(fallback, resource_id, palette_resource_ids)
        )

    lines.extend(
        [
            "[resource]",
            'script = ExtResource("1_route_map")',
            "exact_routes = "
            + _typed_subresources("4_route", route_resource_ids),
            "target_family_fallbacks = "
            + _typed_subresources("5_fallback", target_resource_ids),
            "source_family_fallbacks = "
            + _typed_subresources("5_fallback", source_resource_ids),
        ]
    )
    if plan.global_default is not None:
        lines.append(
            "global_default = SubResource("
            + _gd_quote(palette_resource_ids[plan.global_default])
            + ")"
        )
    lines.append("")
    return "\n".join(lines).encode("utf-8")


def _fallback_tres_lines(
    fallback: _Fallback,
    resource_id: str,
    palette_resource_ids: dict[str, str],
) -> list[str]:
    return [
        f'[sub_resource type="Resource" id={_gd_quote(resource_id)}]',
        'script = ExtResource("5_fallback")',
        f"fallback_id = {_gd_string_name(fallback.fallback_id)}",
        f"family_id = {_gd_string_name(fallback.family_id)}",
        (
            "output_material = SubResource("
            + _gd_quote(palette_resource_ids[fallback.palette_id])
            + ")"
        ),
        "",
    ]


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except OSError as error:
        raise ManifestError(f"cannot create compiler output {path}: {error}") from error


def _copy_audio(asset: _AudioAsset, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    try:
        with asset.source_path.open("rb") as source, destination.open("xb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                written += len(chunk)
                target.write(chunk)
    except OSError as error:
        raise ManifestError(
            f"cannot copy rights asset {asset.asset_id!r}: {error}"
        ) from error
    if digest.hexdigest() != asset.sha256 or written != asset.bytes:
        raise ManifestError(
            f"rights asset changed while copying: {asset.asset_id!r}"
        )
    if sha256_file(destination) != asset.sha256:
        raise ManifestError(
            f"compiled audio hash mismatch: {asset.output_relative_path}"
        )


def _stable_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _stable_json_sha256(value: Any) -> str:
    return hashlib.sha256(_stable_json_bytes(value)).hexdigest()


def _file_inventory(root: Path) -> list[dict[str, Any]]:
    result = []
    for path in sorted(
        (candidate for candidate in root.rglob("*") if candidate.is_file()),
        key=lambda candidate: candidate.relative_to(root).as_posix(),
    ):
        if _is_reparse(path):
            raise ManifestError("compiler output unexpectedly contains a reparse point")
        relative = path.relative_to(root).as_posix()
        if relative == "compiled-manifest.json":
            continue
        result.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return result


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _publish_no_replace(stage: Path, output: Path) -> None:
    try:
        if os.name == "nt":
            os.rename(stage, output)
            return
        if sys.platform.startswith("linux"):
            libc = ctypes.CDLL(None, use_errno=True)
            renameat2 = getattr(libc, "renameat2", None)
            if renameat2 is None:
                raise ManifestError(
                    "atomic no-replace publication is unavailable on this Linux runtime"
                )
            renameat2.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            renameat2.restype = ctypes.c_int
            result = renameat2(
                -100,
                os.fsencode(stage),
                -100,
                os.fsencode(output),
                1,
            )
            if result == 0:
                return
            error_number = ctypes.get_errno()
            if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
                raise ManifestError(
                    "compiler output appeared during compilation; overwrite is forbidden"
                )
            raise ManifestError(
                "cannot atomically publish compiler output: "
                + os.strerror(error_number)
            )
        raise ManifestError(
            "atomic no-replace publication is unsupported on this authoring platform"
        )
    except FileExistsError as error:
        raise ManifestError(
            "compiler output appeared during compilation; overwrite is forbidden"
        ) from error
    except OSError as error:
        raise ManifestError(
            f"cannot atomically publish compiler output: {error}"
        ) from error




def _prepare_output_path(output_dir: Path, prepared: _Prepared) -> tuple[Path, Path]:
    raw_output = Path(output_dir)
    if raw_output.exists() or raw_output.is_symlink():
        raise ManifestError("compiler output path already exists; overwrite is forbidden")
    parent = raw_output.parent
    if not parent.exists() or not parent.is_dir() or _is_reparse(parent):
        raise ManifestError("compiler output parent must be an existing regular directory")
    parent = parent.resolve(strict=True)
    output = parent / raw_output.name
    if not raw_output.name or raw_output.name in {".", ".."}:
        raise ManifestError("compiler output directory name is unsafe")
    output_absolute = output.absolute()
    _portable_relative_path(raw_output.name, "compiler output directory name")
    if _path_is_within(output_absolute, prepared.kit.root) or _path_is_within(
        prepared.kit.root, output_absolute
    ):
        raise ManifestError("compiler output must be outside the input Kit tree")
    if _path_is_within(output_absolute, prepared.plan.path.parent) and (
        prepared.plan.path.parent == output_absolute
    ):
        raise ManifestError("compiler output must not replace the plan directory")
    stage = Path(
        tempfile.mkdtemp(prefix=f".{raw_output.name}.tmp-", dir=parent)
    )
    return output, stage


def compile_godot_kit(
    kit_manifest_path: Path,
    plan_path: Path,
    output_dir: Path,
    *,
    rights_targets: Sequence[str],
) -> GodotCompileReport:
    """Compile an approved sample-first Kit plan into deterministic Godot data.

    The plan is an independent frozen input because placing it inside the Kit
    inventory while also binding the complete Kit manifest SHA-256 would create
    a self-referential hash.  The function never overwrites an output path.
    """

    prepared = _prepare(
        Path(kit_manifest_path), Path(plan_path), rights_targets
    )
    output, stage = _prepare_output_path(Path(output_dir), prepared)
    published = False
    try:
        distinct_audio = sorted(
            {
                asset.output_relative_path: asset
                for asset in prepared.audio_assets.values()
            }.values(),
            key=lambda asset: asset.output_relative_path,
        )
        for asset in distinct_audio:
            _copy_audio(asset, stage / asset.output_relative_path)

        for material in prepared.plan.materials:
            relative = f"materials/{material.material_id}.tres"
            _write_new(stage / relative, _material_tres(material))
        _write_new(stage / "impact_route_map.tres", _route_map_tres(prepared))

        authoritative_files = _file_inventory(stage)
        output_inventory_sha256 = _stable_json_sha256(authoritative_files)
        audio_manifest = []
        for asset in sorted(
            prepared.audio_assets.values(), key=lambda entry: entry.asset_id
        ):
            audio_manifest.append(
                {
                    "asset_id": asset.asset_id,
                    "source_path": asset.source_relative_path,
                    "source_sha256": asset.sha256,
                    "compiled_path": asset.output_relative_path,
                    "compiled_sha256": asset.sha256,
                    "bytes": asset.bytes,
                    "license_spdx": asset.license_spdx,
                }
            )
        manifest = {
            "schema": COMPILED_SCHEMA,
            "compiler": {
                "id": COMPILER_ID,
                "deterministic": True,
            },
            "runtime": {
                "contract": RUNTIME_CONTRACT,
                "sonic_matter_version": SONIC_MATTER_VERSION,
                "godot_version": GODOT_VERSION,
            },
            "source": {
                "kit_id": prepared.kit.kit_id,
                "kit_version": prepared.kit.version,
                "kit_manifest_sha256": prepared.kit.manifest_sha256,
                "plan_sha256": prepared.plan.sha256,
                "rights_manifest_sha256": prepared.rights_manifest_sha256,
                "rights_targets": list(prepared.rights_targets),
            },
            "resources": {
                "impact_route_map": "impact_route_map.tres",
                "materials": [
                    {
                        "material_id": material.material_id,
                        "family_id": material.family_id,
                        "path": f"materials/{material.material_id}.tres",
                    }
                    for material in prepared.plan.materials
                ],
                "embedded_palettes": [
                    palette.palette_id for palette in prepared.plan.palettes
                ],
            },
            "audio": audio_manifest,
            "coverage": list(prepared.coverage_results),
            "output_inventory_sha256": output_inventory_sha256,
            "files": authoritative_files,
        }
        manifest_payload = _stable_json_bytes(manifest)
        _write_new(stage / "compiled-manifest.json", manifest_payload)
        if _stable_json_sha256(_file_inventory(stage)) != output_inventory_sha256:
            raise ManifestError("compiled output inventory changed before publication")

        if sha256_file(prepared.kit.manifest_path) != prepared.kit.manifest_sha256:
            raise ManifestError("Kit manifest changed during compilation")
        if sha256_file(prepared.plan.path) != prepared.plan.sha256:
            raise ManifestError("compile plan changed during compilation")
        if (
            sha256_file(prepared.kit.rights_path)
            != prepared.rights_manifest_sha256
        ):
            raise ManifestError("rights manifest changed during compilation")
        if output.exists() or output.is_symlink():
            raise ManifestError(
                "compiler output appeared during compilation; overwrite is forbidden"
            )
        _publish_no_replace(stage, output)
        published = True
        manifest_path = output / "compiled-manifest.json"
        return GodotCompileReport(
            output_dir=output,
            manifest_path=manifest_path,
            manifest_sha256=sha256_file(manifest_path),
            output_inventory_sha256=output_inventory_sha256,
            kit_id=prepared.kit.kit_id,
            kit_version=prepared.kit.version,
            rights_targets=prepared.rights_targets,
            file_count=len(authoritative_files) + 1,
        )
    finally:
        if not published and stage.exists():
            shutil.rmtree(stage)
