"""Verify installed product CLIs and adapter tests without models or playback."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "sonic-matter"
ENTRY = ['tools.authoring']


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    require(importlib.metadata.version("matter-audio-core") == "0.6.0", "Install the pinned core 0.6.0")
    if PRODUCT == "score-matter":
        requirements = importlib.metadata.requires("score-matter") or []
        require(any("matter-audio-core" in item and "audio" in item for item in requirements),
                "Reinstall ScoreMatter to refresh its audio extra metadata")
    else:
        require(importlib.metadata.version("miniaudio") == "1.71", "Install the pinned recording decoder")

    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for directory, pattern in [('tests/authoring', 'test_*.py')]:
        suite.addTests(loader.discover(str(ROOT / directory), pattern=pattern))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    require(outcome.wasSuccessful() and not outcome.skipped, "Shared audio tests must pass without skips")

    with tempfile.TemporaryDirectory(prefix="matter-product-check-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        calls = 0

        def call(*arguments):
            nonlocal calls
            result = subprocess.run([sys.executable, "-m", *ENTRY, "--workspace", str(workspace),
                                     *map(str, arguments), "--json"], cwd=ROOT,
                                    capture_output=True, encoding="utf-8", timeout=120)
            calls += 1
            require(result.returncode == 0, f"CLI failed: {arguments}\n{result.stdout}\n{result.stderr}")
            value = json.loads(result.stdout)
            require(value.get("status") != "failed", f"Authoring failed: {value}")
            return value

        def write(commands, body):
            path = root / f"request-{calls}.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            return call(*commands, "--request", path)

        def action(identifier, operation, asset, parameters):
            require(operation in {"normalize/v1", "loop/v1", "scene/v1"}, "Only PCM operations belong in this smoke")
            result = write(["action", "execute"], {"schema": "matter-action/v1", "request_id": identifier,
                           "operation": operation, "inputs": [asset["asset_id"]], "parameters": parameters})
            require(result["status"] == "succeeded" and result["audio_model_calls"] == 0, "Expected zero-model PCM output")
            return result["outputs"][0]

        capabilities = call("capabilities")
        require(capabilities["product"] == PRODUCT and capabilities["core_version"] == "0.6.0", "Wrong product/core routing")
        require({"normalize/v1", "loop/v1", "scene/v1", "analyze/v1"}.issubset(
            {item["operation"] for item in capabilities["operations"]}), "M4 operations are missing")
        require(capabilities["cue_sets"]["availability"] == capabilities["library"]["availability"] == "available",
                "Cue packages or local search are unavailable")
        project_recordings = capabilities["product_capabilities"]["project_recordings"]
        require(project_recordings["availability"] == "available" and
                project_recordings["manifest_schema"]["properties"]["schema"]["const"] == "sonic-project-recordings/v1",
                "Project recording schema is not discoverable")

        if PRODUCT == "score-matter":
            from matter_audio_core.media import PCM, encode_wav, sample_bytes
            source = root / "synthetic.wav"
            source.write_bytes(encode_wav(PCM(sample_bytes(array("h", [-2000, 0, 2000, 0] * 2000)), 8000, 1)))
            original = source.read_bytes()
            asset = call("assets", "import", source, "--request-id", "input")["outputs"][0]
        else:
            catalog = call("catalog", "list")
            require(catalog["decoder"]["availability"] == "available", "Recording decoder unavailable")
            registration = next(item for item in catalog["assets"] if item["source_asset_id"] == "starninjas.book-flip.08")
            source = Path(registration["path"])
            original = source.read_bytes()
            require(hashlib.sha256(original).hexdigest() == registration["digest"]["hex"], "Recording registration changed")
            decoded = call("catalog", "decode", registration["source_asset_id"], "--request-id", "input")
            require(decoded["audio_model_calls"] == 0, "Decoding must not call a model")
            asset = next(item for item in decoded["outputs"] if item["role"] == "audio")

        from matter_audio_core.media import PCM, encode_wav, sample_bytes
        project_source = root / "project-recording.wav"
        payload = encode_wav(PCM(sample_bytes(array("h", [-1000, 1000] * 100)), 8000, 1))
        payload = payload[:12] + b"JUNK" + struct.pack("<I", 4) + b"note" + payload[12:]
        payload = payload[:4] + struct.pack("<I", len(payload) - 8) + payload[8:]
        project_source.write_bytes(payload)
        project_manifest = root / "project-recordings.json"
        project_manifest.write_text(json.dumps({"schema": "sonic-project-recordings/v1", "catalog_id": "check",
            "recordings": [{"recording_id": "fixture", "path": project_source.name,
                "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload), "creator": "Engineering fixture",
                "source": {"kind": "synthetic_fixture", "reference": "Created by the zero-model shared smoke"},
                "rights": {"local_preview": {"status": "allow", "evidence_refs": ["fixture"]}},
                "evidence": [{"id": "fixture", "kind": "self_declaration", "reference": "Synthetic test-only PCM"}]}]}),
            encoding="utf-8")
        manifest_original = project_manifest.read_bytes()
        listed = call("recordings", "list", "--manifest", project_manifest)
        require(listed["recordings"][0]["rights"]["game_binary_embedding"]["status"] == "unknown",
                "Project input must not gain distribution rights")
        project_import = call("recordings", "import", "fixture", "--manifest", project_manifest, "--request-id", "project-input")
        require(call("recordings", "import", "fixture", "--manifest", project_manifest, "--request-id", "project-input") == project_import,
                "Project recording retry changed its receipt")
        project_audio = next(item for item in project_import["outputs"] if item["role"] == "audio")
        require((workspace / project_audio["locator"]).read_bytes() == payload and
                project_import["rights_verification"] == "not_performed" and project_import["audio_model_calls"] == 0,
                "Project WAV snapshot changed bytes or promoted rights")
        write(["cue-set", "create"], {"schema": "matter-cue-set/v1", "set_id": "project-input", "name": "Project input",
            "cues": [{"key": "fixture", "name": "Fixture", "selected_variant": "main",
                      "variants": [{"key": "main", "asset_id": project_audio["asset_id"]}]}]})
        project_export = write(["cue-set", "export"], {"schema": "matter-cue-export/v1", "request_id": "project-delivery",
                                                      "set_id": "project-input", "variants": "selected"})
        project_entry = project_export["body"]["entries"][0]
        require((Path(project_export["directory"]) / project_entry["filename"]).read_bytes() == payload,
                "Project WAV export changed ancillary metadata or PCM bytes")
        require(project_source.read_bytes() == payload and project_manifest.read_bytes() == manifest_original,
                "Project input files were modified")

        normalized = action("level", "normalize/v1", asset, {"target_rms_dbfs": -24, "max_boost_db": 24})
        analysis = call("analyze", normalized["asset_id"])["analysis"]
        require(analysis["rms_dbfs"] is not None, "Expected a non-silent measured fixture")
        end = min(4096, normalized["media"]["frame_count"])
        loop = action("loop", "loop/v1", normalized, {"start_frame": 0, "end_frame": end, "crossfade_frames": 64})
        length = loop["media"]["frame_count"]
        require(length == end - 64, "Unexpected overlap loop frame count")
        scene = action("scene", "scene/v1", loop, {"duration_frames": length * 2, "tracks": [{"name": "bed", "db": -6}],
            "events": [{"event_id": "repeat", "input_index": 0, "track": "bed", "source_start_frame": 0,
                        "source_end_frame": length, "offset_frame": 0, "repeat": 2}]})
        require(scene["media"]["frame_count"] == length * 2, "Scene duration changed")
        write(["session", "create"], {"schema": "matter-session-create/v1", "request_id": "session-create",
              "session_id": "check", "name": "Engineering fixture", "asset_id": loop["asset_id"]})
        package = write(["cue-set", "create"], {"schema": "matter-cue-set/v1", "set_id": "check-v1", "name": "Engineering fixtures",
            "cues": [{"key": "loop", "name": "Loop", "selected_variant": "main", "variants": [{"key": "main", "asset_id": loop["asset_id"],
                       "loop": {"begin_frame": 0, "end_frame": length}, "selection": {"session_id": "check", "revision": 1}}]},
                     {"key": "scene", "name": "Scene", "selected_variant": "main", "variants": [{"key": "main", "asset_id": scene["asset_id"]}]}]})
        delivery = write(["cue-set", "export"], {"schema": "matter-cue-export/v1", "request_id": "delivery", "set_id": "check-v1", "variants": "selected"})
        require(len(delivery["files"]) == 2, "Expected two exported WAV files")
        originals = {item["asset_id"]: (workspace / item["locator"]).read_bytes() for item in (loop, scene)}
        for entry in delivery["body"]["entries"]:
            require((Path(delivery["directory"]) / entry["filename"]).read_bytes() == originals[entry["asset"]["asset_id"]],
                    "Cue export changed the saved artifact bytes")
        require(call("cue-set", "export-show", "delivery") == delivery, "Export replay changed its receipt")
        require(call("cue-set", "show", "check-v1") == package, "Cue export changed the source package")
        write(["library", "create"], {"schema": "matter-library/v1", "library_id": "check", "name": "Engineering fixtures",
              "entries": [{"asset_id": item["asset_id"], "name": name, "tags": ["integration"]} for item, name in [(loop, "Loop"), (scene, "Scene")]]})
        matches = write(["library", "search"], {"schema": "matter-library-search/v1", "library_id": "check",
                        "tags": ["integration"], "similar_to": loop["asset_id"]})
        require(matches["total_matches"] == 2 and matches["items"][0]["asset_id"] == loop["asset_id"]
                and matches["items"][0]["distance"] == 0, "Measured search returned unexpected results")
        require(source.read_bytes() == original, "Authoring modified the original source")

    print(json.dumps({"status": "passed", "product": PRODUCT, "core_version": "0.6.0", "adapter_tests": outcome.testsRun,
                      "cli_calls": calls, "exported_wavs": 3, "exact_export_bytes": True,
                      "project_recording_snapshot": "original_wav_bytes_and_declarations",
                      "audio_model_calls": 0, "human_listening": "not_performed"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
