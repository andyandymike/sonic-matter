"""Sonic doctor reads metadata, never decoder binaries or recording payloads."""

import builtins
from contextlib import ExitStack, redirect_stdout
from importlib import metadata
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    from matter_audio_core.diagnostics import build_report
    from tools.authoring import cli, diagnostics
    CORE_AVAILABLE = True
except ModuleNotFoundError as exc:
    if exc.name != "matter_audio_core":
        raise
    CORE_AVAILABLE = False


@unittest.skipUnless(CORE_AVAILABLE, "Install requirements-authoring.txt for shared authoring tests")
class SonicDiagnosticTests(unittest.TestCase):
    def fixture(self, root):
        source = root / "source.ogg"
        source.write_bytes(b"not-decoded-by-doctor")
        manifest = {"schema": "sonicmatter-content-pack-rights/v1", "pack_id": "fixture",
                    "approval_state": "approved",
                    "license": {"spdx": "CC0-1.0"}, "rights": {"local_preview": "allow"},
                    "assets": [{"asset_id": "fixture", "path": source.name, "sha256": "0" * 64,
                                "size_bytes": source.stat().st_size}]}
        (root / "rights.json").write_text(json.dumps(manifest), encoding="utf-8")
        return source, manifest

    def test_doctor_reads_manifest_and_stats_but_not_audio_or_native_decoder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = self.fixture(root)
            read = diagnostics.stable_read
            opened = []
            original_open, original_import = Path.open, builtins.__import__

            def guard_open(path, *args, **kwargs):
                if path.resolve() == source.resolve():
                    self.fail("Doctor read recording payload")
                return original_open(path, *args, **kwargs)

            def guarded_import(name, *args, **kwargs):
                if name.split(".")[0] in {"miniaudio", "torch", "numpy"}:
                    self.fail("Doctor imported an audio/model runtime")
                return original_import(name, *args, **kwargs)

            def manifest_read(path, **kwargs):
                opened.append(path.name)
                return read(path, **kwargs)

            with patch.object(cli, "REPOSITORY_ROOT", root), patch.object(cli, "REGISTERED_MANIFESTS", ("rights.json",)), \
                    patch.object(diagnostics.metadata, "version", return_value="1.71"), \
                    patch.object(Path, "open", guard_open), patch("builtins.__import__", guarded_import), \
                    patch.object(diagnostics, "stable_read", side_effect=manifest_read):
                result = build_report("sonic-matter", diagnostics.doctor_provider())
            self.assertEqual(opened, ["rights.json"])
            self.assertEqual([item["availability"] for item in result["backends"]], ["available", "available"])
            self.assertEqual(result["backends"][1]["checks"][0]["details"]["asset_count"], 1)
            self.assertIn("hashes", result["backends"][1]["checks"][0]["reason"]["message"])

    def test_missing_decoder_is_optional_and_wrong_version_has_actionable_reason(self):
        for value, expected in ((metadata.PackageNotFoundError("miniaudio"), "decoder_not_installed"),
                                ("0.0", "decoder_version_mismatch")):
            with patch.object(diagnostics.metadata, "version", side_effect=value if isinstance(value, Exception) else None,
                              return_value=value), self.subTest(expected=expected):
                report = diagnostics.doctor_provider()[0]
            self.assertTrue(report["optional"])
            self.assertEqual(report["availability"], "unavailable")
            self.assertEqual(report["checks"][0]["reason"]["code"], expected)
            self.assertTrue(report["checks"][0]["remedy"])

    def test_missing_changed_or_escaping_catalog_sources_fail_without_path_disclosure(self):
        with tempfile.TemporaryDirectory(prefix="private-catalog-") as directory:
            root = Path(directory)
            source, manifest = self.fixture(root)
            for bad_path, bad_size in ((source.name, 999), ("missing.ogg", 1), ("../private.ogg", 1)):
                manifest["assets"][0].update(path=bad_path, size_bytes=bad_size)
                (root / "rights.json").write_text(json.dumps(manifest), encoding="utf-8")
                result = diagnostics._catalog_checks(root, ("rights.json",))
                self.assertEqual(result[0]["status"], "error")
                self.assertEqual(result[0]["reason"]["code"], "catalog_metadata_unavailable")
                self.assertNotIn(str(root), json.dumps(result))
                self.assertNotIn(bad_path, json.dumps(result))

    def test_cli_default_is_read_only_and_does_not_expose_environment_or_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "absent"
            secret = "fixture-secret-needle-221"
            output = io.StringIO()
            with ExitStack() as stack:
                for name in ("socket.create_connection", "subprocess.Popen", "tools.authoring.cli.prepare_workspace",
                             "matter_audio_core.artifacts.ArtifactStore._workspace", "tools.authoring.cli.catalog"):
                    stack.enter_context(patch(name, side_effect=AssertionError("doctor side effect")))
                stack.enter_context(patch.dict(os.environ, {"API_KEY": secret}))
                stack.enter_context(patch.object(diagnostics.metadata, "version", side_effect=OSError(secret)))
                stack.enter_context(redirect_stdout(output))
                code = cli.main(["--workspace", str(workspace), "doctor", "--json"])
            self.assertEqual(code, 0, output.getvalue())
            self.assertFalse(workspace.exists())
            self.assertNotIn(secret, output.getvalue())
            result = json.loads(output.getvalue())
            self.assertEqual(result["schema"], "matter-diagnostics/v1")
            self.assertEqual(result["backends"][0]["checks"][0]["reason"]["code"], "decoder_metadata_unreadable")
            self.assertEqual(result["scope"]["audio_model_calls"], 0)
