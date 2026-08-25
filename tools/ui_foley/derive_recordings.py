from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import uuid
import wave
from array import array
from pathlib import Path, PurePosixPath
from typing import Any


DERIVATIVE_SCHEMA = "sonic-ui-recording-derivative/v1"
MANIFEST_SCHEMA = "sonicmatter-recording-derivative-pack/v1"
GENERATOR_ID = "sonicmatter.ui-recording-derivative"
GENERATOR_VERSION = "1.0.0"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
AUTHORING_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts" / "ui-foley"
Q15_ONE = 32768
WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class DerivativeError(RuntimeError):
    """Raised when a recording derivative cannot be built safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: Any, field: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise DerivativeError(f"{field} must be a non-empty relative path")
    if "\\" in value or "\x00" in value:
        raise DerivativeError(f"{field} must use safe POSIX separators")
    result = PurePosixPath(value)
    if (
        result.is_absolute()
        or ".." in result.parts
        or "." in result.parts
        or result.as_posix() != value
    ):
        raise DerivativeError(f"{field} must be a normalized relative path")
    for part in result.parts:
        if any(character in '<>:"|?*' for character in part):
            raise DerivativeError(f"{field} contains a Windows-unsafe character")
        if part.endswith((" ", ".")):
            raise DerivativeError(f"{field} contains a Windows-unsafe suffix")
        if part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES:
            raise DerivativeError(f"{field} contains a Windows-reserved name")
    return result


def _join_under_root(root: Path, relative: PurePosixPath, field: str) -> Path:
    resolved_root = root.resolve()
    try:
        candidate = resolved_root.joinpath(*relative.parts).resolve()
        candidate.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DerivativeError(f"{field} escapes its allowed root") from exc
    return candidate


def _required_string(owner: dict[str, Any], field: str) -> str:
    value = owner.get(field)
    if not isinstance(value, str) or not value:
        raise DerivativeError(f"{field} must be a non-empty string")
    return value


def _required_int(
    owner: dict[str, Any], field: str, minimum: int, maximum: int
) -> int:
    value = owner.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise DerivativeError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise DerivativeError(
            f"{field} must be in the inclusive range {minimum}..{maximum}"
        )
    return value


def load_derivative_recipe(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DerivativeError(f"cannot read recipe {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DerivativeError("recipe root must be an object")
    _validate_recipe(value)
    return value


def _validate_recipe(recipe: dict[str, Any]) -> None:
    if recipe.get("schema") != DERIVATIVE_SCHEMA:
        raise DerivativeError(f"recipe schema must be {DERIVATIVE_SCHEMA}")
    _required_string(recipe, "recipe_id")
    _required_string(recipe, "created_date")
    generator = recipe.get("generator")
    if generator != {"id": GENERATOR_ID, "version": GENERATOR_VERSION}:
        raise DerivativeError("recipe generator identity is unsupported")

    parent = recipe.get("parent")
    if not isinstance(parent, dict):
        raise DerivativeError("parent must be an object")
    _required_string(parent, "pack_id")
    _required_string(parent, "version")
    _relative_path(parent.get("manifest_path"), "parent.manifest_path")
    manifest_sha = _required_string(parent, "manifest_sha256")
    if len(manifest_sha) != 64:
        raise DerivativeError("parent.manifest_sha256 must be SHA-256")

    decoder = recipe.get("decoder")
    expected_decoder = {
        "package": "miniaudio",
        "version": "1.71",
        "sample_format": "SIGNED16",
        "sample_rate_hz": 44100,
        "channels": 2,
    }
    if decoder != expected_decoder:
        raise DerivativeError("decoder contract must match the frozen v1 profile")

    outputs = recipe.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise DerivativeError("outputs must be a non-empty array")
    seen_asset_ids: set[str] = set()
    seen_output_paths: set[str] = set()
    for index, raw in enumerate(outputs):
        if not isinstance(raw, dict):
            raise DerivativeError(f"outputs[{index}] must be an object")
        asset_id = _required_string(raw, "asset_id")
        cue_id = _required_string(raw, "cue_id")
        if not cue_id.startswith("ui.foley."):
            raise DerivativeError(f"outputs[{index}].cue_id is unsupported")
        _required_int(raw, "variant", 1, 16)
        _required_string(raw, "source_asset_id")
        _relative_path(raw.get("source_path"), f"outputs[{index}].source_path")
        source_sha = _required_string(raw, "source_sha256")
        if len(source_sha) != 64:
            raise DerivativeError(f"outputs[{index}].source_sha256 must be SHA-256")
        output_path = _relative_path(
            raw.get("output_path"), f"outputs[{index}].output_path"
        )
        if (
            len(output_path.parts) < 2
            or output_path.parts[0] != "audio"
            or output_path.suffix != ".wav"
        ):
            raise DerivativeError(
                f"outputs[{index}].output_path must be audio/<name>.wav"
            )
        output_sha = _required_string(raw, "output_sha256")
        if len(output_sha) != 64 or any(
            character not in "0123456789abcdef" for character in output_sha
        ):
            raise DerivativeError(
                f"outputs[{index}].output_sha256 must be lowercase SHA-256"
            )
        start_frame = _required_int(raw, "start_frame", 0, 100_000_000)
        frame_count = _required_int(raw, "frame_count", 1764, 44100)
        fade_in = _required_int(raw, "fade_in_frames", 0, frame_count)
        fade_out = _required_int(raw, "fade_out_frames", 0, frame_count)
        if fade_in + fade_out > frame_count:
            raise DerivativeError(f"outputs[{index}] fades overlap")
        _required_int(raw, "gain_q15", 1, Q15_ONE)
        if start_frame + frame_count > 100_000_000:
            raise DerivativeError(f"outputs[{index}] frame range is invalid")
        output_collision_key = output_path.as_posix().casefold()
        if asset_id in seen_asset_ids or output_collision_key in seen_output_paths:
            raise DerivativeError("asset IDs and output paths must be unique")
        seen_asset_ids.add(asset_id)
        seen_output_paths.add(output_collision_key)

    rights = recipe.get("rights")
    if not isinstance(rights, dict):
        raise DerivativeError("rights must be an object")
    if rights.get("spdx") != "CC0-1.0":
        raise DerivativeError("recording derivatives must preserve the CC0 license")
    if rights.get("derivative_of_approved_cc0_recordings") is not True:
        raise DerivativeError("recording derivatives must declare their CC0 parent")
    for action, decision in rights.items():
        if action in {"spdx", "derivative_of_approved_cc0_recordings"}:
            continue
        if decision not in {"allow", "deny", "unknown"}:
            raise DerivativeError(f"rights.{action} has an invalid decision")
    for action in ("game_source_distribution", "game_binary_embedding"):
        if rights.get(action) != "allow":
            raise DerivativeError(f"rights.{action} must be allow")


def _mul_q15(value: int, gain_q15: int) -> int:
    product = value * gain_q15
    if product >= 0:
        result = (product + (Q15_ONE // 2)) // Q15_ONE
    else:
        result = -((-product + (Q15_ONE // 2)) // Q15_ONE)
    return max(-32768, min(32767, result))


def _ramp_q15(position: int, frame_count: int) -> int:
    if frame_count <= 1:
        return Q15_ONE
    return max(0, min(Q15_ONE, position * Q15_ONE // (frame_count - 1)))


def _condition_samples(samples: array, definition: dict[str, Any]) -> array:
    channels = 2
    start_frame = int(definition["start_frame"])
    frame_count = int(definition["frame_count"])
    fade_in = int(definition["fade_in_frames"])
    fade_out = int(definition["fade_out_frames"])
    base_gain = int(definition["gain_q15"])
    start = start_frame * channels
    end = (start_frame + frame_count) * channels
    if end > len(samples):
        raise DerivativeError(
            f"{definition['asset_id']} requests frames beyond its parent recording"
        )
    result = array("h")
    for local_frame in range(frame_count):
        effective_gain = base_gain
        if fade_in and local_frame < fade_in:
            effective_gain = _mul_q15(
                effective_gain, _ramp_q15(local_frame, fade_in)
            )
        if fade_out and local_frame >= frame_count - fade_out:
            remaining = frame_count - 1 - local_frame
            effective_gain = _mul_q15(
                effective_gain, _ramp_q15(remaining, fade_out)
            )
        source_offset = start + local_frame * channels
        for channel in range(channels):
            result.append(
                _mul_q15(int(samples[source_offset + channel]), effective_gain)
            )
    return result


def _pcm16le_bytes(samples: array) -> bytes:
    output = array("h", samples)
    if sys.byteorder != "little":
        output.byteswap()
    return output.tobytes()


def _wav_bytes(samples: array, sample_rate: int = 44100) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(_pcm16le_bytes(samples))
    return buffer.getvalue()


def _write_wav(path: Path, samples: array, sample_rate: int = 44100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_wav_bytes(samples, sample_rate))


def _audio_metrics(samples: array) -> dict[str, Any]:
    if not samples:
        raise DerivativeError("derived audio is empty")
    peak = max(abs(int(sample)) for sample in samples)
    dc_sum = sum(int(sample) for sample in samples)
    return {
        "peak_pcm16": peak,
        "clipped_sample_count": sum(
            1 for sample in samples if int(sample) in (-32768, 32767)
        ),
        "dc_mean_pcm16": round(dc_sum / len(samples), 6),
        "first_frame_silent": samples[0] == 0 and samples[1] == 0,
        "last_frame_silent": samples[-2] == 0 and samples[-1] == 0,
    }


def _verify_output_pack(
    root: Path, records: list[dict[str, Any]], manifest_text: str
) -> None:
    expected_files = {"derivative-manifest.json"}
    for record in records:
        relative = _relative_path(record["path"], "manifest asset path")
        expected_files.add(relative.as_posix())
        path = _join_under_root(root, relative, "manifest asset path")
        if not path.is_file() or _sha256(path) != record["sha256"]:
            raise DerivativeError(f"final output hash mismatch: {relative.as_posix()}")
    manifest_path = _join_under_root(
        root, PurePosixPath("derivative-manifest.json"), "derivative manifest"
    )
    try:
        observed_manifest = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DerivativeError("final derivative manifest is unreadable") from exc
    if observed_manifest != manifest_text:
        raise DerivativeError("final derivative manifest bytes do not match")
    observed_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    if observed_files != expected_files:
        raise DerivativeError("final derivative pack contains unexpected files")


def derive_recordings(
    recipe: dict[str, Any], output_root: Path, allow_overwrite: bool = False
) -> dict[str, Any]:
    _validate_recipe(recipe)
    try:
        import miniaudio
    except ImportError as exc:
        raise DerivativeError(
            "miniaudio 1.71 is required; install requirements-ui-derivative.txt"
        ) from exc
    if getattr(miniaudio, "__version__", "") != "1.71":
        raise DerivativeError("miniaudio version must be exactly 1.71")

    if output_root.is_symlink():
        raise DerivativeError("output directory must not be a symbolic link")
    output_root = output_root.resolve()
    authoring_root = AUTHORING_OUTPUT_ROOT.resolve()
    try:
        output_relative_to_authoring = output_root.relative_to(authoring_root)
    except ValueError as exc:
        raise DerivativeError(
            f"output directory must be below {authoring_root}"
        ) from exc
    if not output_relative_to_authoring.parts:
        raise DerivativeError("output directory must name one derivative pack")
    if output_root.exists() and not output_root.is_dir():
        raise DerivativeError(f"output path is not a directory: {output_root}")
    existing_entries = list(output_root.iterdir()) if output_root.exists() else []
    if existing_entries and not allow_overwrite:
        raise DerivativeError(f"output directory must be empty: {output_root}")
    if existing_entries:
        existing_manifest_path = _join_under_root(
            output_root,
            PurePosixPath("derivative-manifest.json"),
            "existing derivative manifest",
        )
        try:
            existing_manifest = json.loads(
                existing_manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise DerivativeError(
                "reviewed overwrite requires an existing derivative manifest"
            ) from exc
        if (
            existing_manifest.get("schema") != MANIFEST_SCHEMA
            or existing_manifest.get("pack_id") != recipe["recipe_id"]
        ):
            raise DerivativeError(
                "reviewed overwrite requires the same derivative pack identity"
            )

    parent = recipe["parent"]
    manifest_relative = _relative_path(
        parent["manifest_path"], "parent.manifest_path"
    )
    parent_manifest_path = _join_under_root(
        REPOSITORY_ROOT, manifest_relative, "parent.manifest_path"
    )
    if not parent_manifest_path.is_file():
        raise DerivativeError(f"parent manifest is missing: {parent_manifest_path}")
    if _sha256(parent_manifest_path) != parent["manifest_sha256"]:
        raise DerivativeError("parent manifest hash does not match the recipe")
    try:
        parent_manifest = json.loads(parent_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DerivativeError("parent manifest is not valid JSON") from exc
    if parent_manifest.get("pack_id") != parent["pack_id"]:
        raise DerivativeError("parent pack ID does not match")
    if parent_manifest.get("version") != parent["version"]:
        raise DerivativeError("parent pack version does not match")
    if parent_manifest.get("approval_state") != "approved":
        raise DerivativeError("parent pack must be approved")
    if parent_manifest.get("schema") != "sonicmatter-content-pack-rights/v1":
        raise DerivativeError("parent manifest schema is unsupported")
    if (
        (parent_manifest.get("license") or {}).get("spdx")
        != recipe["rights"]["spdx"]
    ):
        raise DerivativeError("parent license does not match derivative rights")
    parent_rights = parent_manifest.get("rights")
    if not isinstance(parent_rights, dict):
        raise DerivativeError("parent manifest rights must be an object")
    for action, decision in recipe["rights"].items():
        if action in {"spdx", "derivative_of_approved_cc0_recordings"}:
            continue
        if decision == "allow" and parent_rights.get(action) != "allow":
            raise DerivativeError(f"parent rights do not allow {action}")
    parent_assets = {
        str(asset["asset_id"]): asset for asset in parent_manifest.get("assets", [])
    }

    decoded_by_path: dict[str, Any] = {}
    output_records: list[dict[str, Any]] = []
    pending_outputs: list[tuple[PurePosixPath, bytes]] = []
    for definition in recipe["outputs"]:
        source_asset = parent_assets.get(definition["source_asset_id"])
        if not source_asset:
            raise DerivativeError(
                f"unknown parent asset {definition['source_asset_id']}"
            )
        parent_asset_relative = _relative_path(
            source_asset.get("path"), "parent asset path"
        )
        expected_parent_path = manifest_relative.parent.joinpath(
            parent_asset_relative
        )
        source_relative = _relative_path(
            definition["source_path"], "output.source_path"
        )
        if source_relative != expected_parent_path:
            raise DerivativeError(
                f"source path does not match parent asset {definition['source_asset_id']}"
            )
        if definition["source_sha256"] != source_asset["sha256"]:
            raise DerivativeError("source hash does not match the parent manifest")
        source_path = _join_under_root(
            REPOSITORY_ROOT, source_relative, "output.source_path"
        )
        if not source_path.is_file() or _sha256(source_path) != definition["source_sha256"]:
            raise DerivativeError(f"source recording hash mismatch: {source_path}")

        cache_key = source_relative.as_posix()
        if cache_key not in decoded_by_path:
            decoded_by_path[cache_key] = miniaudio.decode_file(
                str(source_path),
                output_format=miniaudio.SampleFormat.SIGNED16,
                nchannels=2,
                sample_rate=44100,
            )
        decoded = decoded_by_path[cache_key]
        if decoded.nchannels != 2 or decoded.sample_rate != 44100:
            raise DerivativeError("decoded source does not match the frozen profile")
        conditioned = _condition_samples(decoded.samples, definition)
        metrics = _audio_metrics(conditioned)
        if metrics["clipped_sample_count"] != 0:
            raise DerivativeError(f"{definition['asset_id']} clips after conditioning")
        if not metrics["first_frame_silent"] or not metrics["last_frame_silent"]:
            raise DerivativeError(f"{definition['asset_id']} must begin and end silent")

        output_relative = _relative_path(
            definition["output_path"], "output.output_path"
        )
        rendered_wav = _wav_bytes(conditioned)
        output_sha = hashlib.sha256(rendered_wav).hexdigest()
        if output_sha != definition["output_sha256"]:
            raise DerivativeError(
                f"{definition['asset_id']} output hash does not match the frozen recipe"
            )
        pending_outputs.append((output_relative, rendered_wav))
        output_records.append(
            {
                "asset_id": definition["asset_id"],
                "cue_id": definition["cue_id"],
                "variant": definition["variant"],
                "path": output_relative.as_posix(),
                "size_bytes": len(rendered_wav),
                "sha256": output_sha,
                "audio": {
                    "container": "WAV",
                    "codec": "PCM_S16LE",
                    "sample_rate_hz": 44100,
                    "channels": 2,
                    "frame_count": definition["frame_count"],
                    "duration_ms": round(
                        definition["frame_count"] * 1000.0 / 44100.0, 6
                    ),
                },
                "parent": {
                    "pack_id": parent["pack_id"],
                    "asset_id": definition["source_asset_id"],
                    "path": source_relative.as_posix(),
                    "sha256": definition["source_sha256"],
                },
                "transforms": [
                    {
                        "kind": "decode",
                        "decoder": "miniaudio==1.71",
                        "sample_format": "SIGNED16",
                        "sample_rate_hz": 44100,
                        "channels": 2,
                    },
                    {
                        "kind": "frame_slice",
                        "start_frame": definition["start_frame"],
                        "frame_count": definition["frame_count"],
                    },
                    {
                        "kind": "linear_fade",
                        "fade_in_frames": definition["fade_in_frames"],
                        "fade_out_frames": definition["fade_out_frames"],
                    },
                    {"kind": "gain_q15", "value": definition["gain_q15"]},
                ],
                "metrics": metrics,
            }
        )

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "pack_id": recipe["recipe_id"],
        "version": "1.0.0-candidate.1",
        "approval_state": "candidate",
        "created_date": recipe["created_date"],
        "generator": {
            "id": GENERATOR_ID,
            "version": GENERATOR_VERSION,
            "decoder": "miniaudio==1.71",
        },
        "parent_manifest": {
            "pack_id": parent["pack_id"],
            "version": parent["version"],
            "path": manifest_relative.as_posix(),
            "sha256": parent["manifest_sha256"],
        },
        "license": {
            "spdx": "CC0-1.0",
            "name": "Creative Commons Zero v1.0 Universal",
        },
        "rights": dict(recipe["rights"]),
        "assets": sorted(output_records, key=lambda record: record["path"]),
        "summary": {
            "asset_count": len(output_records),
            "cue_count": len({record["cue_id"] for record in output_records}),
            "total_size_bytes": sum(record["size_bytes"] for record in output_records),
        },
    }
    manifest_text = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging_root = output_root.with_name(
        f".{output_root.name}.staging-{uuid.uuid4().hex}"
    )
    staging_root.resolve().relative_to(authoring_root)
    staging_root.mkdir()
    backup_root: Path | None = None
    try:
        staging_root.relative_to(authoring_root)
        for output_relative, rendered_wav in pending_outputs:
            staging_path = _join_under_root(
                staging_root, output_relative, "staged output path"
            )
            staging_path.parent.mkdir(parents=True, exist_ok=True)
            with staging_path.open("xb") as handle:
                handle.write(rendered_wav)
        staging_manifest = _join_under_root(
            staging_root,
            PurePosixPath("derivative-manifest.json"),
            "staged derivative manifest",
        )
        with staging_manifest.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(manifest_text)
        _verify_output_pack(staging_root, output_records, manifest_text)

        if output_root.exists():
            backup_root = output_root.with_name(
                f".{output_root.name}.previous-{uuid.uuid4().hex}"
            )
            backup_root.resolve().relative_to(authoring_root)
            output_root.replace(backup_root)
        try:
            staging_root.replace(output_root)
        except OSError as exc:
            if backup_root is not None and backup_root.exists():
                backup_root.replace(output_root)
            raise DerivativeError("cannot commit staged derivative pack") from exc

        try:
            _verify_output_pack(output_root, output_records, manifest_text)
        except (DerivativeError, OSError, UnicodeError) as exc:
            try:
                output_root.replace(staging_root)
                if backup_root is not None and backup_root.exists():
                    backup_root.replace(output_root)
            except OSError as rollback_exc:
                raise DerivativeError(
                    "final derivative verification failed and rollback could not "
                    "restore the previous pack"
                ) from rollback_exc
            if isinstance(exc, DerivativeError):
                raise
            raise DerivativeError(
                "final derivative verification failed; the previous pack was restored"
            ) from exc
        if backup_root is not None and backup_root.exists():
            shutil.rmtree(backup_root)
    finally:
        if staging_root.exists():
            shutil.rmtree(staging_root)
    return manifest


__all__ = [
    "DERIVATIVE_SCHEMA",
    "GENERATOR_ID",
    "GENERATOR_VERSION",
    "DerivativeError",
    "derive_recordings",
    "load_derivative_recipe",
]
