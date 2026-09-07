from __future__ import annotations

import argparse
from importlib import metadata
from pathlib import Path

from matter_audio_core.actions import Operation, Registry
from matter_audio_core.artifacts import ArtifactStore, safe_path, stable_read
from matter_audio_core.cli import run
from matter_audio_core.contracts import digest, object_schema, parse_json
from matter_audio_core.errors import AudioError
from matter_audio_core.media import PCM, encode_wav, sample_bytes

from tools.ui_foley.derive_recordings import DerivativeError, _condition_samples, _relative_path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
REGISTERED_MANIFESTS = ("content-packs/ui-page-turn-starninjas-cc0/asset-rights.json",)
DECODER_PROFILE = "miniaudio-1.71-pcm16-stereo-44100/v1"


def catalog() -> list[dict]:
    records, seen = [], set()
    for relative in REGISTERED_MANIFESTS:
        path = safe_path(REPOSITORY_ROOT / relative)
        raw = stable_read(path, max_bytes=1024 * 1024)
        manifest = parse_json(raw)
        if (manifest.get("schema") != "sonicmatter-content-pack-rights/v1"
                or manifest.get("approval_state") != "approved"
                or manifest.get("license", {}).get("spdx") != "CC0-1.0"
                or manifest.get("rights", {}).get("local_preview") != "allow"):
            raise AudioError("catalog_ineligible", f"Recording pack cannot be used here: {relative}")
        for source in manifest.get("assets", []):
            asset_id = source["asset_id"]
            if asset_id in seen:
                raise AudioError("catalog_ambiguous", f"Duplicate registered ID: {asset_id}")
            seen.add(asset_id)
            try:
                local = _relative_path(source["path"], "registered recording")
            except DerivativeError as exc:
                raise AudioError("invalid_catalog_path", str(exc)) from exc
            source_path = safe_path(path.parent.joinpath(*local.parts))
            if not source_path.is_relative_to(path.parent):
                raise AudioError("unsafe_path", "Recording escaped its pack")
            data = stable_read(source_path)
            if digest(data)["hex"] != source["sha256"] or len(data) != source["size_bytes"]:
                raise AudioError("catalog_integrity_error", f"Recording changed: {asset_id}")
            records.append({"source_asset_id": asset_id, "pack_id": manifest["pack_id"],
                            "registered_duration_ms": source.get("duration_ms"), "digest": digest(data),
                            "manifest_digest": digest(raw), "path": str(source_path), "manifest_path": str(path)})
    return records


def decoder_capability() -> dict:
    try:
        version = metadata.version("miniaudio")
    except metadata.PackageNotFoundError:
        version = None
    return {"catalog": "registered_cc0_recordings", "decoder": {
        "profile": DECODER_PROFILE, "installed_version": version,
        "availability": "available" if version == "1.71" else "missing_or_wrong_version"}}


