"""Explicit project recording snapshots; declarations never grant publication rights."""
from __future__ import annotations

from pathlib import Path

from matter_audio_core.artifacts import ArtifactStore, safe_path, stable_read
from matter_audio_core.contracts import digest, object_schema, parse_json, validate
from matter_audio_core.errors import AudioError
from matter_audio_core.media import MAX_AUDIO_BYTES, decode_wav

from tools.ui_foley.derive_recordings import DerivativeError, _relative_path


PROFILE = "sonic-project-pcm16-wav/v1"
# Same purpose names as Material Lab, without importing its optional NumPy stack.
RIGHTS_ACTIONS = (
    "local_preview", "source_repo_distribution", "material_kit_distribution",
    "game_source_distribution", "game_binary_embedding", "unchanged_redistribution",
    "standalone_baked_audio_distribution", "parameter_fitting", "evaluation_use",
    "evaluation_stimulus_publication", "training", "private_embedding", "index_redistribution",
)
IDENTIFIER = {"type": "string", "pattern": r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$"}
TEXT = {"type": "string", "minLength": 1, "maxLength": 2000, "pattern": r"\S"}
EVIDENCE = object_schema({
    "id": IDENTIFIER,
    "kind": {"enum": ["self_declaration", "license", "permission", "other"]},
    "reference": TEXT,
})
DECISION = object_schema({
    "status": {"enum": ["allow", "deny", "unknown"]},
    "evidence_refs": {"type": "array", "maxItems": 32, "uniqueItems": True, "items": IDENTIFIER},
}, ["status"])
RECORDING = object_schema({
    "recording_id": IDENTIFIER,
    "path": TEXT,
    "sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
    "size_bytes": {"type": "integer", "minimum": 44, "maximum": MAX_AUDIO_BYTES},
    "creator": TEXT,
    "source": object_schema({
        "kind": {"enum": ["self_recorded", "third_party", "synthetic_fixture"]},
        "reference": TEXT,
    }),
    "rights": object_schema({name: DECISION for name in RIGHTS_ACTIONS}, []),
    "evidence": {"type": "array", "maxItems": 32, "items": EVIDENCE},
}, ["recording_id", "path", "sha256", "size_bytes", "creator", "source", "rights", "evidence"])
MANIFEST_SCHEMA = object_schema({
    "schema": {"const": "sonic-project-recordings/v1"},
    "catalog_id": IDENTIFIER,
    "recordings": {"type": "array", "minItems": 1, "maxItems": 128, "items": RECORDING},
})
LIMITATIONS = [
    "Source, creator and rights are supplied declarations, not verified grants.",
    "Evidence references are preserved as text; no referenced document or URL is fetched or verified.",
    "Import does not establish distribution rights or listening acceptance.",
]


def capability() -> dict:
    return {"availability": "available", "profile": PROFILE, "manifest_schema": MANIFEST_SCHEMA,
            "commands": ["recordings list --manifest PATH",
                         "recordings import RECORDING_ID --manifest PATH --request-id ID"],
            "format": "PCM16 WAV, mono/stereo, 8000-192000 Hz, original bytes preserved",
            "rights_verification": "not_performed"}


def _load_manifest(path: Path) -> tuple[Path, bytes, dict]:
    path = safe_path(path)
    raw = stable_read(path, max_bytes=1024 * 1024)
    manifest = parse_json(raw)
    validate(manifest, MANIFEST_SCHEMA)
    ids, paths = set(), set()
    for recording in manifest["recordings"]:
        identifier = recording["recording_id"]
        relative = _recording_path(recording["path"])
        path_key = relative.as_posix().casefold()
        if identifier in ids or path_key in paths:
            raise AudioError("recordings_ambiguous", "Recording IDs and source paths must be unique")
        ids.add(identifier)
        paths.add(path_key)
        evidence_ids = [item["id"] for item in recording["evidence"]]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise AudioError("invalid_recording_evidence", f"Duplicate evidence ID for {identifier}")
        for purpose, decision in recording["rights"].items():
            refs = decision.get("evidence_refs", [])
            if set(refs) - set(evidence_ids):
                raise AudioError("invalid_recording_evidence", f"Unknown evidence reference for {identifier}/{purpose}")
            if decision["status"] == "allow" and not refs:
                raise AudioError("invalid_recording_evidence", f"Allow requires evidence references for {identifier}/{purpose}")
    return path, raw, manifest


def _recording_path(value: str):
    try:
        relative = _relative_path(value, "recording.path")
    except DerivativeError as exc:
        raise AudioError("invalid_recording_path", str(exc)) from exc
    if relative.suffix.lower() != ".wav":
        raise AudioError("unsupported_audio", "Project recordings must be PCM16 WAV files")
    return relative


def _read_recording(manifest_path: Path, recording: dict):
    relative = _recording_path(recording["path"])
    source_path = safe_path(manifest_path.parent.joinpath(*relative.parts))
    if not source_path.is_relative_to(manifest_path.parent):
        raise AudioError("unsafe_path", "Recording escaped its manifest directory")
    data = stable_read(source_path)
    if digest(data)["hex"] != recording["sha256"] or len(data) != recording["size_bytes"]:
        raise AudioError("recording_integrity_error", f"Recording changed: {recording['recording_id']}")
    return source_path, data, decode_wav(data)


def _declarations(recording: dict) -> dict:
    return {"creator": recording["creator"], "source": recording["source"],
            "rights": {name: recording["rights"].get(name, {"status": "unknown"}) for name in RIGHTS_ACTIONS},
            "evidence": recording["evidence"], "rights_verification": "not_performed",
            "publication_eligibility": "not_evaluated", "listening": "not_performed"}


def list_recordings(manifest_path: Path) -> dict:
    path, raw, manifest = _load_manifest(manifest_path)
    if sum(item["size_bytes"] for item in manifest["recordings"]) > MAX_AUDIO_BYTES:
        raise AudioError("recordings_limit", "Listing supports at most 64 MiB of combined recording data")
    records = []
    for recording in manifest["recordings"]:
        source, data, pcm = _read_recording(path, recording)
        declarations = _declarations(recording)
        records.append({"recording_id": recording["recording_id"], "path": str(source),
                        "digest": digest(data), "byte_count": len(data), "media": pcm.facts(),
                        "local_preview_declared_allowed": declarations["rights"]["local_preview"]["status"] == "allow",
                        **declarations})
    if stable_read(path, max_bytes=1024 * 1024) != raw:
        raise AudioError("recordings_changed", "Manifest changed during listing")
    return {"schema": "sonic-project-recording-list/v1", "status": "succeeded",
            "catalog_id": manifest["catalog_id"], "manifest_digest": digest(raw),
            "recordings": records, "limitations": LIMITATIONS, "audio_model_calls": 0}


def import_recording(store: ArtifactStore, manifest_path: Path, recording_id: str, request_id: str) -> dict:
    path, raw, manifest = _load_manifest(manifest_path)
    recording = next((item for item in manifest["recordings"] if item["recording_id"] == recording_id), None)
    if recording is None:
        raise AudioError("recording_not_found", recording_id)
    declarations = _declarations(recording)
    if declarations["rights"]["local_preview"]["status"] != "allow":
        raise AudioError("recording_use_not_allowed", "Import requires an explicit local_preview allow declaration")
    source_path, data, pcm = _read_recording(path, recording)
    if stable_read(path, max_bytes=1024 * 1024) != raw:
        raise AudioError("recordings_changed", "Manifest changed while taking the source snapshot")
    binding = {"operation": "sonic.import_project_recording/v1", "profile": PROFILE,
               "catalog_id": manifest["catalog_id"], "recording_id": recording_id,
               "manifest_digest": digest(raw), "source_digest": digest(data)}

    def produce(publication):
        registration = publication.add(raw, {"kind": "registration_json"}, role="registration",
                                       provenance={"manifest_path": str(path), "catalog_id": manifest["catalog_id"]})
        source = publication.add(data, {"kind": "source_bytes"}, role="recording_source",
                                 parents=[{"role": "registration", "asset_id": registration["asset_id"],
                                           "digest": registration["digest"]}],
                                 provenance={"path": str(source_path), "recording_id": recording_id, **declarations})
        publication.add(data, pcm.facts(), parents=[{"role": "recording_source", "asset_id": source["asset_id"],
                                                    "digest": source["digest"]}],
                        provenance={"profile": PROFILE, "recording_id": recording_id, **declarations})
        return {"findings": [], "limitations": LIMITATIONS, "rights_verification": "not_performed",
                "publication_eligibility": "not_evaluated", "listening": "not_performed"}

    return store.transact(request_id, binding, produce)
