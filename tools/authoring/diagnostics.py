"""Static Sonic authoring checks; never import the decoder or open audio data."""

from importlib import metadata
import re

from matter_audio_core.artifacts import safe_path, stable_read
from matter_audio_core.contracts import parse_json
from matter_audio_core.diagnostics import backend_report, check
from matter_audio_core.errors import AudioError

from tools.ui_foley.derive_recordings import DerivativeError, _relative_path


def _decoder_checks():
    try:
        version = metadata.version("miniaudio")
    except metadata.PackageNotFoundError:
        return [check("miniaudio", "dependency", "error", "decoder_not_installed",
                      "The optional recording decoder is not installed.",
                      remedy="Install the pinned authoring requirements from docs/shared-audio.md.")]
    except (OSError, ValueError):
        return [check("miniaudio", "dependency", "error", "decoder_metadata_unreadable",
                      "The optional decoder distribution metadata could not be read.",
                      remedy="Repair the authoring environment using the pinned requirements.")]
    expected = version == "1.71"
    # Version metadata is untrusted display data; never print arbitrary text.
    public_version = version if isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", version) else "unknown"
    return [check("miniaudio", "dependency", "ok" if expected else "error",
                  "decoder_version_matches" if expected else "decoder_version_mismatch",
                  "Recording decoding requires miniaudio 1.71; its native library was not loaded.",
                  remedy="Install the pinned authoring requirements from docs/shared-audio.md.",
                  details={"installed_version": public_version, "required_version": "1.71"})]


def _catalog_checks(repository_root, manifests):
    count, seen = 0, set()
    try:
        repository_root = safe_path(repository_root)
        if not manifests or len(manifests) > 32:
            raise ValueError("manifest_count")
        for relative in manifests:
            path = safe_path(repository_root / relative)
            if not path.is_relative_to(repository_root):
                raise ValueError("manifest_location")
            manifest = parse_json(stable_read(path, max_bytes=1024 * 1024))
            if (not isinstance(manifest, dict)
                    or manifest.get("schema") != "sonicmatter-content-pack-rights/v1"
                    or not isinstance(manifest.get("pack_id"), str) or not manifest["pack_id"]
                    or manifest.get("approval_state") != "approved"
                    or not isinstance(manifest.get("license"), dict)
                    or manifest["license"].get("spdx") != "CC0-1.0"
                    or not isinstance(manifest.get("rights"), dict)
                    or manifest["rights"].get("local_preview") != "allow"
                    or not isinstance(manifest.get("assets"), list)
                    or not 1 <= len(manifest["assets"]) <= 4096):
                raise ValueError("metadata")
            for asset in manifest["assets"]:
                if (not isinstance(asset, dict) or not isinstance(asset.get("asset_id"), str)
                        or not asset["asset_id"] or asset["asset_id"] in seen
                        or not isinstance(asset.get("path"), str)
                        or type(asset.get("size_bytes")) is not int or asset["size_bytes"] <= 0
                        or not isinstance(asset.get("sha256"), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])):
                    raise ValueError("asset_metadata")
                seen.add(asset["asset_id"])
                local = _relative_path(asset["path"], "registered recording")
                source = safe_path(path.parent.joinpath(*local.parts))
                if not source.is_relative_to(path.parent) or not source.is_file():
                    raise ValueError("source_missing")
                if source.stat().st_size != asset["size_bytes"]:
                    raise ValueError("source_size")
                count += 1
    except (OSError, AudioError, ValueError, TypeError, KeyError, DerivativeError):
        return [check("registered_catalog", "file", "error", "catalog_metadata_unavailable",
                      "Registered catalog metadata or source-file presence and sizes did not pass the static check.",
                      remedy="Restore the registered content pack and run its integrity audit; doctor never repairs files.")]
    return [check("registered_catalog", "file", "ok", "catalog_metadata_present",
                  "Registered manifests and source-file sizes are present. Audio content hashes and decoding were not checked.",
                  details={"manifest_count": len(manifests), "asset_count": count})]


def doctor_provider():
    # Import constants only after cli has loaded; do not invoke catalog(), which
    # hashes every recording. No workspace or decoder is required for doctor.
    from .cli import REGISTERED_MANIFESTS, REPOSITORY_ROOT

    return [
        backend_report("sonic.recording_decoder", configured=True, checks=_decoder_checks()),
        backend_report("sonic.registered_catalog", configured=bool(REGISTERED_MANIFESTS),
                       checks=_catalog_checks(REPOSITORY_ROOT, REGISTERED_MANIFESTS)),
    ]
