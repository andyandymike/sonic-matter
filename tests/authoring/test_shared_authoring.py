from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

try:
    from matter_audio_core.actions import ActionService, Registry
    from matter_audio_core.artifacts import ArtifactStore
    from matter_audio_core.contracts import digest, request
    from matter_audio_core.errors import AudioError
    from matter_audio_core.media import PCM, decode_wav, encode_wav, sample_bytes
    from tools.authoring import cli
    CORE_AVAILABLE = True
except ModuleNotFoundError as exc:
    if exc.name != "matter_audio_core":
        raise
    CORE_AVAILABLE = False
from tools.ui_foley.derive_recordings import _condition_samples, _wav_bytes


@unittest.skipUnless(CORE_AVAILABLE, "Install requirements-authoring.txt for shared authoring tests")
class SonicAuthoringTests(unittest.TestCase):
    def test_capabilities_keep_decoder_optional(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli.main(["capabilities", "--json"])
        self.assertEqual(status, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["product"], "sonic-matter")
        self.assertIn("sonic.recording_condition/v1", [item["operation"] for item in result["operations"]])

    def test_arbitrary_import_is_not_a_sonic_catalog_entry(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli.main(["assets", "import", "unknown.wav"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "invalid_arguments")

    def test_unsafe_in_repo_workspace_is_rejected(self):
        with self.assertRaises(AudioError):
            cli.prepare_workspace(cli.REPOSITORY_ROOT / "new-workspace")

    def test_fused_profile_matches_legacy_golden(self):
        samples = array("h")
        for frame in range(2000):
            samples.extend(((frame * 1733 % 30000) - 15000, 12000 - (frame * 997 % 24000)))
        parameters = {"start_frame": 20, "frame_count": 1764, "fade_in_frames": 88,
                      "fade_out_frames": 176, "gain_q15": 19661}
        expected = _wav_bytes(_condition_samples(samples, parameters))
        self.assertEqual(digest(expected)["hex"], "e73eec7d4cdd11e9baca667f785759d7b17ebcedd4fe23319a1f14cbf697b9fa")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "decoded.wav"
            source.write_bytes(encode_wav(PCM(sample_bytes(samples), 44100, 2)))
            store = ArtifactStore(root / "workspace", product="sonic-matter")
            imported = store.import_wav(source, "fixture-import")
            registry = Registry()
            registry.register(cli.legacy_operation())
            result = ActionService(store, registry).execute(request("fused", "sonic.recording_condition/v1",
                                                         imported["outputs"][0]["asset_id"], parameters))
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(store.asset(result["outputs"][0]["asset_id"])[1], expected)

    def test_catalog_binds_current_source_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.ogg"
            source.write_bytes(b"registered fixture source")
            manifest = {"schema": "sonicmatter-content-pack-rights/v1", "pack_id": "fixture",
                        "approval_state": "approved", "license": {"spdx": "CC0-1.0"},
                        "rights": {"local_preview": "allow"}, "assets": [
                            {"asset_id": "fixture.1", "path": "sample.ogg", "sha256": digest(source.read_bytes())["hex"],
                             "size_bytes": source.stat().st_size}]}
            (root / "rights.json").write_text(json.dumps(manifest))
            with patch.object(cli, "REPOSITORY_ROOT", root), patch.object(cli, "REGISTERED_MANIFESTS", ("rights.json",)):
                self.assertEqual(len(cli.catalog()), 1)
                source.write_bytes(b"changed")
                with self.assertRaises(AudioError):
                    cli.catalog()

from tools.authoring import main as entry_main


class AudioDependencyTests(unittest.TestCase):
    """The base installation must remain usable without the optional core."""

    def call_with_core(self, replacement):
        import builtins
        from unittest.mock import patch
        original_import = builtins.__import__

        def substitute(name, *args, **kwargs):
            if name == "matter_audio_core":
                if isinstance(replacement, Exception):
                    raise replacement
                return replacement
            return original_import(name, *args, **kwargs)

        output = io.StringIO()
        with patch("builtins.__import__", side_effect=substitute), contextlib.redirect_stdout(output):
            code = entry_main(["capabilities", "--json"])
        return code, json.loads(output.getvalue())

    def test_missing_optional_core_has_an_installation_error(self):
        code, response = self.call_with_core(ModuleNotFoundError("No core installed", name="matter_audio_core"))
        self.assertEqual(code, 2)
        self.assertEqual(response["error"]["code"], "audio_dependency_missing")

    def test_old_optional_core_is_rejected_before_loading_adapters(self):
        from types import SimpleNamespace
        code, response = self.call_with_core(SimpleNamespace(__version__="0.5.0"))
        self.assertEqual(code, 2)
        self.assertEqual(response["error"]["code"], "audio_dependency_incompatible")
        self.assertEqual(response["error"]["details"]["installed_core_version"], "0.5.0")

    def test_broken_core_dependency_is_not_reported_as_missing_core(self):
        with self.assertRaises(ModuleNotFoundError) as caught:
            self.call_with_core(ModuleNotFoundError("Broken dependency", name="broken_dependency"))
        self.assertEqual(caught.exception.name, "broken_dependency")