def decode_registered(store: ArtifactStore, source_asset_id: str, request_id: str) -> dict:
    candidates = [record for record in catalog() if record["source_asset_id"] == source_asset_id]
    if len(candidates) != 1:
        raise AudioError("catalog_not_found", source_asset_id)
    record = candidates[0]
    source = stable_read(Path(record["path"]))
    raw_manifest = stable_read(Path(record["manifest_path"]), max_bytes=1024 * 1024)
    if digest(source) != record["digest"] or digest(raw_manifest) != record["manifest_digest"]:
        raise AudioError("catalog_changed", "Registration changed after lookup")
    if decoder_capability()["decoder"]["availability"] != "available":
        raise AudioError("decoder_unavailable", "This profile requires miniaudio==1.71")
    binding = {"operation": "sonic.decode_registered/v1", "registration": record, "profile": DECODER_PROFILE}

    def produce(publication):
        try:
            import miniaudio
        except (ImportError, OSError) as exc:
            raise AudioError("decoder_unavailable", str(exc)) from exc

        manifest_asset = publication.add(raw_manifest, {"kind": "registration_json"}, role="registration")
        source_ref = publication.add(source, {"kind": "source_bytes"}, role="recording_source",
                                     parents=[{"role": "registration", "asset_id": manifest_asset["asset_id"],
                                               "digest": manifest_asset["digest"]}],
                                     provenance={"source_asset_id": source_asset_id, "pack_id": record["pack_id"]})
        try:
            decoded = miniaudio.decode(source, output_format=miniaudio.SampleFormat.SIGNED16,
                                       nchannels=2, sample_rate=44100, dither=miniaudio.DitherMode.NONE)
        except miniaudio.DecodeError as exc:
            raise AudioError("decode_failed", str(exc)) from exc
        if decoded.nchannels != 2 or decoded.sample_rate != 44100 or not decoded.samples:
            raise AudioError("decoder_mismatch", "Decoded audio does not match the profile")
        pcm = PCM(sample_bytes(decoded.samples), 44100, 2)
        publication.add(encode_wav(pcm), pcm.facts(),
                        parents=[{"role": "recording_source", "asset_id": source_ref["asset_id"], "digest": source_ref["digest"]}],
                        provenance={"profile": DECODER_PROFILE, "registration_digest": record["manifest_digest"]})
        return {"findings": [], "limitations": ["Decoded audio is a candidate; user listening has not been recorded."]}

    return store.transact(request_id, binding, produce)


def legacy_operation() -> Operation:
    integer = {"type": "integer", "minimum": 0, "maximum": 230400000}
    schema = object_schema({"start_frame": integer,
                            "frame_count": {"type": "integer", "minimum": 1, "maximum": 230400000},
                            "fade_in_frames": integer, "fade_out_frames": integer,
                            "gain_q15": {"type": "integer", "minimum": 0, "maximum": 32768}})

    def resolve(parameters, pcm):
        if pcm.sample_rate != 44100 or pcm.channels != 2:
            raise AudioError("legacy_format_required", "Legacy recording profile requires 44100 Hz stereo PCM16")
        if (parameters["start_frame"] + parameters["frame_count"] > pcm.frames
                or parameters["fade_in_frames"] > parameters["frame_count"]
                or parameters["fade_out_frames"] > parameters["frame_count"]):
            raise AudioError("invalid_range", "Recording crop/fades are outside the source")
        return dict(parameters)

    def execute(parameters, pcm):
        output = PCM(sample_bytes(_condition_samples(pcm.samples(), parameters)), 44100, 2)
        return output, {"time_mapping": {"kind": "slice", "source_start_frame": parameters["start_frame"],
                                        "output_start_frame": 0, "frame_count": parameters["frame_count"]}}

    return Operation("sonic.recording_condition/v1", schema, resolve, execute, "sonic-fused-q15/v1")


def extend_parser(parser):
    commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    subcommands = commands.add_parser("catalog").add_subparsers(dest="catalog_command", required=True)
    subcommands.add_parser("list")
    decode = subcommands.add_parser("decode")
    decode.add_argument("source_asset_id")
    decode.add_argument("--request-id", required=True)


def handle_extra(args, store):
    if args.command != "catalog":
        raise AudioError("unsupported_command", args.command)
    if args.catalog_command == "list":
        return {"schema": "sonic-catalog/v1", "assets": catalog(), "decoder": decoder_capability()["decoder"]}
    return decode_registered(store, args.source_asset_id, args.request_id)


def prepare_workspace(path):
    root = safe_path(path)
    if root.is_relative_to(REPOSITORY_ROOT):
        authoring_root = REPOSITORY_ROOT / "artifacts"
        if not root.is_relative_to(authoring_root) or root == authoring_root or not (authoring_root / ".gdignore").is_file():
            raise AudioError("workspace_scan_boundary", "Inside SonicMatter, use artifacts/<workspace> beneath artifacts/.gdignore")


def main(argv=None):
    registry = Registry()
    registry.register(legacy_operation())
    return run(argv, product="sonic-matter", registry=registry, allow_import=False,
               extend_parser=extend_parser, handle_extra=handle_extra,
               prepare_workspace=prepare_workspace, capability_extra=decoder_capability)
