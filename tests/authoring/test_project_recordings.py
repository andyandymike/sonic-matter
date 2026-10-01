from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import struct
import subprocess
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

try:
    from matter_audio_core.artifacts import ArtifactStore
    from matter_audio_core.contracts import digest
    from matter_audio_core.errors import AudioError
    from matter_audio_core.media import PCM, encode_wav, sample_bytes
    from tools.authoring import cli, recordings
    CORE_AVAILABLE = True
except ModuleNotFoundError as exc:
    if exc.name != "matter_audio_core":
        raise
    CORE_AVAILABLE = False


@unittest.skipUnless(CORE_AVAILABLE, "Install requirements-authoring.txt for project recording tests")
class ProjectRecordingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / "audio" / "door.wav"
        self.source.parent.mkdir()
        wav = encode_wav(PCM(sample_bytes(array("h", [100, -100, 200, -200])), 8000, 1))
        # Valid ancillary RIFF metadata proves the main audio is not re-encoded.
        wav = wav[:12] + b"JUNK" + struct.pack("<I", 4) + b"note" + wav[12:]
        self.original = wav[:4] + struct.pack("<I", len(wav) - 8) + wav[8:]
        self.source.write_bytes(self.original)
        self.manifest_path = self.root / "recordings.json"
        self.manifest = {
            "schema": "sonic-project-recordings/v1", "catalog_id": "my-game",
            "recordings": [{
                "recording_id": "door", "path": "audio/door.wav",
                "sha256": digest(self.original)["hex"], "size_bytes": len(self.original),
                "creator": "Fixture author", "source": {"kind": "synthetic_fixture", "reference": "Test-only PCM"},
                "rights": {"local_preview": {"status": "allow", "evidence_refs": ["fixture"]}},
                "evidence": [{"id": "fixture", "kind": "self_declaration", "reference": "Generated solely for this test"}],
            }],
        }
        self.write_manifest()
        self.store = ArtifactStore(self.root / "workspace", product="sonic-matter")

    def write_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")

    def import_recording(self, request_id="import-one"):
        return recordings.import_recording(self.store, self.manifest_path, "door", request_id)

    def test_snapshots_keep_original_wav_metadata_and_complete_lineage(self):
        raw = self.manifest_path.read_bytes()
        result = self.import_recording()
        registration, source, audio = result["outputs"]
        self.assertEqual([item["role"] for item in result["outputs"]], ["registration", "recording_source", "audio"])
        self.assertEqual(self.store.asset(registration["asset_id"])[1], raw)
        self.assertEqual(self.store.asset(source["asset_id"])[1], self.original)
        self.assertEqual(self.store.asset(audio["asset_id"])[1], self.original)
        self.assertEqual(source["parents"][0]["asset_id"], registration["asset_id"])
        self.assertEqual(audio["parents"][0]["asset_id"], source["asset_id"])
        self.assertEqual(audio["media"]["sample_rate_hz"], 8000)
        self.assertEqual(audio["media"]["channels"], 1)
        self.assertEqual(result["audio_model_calls"], 0)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.manifest_path.read_bytes(), raw)

    def test_retry_replays_exact_result_and_changed_declarations_conflict(self):
        first = self.import_recording()
        self.assertEqual(self.import_recording(), first)
        self.manifest["recordings"][0]["creator"] = "Changed declaration"
        self.write_manifest()
        with self.assertRaises(AudioError) as caught:
            self.import_recording()
        self.assertEqual(caught.exception.code, "request_conflict")
        self.assertEqual(self.store.show_request("import-one"), first)

    def test_changed_valid_source_conflicts_with_original_request(self):
        first = self.import_recording()
        changed = encode_wav(PCM(sample_bytes(array("h", [300, -300])), 8000, 1))
        self.source.write_bytes(changed)
        self.manifest["recordings"][0].update(sha256=digest(changed)["hex"], size_bytes=len(changed))
        self.write_manifest()
        with self.assertRaises(AudioError) as caught:
            self.import_recording()
        self.assertEqual(caught.exception.code, "request_conflict")
        self.assertEqual(self.store.show_request("import-one"), first)

    def test_declared_allow_is_not_promoted_to_verified_or_publishable(self):
        self.manifest["recordings"][0]["rights"]["game_binary_embedding"] = {
            "status": "allow", "evidence_refs": ["fixture"]}
        self.write_manifest()
        result = self.import_recording()
        declarations = result["outputs"][-1]["provenance"]
        self.assertEqual(declarations["rights"]["game_binary_embedding"]["status"], "allow")
        self.assertEqual(declarations["rights"]["training"]["status"], "unknown")
        self.assertEqual(result["rights_verification"], "not_performed")
        self.assertEqual(result["publication_eligibility"], "not_evaluated")
        self.assertEqual(result["listening"], "not_performed")

    def test_list_is_read_only_and_denied_or_unknown_preview_cannot_import(self):
        for rights in ({}, {"local_preview": {"status": "unknown"}}, {"local_preview": {"status": "deny"}}):
            with self.subTest(rights=rights):
                self.manifest["recordings"][0]["rights"] = rights
                self.manifest["recordings"][0]["evidence"] = []
                self.write_manifest()
                result = recordings.list_recordings(self.manifest_path)
                self.assertFalse(result["recordings"][0]["local_preview_declared_allowed"])
                with self.assertRaises(AudioError) as caught:
                    self.import_recording()
                self.assertEqual(caught.exception.code, "recording_use_not_allowed")
                self.assertFalse(self.store.root.exists())

    def test_only_allow_requires_known_evidence_and_duplicate_ids_fail(self):
        cases = [
            {"status": "allow"},
            {"status": "allow", "evidence_refs": ["missing"]},
            {"status": "deny", "evidence_refs": ["missing"]},
        ]
        for decision in cases:
            with self.subTest(decision=decision):
                self.manifest["recordings"][0]["rights"]["local_preview"] = decision
                self.write_manifest()
                with self.assertRaises(AudioError) as caught:
                    recordings.list_recordings(self.manifest_path)
                self.assertEqual(caught.exception.code, "invalid_recording_evidence")
        self.manifest["recordings"][0]["evidence"] *= 2
        self.write_manifest()
        with self.assertRaises(AudioError):
            self.import_recording()
        self.assertFalse(self.store.root.exists())

    def test_malformed_schema_duplicate_json_and_unsafe_paths_fail_before_publication(self):
        baseline = copy.deepcopy(self.manifest)
        for path in ("../door.wav", "/door.wav", "C:/door.wav", "audio\\door.wav", "audio/CON.wav"):
            with self.subTest(path=path):
                self.manifest = copy.deepcopy(baseline)
                self.manifest["recordings"][0]["path"] = path
                self.write_manifest()
                with self.assertRaises(AudioError):
                    self.import_recording()
        self.manifest = copy.deepcopy(baseline)
        self.manifest["recordings"][0]["approval_state"] = "approved"
        self.write_manifest()
        with self.assertRaises(AudioError):
            self.import_recording()
        self.manifest_path.write_text('{"schema": "first", "schema": "second"}', encoding="utf-8")
        with self.assertRaises(AudioError):
            self.import_recording()
        self.assertFalse(self.store.root.exists())

    def test_duplicate_recording_ids_and_casefold_paths_fail(self):
        first = self.manifest["recordings"][0]
        for changed in ({"path": "audio/second.wav"}, {"recording_id": "second", "path": "audio/DOOR.WAV"}):
            with self.subTest(changed=changed):
                self.manifest["recordings"] = [first, {**first, **changed}]
                self.write_manifest()
                with self.assertRaises(AudioError) as caught:
                    self.import_recording()
                self.assertEqual(caught.exception.code, "recordings_ambiguous")

    def test_source_mismatch_and_non_pcm16_fail_before_publication(self):
        self.source.write_bytes(self.original[:-2])
        with self.assertRaises(AudioError) as caught:
            self.import_recording()
        self.assertEqual(caught.exception.code, "recording_integrity_error")
        invalid = bytearray(self.original)
        fmt = invalid.index(b"fmt ") + 8
        struct.pack_into("<H", invalid, fmt, 3)  # IEEE float is not PCM16.
        self.source.write_bytes(invalid)
        self.manifest["recordings"][0]["sha256"] = digest(invalid)["hex"]
        self.write_manifest()
        with self.assertRaises(AudioError) as caught:
            self.import_recording()
        self.assertEqual(caught.exception.code, "unsupported_audio")
        self.assertFalse(self.store.root.exists())

    def test_manifest_change_during_snapshot_fails_before_publication(self):
        real_read = recordings.stable_read
        reads = 0
        def changing_read(path, **kwargs):
            nonlocal reads
            data = real_read(path, **kwargs)
            if path == self.manifest_path:
                reads += 1
                if reads == 2:
                    return data + b" "
            return data
        with patch.object(recordings, "stable_read", side_effect=changing_read):
            with self.assertRaises(AudioError) as caught:
                self.import_recording()
        self.assertEqual(caught.exception.code, "recordings_changed")
        self.assertFalse(self.store.root.exists())

    def test_linked_source_ancestor_is_rejected(self):
        alias = self.root / "linked"
        if os.name == "nt":
            result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(alias), str(self.source.parent)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.addCleanup(alias.rmdir)
        else:
            alias.symlink_to(self.source.parent, target_is_directory=True)
            self.addCleanup(alias.unlink)
        self.manifest["recordings"][0]["path"] = "linked/door.wav"
        self.write_manifest()
        with self.assertRaises(AudioError) as caught:
            self.import_recording()
        self.assertEqual(caught.exception.code, "unsafe_path")
        self.assertFalse(self.store.root.exists())

    def test_cli_and_capabilities_work_without_recording_decoder(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["capabilities", "--json"])
        self.assertEqual(code, 0)
        capability = json.loads(output.getvalue())["product_capabilities"]["project_recordings"]
        self.assertEqual(capability["manifest_schema"], recordings.MANIFEST_SCHEMA)
        output = io.StringIO()
        with patch.object(cli, "decoder_capability", side_effect=AssertionError("Decoder must not be checked")), contextlib.redirect_stdout(output):
            code = cli.main(["--workspace", str(self.store.root), "recordings", "import", "door",
                             "--manifest", str(self.manifest_path), "--request-id", "cli-input", "--json"])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
