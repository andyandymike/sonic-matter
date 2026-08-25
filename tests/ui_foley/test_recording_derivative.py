from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.ui_foley.derive_recordings import (
    DerivativeError,
    _audio_metrics,
    _condition_samples,
    _wav_bytes,
    _write_wav,
    load_derivative_recipe,
)

derivative_module = importlib.import_module("tools.ui_foley.derive_recordings")


def _fixture_recipe() -> dict:
    return {
        "schema": "sonic-ui-recording-derivative/v1",
        "recipe_id": "fixture.paper-switch.cc0",
        "created_date": "2026-08-21",
        "generator": {
            "id": "sonicmatter.ui-recording-derivative",
            "version": "1.0.0",
        },
        "parent": {
            "pack_id": "fixture.approved-recordings.cc0",
            "version": "1.0.0",
            "manifest_path": "content-packs/fixture/asset-rights.json",
            "manifest_sha256": "0" * 64,
        },
        "decoder": {
            "package": "miniaudio",
            "version": "1.71",
            "sample_format": "SIGNED16",
            "sample_rate_hz": 44100,
            "channels": 2,
        },
        "outputs": [
            {
                "asset_id": "fixture:paper-switch:01",
                "cue_id": "ui.foley.evidence_switch",
                "variant": 1,
                "source_asset_id": "fixture.parent.01",
                "source_path": "content-packs/fixture/audio/parent.ogg",
                "source_sha256": "1" * 64,
                "output_path": "audio/evidence_switch_01.wav",
                "output_sha256": (
                    "e73eec7d4cdd11e9baca667f785759d7"
                    "b17ebcedd4fe23319a1f14cbf697b9fa"
                ),
                "start_frame": 20,
                "frame_count": 1764,
                "fade_in_frames": 88,
                "fade_out_frames": 176,
                "gain_q15": 19661,
            }
        ],
        "rights": {
            "spdx": "CC0-1.0",
            "derivative_of_approved_cc0_recordings": True,
            "game_source_distribution": "allow",
            "game_binary_embedding": "allow",
        },
    }


def _synthetic_samples() -> array:
    source = array("h")
    for frame in range(2000):
        source.extend(
            (
                (frame * 1733 % 30000) - 15000,
                12000 - (frame * 997 % 24000),
            )
        )
    return source


def _public_pipeline_fixture(
    root: Path,
) -> tuple[dict, SimpleNamespace, Path, Path]:
    source_path = root / "content-packs" / "fixture" / "audio" / "parent.ogg"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"fake audited ogg bytes")
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()

    parent_manifest = {
        "schema": "sonicmatter-content-pack-rights/v1",
        "pack_id": "fixture.approved-recordings.cc0",
        "version": "1.0.0",
        "approval_state": "approved",
        "license": {"spdx": "CC0-1.0"},
        "rights": {
            "game_source_distribution": "allow",
            "game_binary_embedding": "allow",
        },
        "assets": [
            {
                "asset_id": "fixture.parent.01",
                "path": "audio/parent.ogg",
                "sha256": source_sha,
            }
        ],
    }
    parent_manifest_path = root / "content-packs" / "fixture" / "asset-rights.json"
    parent_manifest_path.write_text(
        json.dumps(parent_manifest, sort_keys=True), encoding="utf-8"
    )

    recipe = _fixture_recipe()
    recipe["parent"]["manifest_sha256"] = hashlib.sha256(
        parent_manifest_path.read_bytes()
    ).hexdigest()
    recipe["outputs"][0]["source_sha256"] = source_sha
    samples = _synthetic_samples()
    rendered = _condition_samples(samples, recipe["outputs"][0])
    recipe["outputs"][0]["output_sha256"] = hashlib.sha256(
        _wav_bytes(rendered)
    ).hexdigest()

    fake_miniaudio = SimpleNamespace(
        __version__="1.71",
        SampleFormat=SimpleNamespace(SIGNED16="SIGNED16"),
        decode_file=lambda *_args, **_kwargs: SimpleNamespace(
            samples=samples,
            nchannels=2,
            sample_rate=44100,
        ),
    )
    authoring_root = root / "artifacts" / "ui-foley"
    output_root = authoring_root / "fixture-paper-switch"
    return recipe, fake_miniaudio, authoring_root, output_root


class RecordingDerivativeDeterminismTests(unittest.TestCase):
    def test_synthetic_pcm_derivative_matches_frozen_wav_oracle(self) -> None:
        recipe = {
            "schema": "sonic-ui-recording-derivative/v1",
            "recipe_id": "fixture.paper-switch.cc0",
            "created_date": "2026-08-21",
            "generator": {
                "id": "sonicmatter.ui-recording-derivative",
                "version": "1.0.0",
            },
            "parent": {
                "pack_id": "fixture.approved-recordings.cc0",
                "version": "1.0.0",
                "manifest_path": "content-packs/fixture/asset-rights.json",
                "manifest_sha256": "0" * 64,
            },
            "decoder": {
                "package": "miniaudio",
                "version": "1.71",
                "sample_format": "SIGNED16",
                "sample_rate_hz": 44100,
                "channels": 2,
            },
            "outputs": [
                {
                    "asset_id": "fixture:paper-switch:01",
                    "cue_id": "ui.foley.evidence_switch",
                    "variant": 1,
                    "source_asset_id": "fixture.parent.01",
                    "source_path": "content-packs/fixture/audio/parent.wav",
                    "source_sha256": "1" * 64,
                    "output_path": "audio/evidence_switch_01.wav",
                    "output_sha256": (
                        "e73eec7d4cdd11e9baca667f785759d7"
                        "b17ebcedd4fe23319a1f14cbf697b9fa"
                    ),
                    "start_frame": 20,
                    "frame_count": 1764,
                    "fade_in_frames": 88,
                    "fade_out_frames": 176,
                    "gain_q15": 19661,
                }
            ],
            "rights": {
                "spdx": "CC0-1.0",
                "derivative_of_approved_cc0_recordings": True,
                "game_source_distribution": "allow",
                "game_binary_embedding": "allow",
            },
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe_path = root / "recipe.json"
            recipe_path.write_text(
                json.dumps(recipe, sort_keys=True), encoding="utf-8"
            )
            validated = load_derivative_recipe(recipe_path)
            definition = validated["outputs"][0]

            source = array("h")
            for frame in range(2000):
                source.extend(
                    (
                        (frame * 1733 % 30000) - 15000,
                        12000 - (frame * 997 % 24000),
                    )
                )

            first = _condition_samples(source, definition)
            second = _condition_samples(source, definition)
            self.assertEqual(first, second)

            metrics = _audio_metrics(first)
            self.assertEqual(0, metrics["clipped_sample_count"])
            self.assertTrue(metrics["first_frame_silent"])
            self.assertTrue(metrics["last_frame_silent"])

            first_path = root / "first.wav"
            second_path = root / "second.wav"
            _write_wav(first_path, first)
            _write_wav(second_path, second)
            self.assertEqual(first_path.read_bytes(), second_path.read_bytes())
            self.assertEqual(
                "e73eec7d4cdd11e9baca667f785759d7b17ebcedd4fe23319a1f14cbf697b9fa",
                hashlib.sha256(first_path.read_bytes()).hexdigest(),
            )

            with wave.open(str(first_path), "rb") as rendered:
                self.assertEqual(2, rendered.getnchannels())
                self.assertEqual(2, rendered.getsampwidth())
                self.assertEqual(44100, rendered.getframerate())
                self.assertEqual(1764, rendered.getnframes())

    def test_recipe_rejects_windows_escapes_and_casefold_collisions(self) -> None:
        unsafe_paths = [
            r"..\escape.wav",
            r"C:\escape.wav",
            r"\\server\share\escape.wav",
            "audio/../escape.wav",
            "audio//escape.wav",
            "audio/CON.wav",
            "derivative-manifest.json",
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, unsafe_path in enumerate(unsafe_paths):
                recipe = _fixture_recipe()
                recipe["outputs"][0]["output_path"] = unsafe_path
                recipe_path = root / f"unsafe-{index}.json"
                recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
                with self.subTest(path=unsafe_path):
                    with self.assertRaises(DerivativeError):
                        load_derivative_recipe(recipe_path)

            collision = _fixture_recipe()
            duplicate = copy.deepcopy(collision["outputs"][0])
            duplicate["asset_id"] = "fixture:paper-switch:02"
            duplicate["variant"] = 2
            duplicate["output_path"] = "audio/EVIDENCE_SWITCH_01.wav"
            collision["outputs"].append(duplicate)
            collision_path = root / "collision.json"
            collision_path.write_text(json.dumps(collision), encoding="utf-8")
            with self.assertRaises(DerivativeError):
                load_derivative_recipe(collision_path)

    def test_public_derivative_pipeline_stages_and_rehashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe, fake_miniaudio, authoring_root, output_root = (
                _public_pipeline_fixture(root)
            )
            with (
                mock.patch.object(derivative_module, "REPOSITORY_ROOT", root),
                mock.patch.object(
                    derivative_module, "AUTHORING_OUTPUT_ROOT", authoring_root
                ),
                mock.patch.dict(sys.modules, {"miniaudio": fake_miniaudio}),
            ):
                manifest = derivative_module.derive_recordings(recipe, output_root)
                first_manifest_bytes = (output_root / "derivative-manifest.json").read_bytes()
                first_wav_bytes = (output_root / "audio" / "evidence_switch_01.wav").read_bytes()
                self.assertEqual(recipe["outputs"][0]["output_sha256"], manifest["assets"][0]["sha256"])

                derivative_module.derive_recordings(
                    recipe, output_root, allow_overwrite=True
                )
                self.assertEqual(
                    first_manifest_bytes,
                    (output_root / "derivative-manifest.json").read_bytes(),
                )
                self.assertEqual(
                    first_wav_bytes,
                    (output_root / "audio" / "evidence_switch_01.wav").read_bytes(),
                )

                bad_recipe = copy.deepcopy(recipe)
                bad_recipe["recipe_id"] = "fixture.bad-output.cc0"
                bad_recipe["outputs"][0]["output_sha256"] = "0" * 64
                bad_output = authoring_root / "bad-output"
                with self.assertRaises(DerivativeError):
                    derivative_module.derive_recordings(bad_recipe, bad_output)
                self.assertFalse(bad_output.exists())

    def test_final_verify_permission_error_restores_previous_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe, fake_miniaudio, authoring_root, output_root = (
                _public_pipeline_fixture(root)
            )
            with (
                mock.patch.object(derivative_module, "REPOSITORY_ROOT", root),
                mock.patch.object(
                    derivative_module, "AUTHORING_OUTPUT_ROOT", authoring_root
                ),
                mock.patch.dict(sys.modules, {"miniaudio": fake_miniaudio}),
            ):
                derivative_module.derive_recordings(recipe, output_root)
                old_manifest = (output_root / "derivative-manifest.json").read_bytes()
                old_wav = (
                    output_root / "audio" / "evidence_switch_01.wav"
                ).read_bytes()
                review_marker = output_root / "review-marker.txt"
                review_marker.write_text("preserve old pack", encoding="utf-8")

                real_verify = derivative_module._verify_output_pack
                verify_calls = 0

                def fail_final_verify(*args, **kwargs) -> None:
                    nonlocal verify_calls
                    verify_calls += 1
                    if verify_calls == 2:
                        raise PermissionError("synthetic final verification failure")
                    real_verify(*args, **kwargs)

                with mock.patch.object(
                    derivative_module,
                    "_verify_output_pack",
                    side_effect=fail_final_verify,
                ):
                    with self.assertRaisesRegex(
                        DerivativeError, "previous pack was restored"
                    ):
                        derivative_module.derive_recordings(
                            recipe, output_root, allow_overwrite=True
                        )

                self.assertEqual(2, verify_calls)
                self.assertEqual(
                    "preserve old pack", review_marker.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    old_manifest,
                    (output_root / "derivative-manifest.json").read_bytes(),
                )
                self.assertEqual(
                    old_wav,
                    (output_root / "audio" / "evidence_switch_01.wav").read_bytes(),
                )
                self.assertEqual(
                    [],
                    list(authoring_root.glob(f".{output_root.name}.staging-*")),
                )
                self.assertEqual(
                    [],
                    list(authoring_root.glob(f".{output_root.name}.previous-*")),
                )


if __name__ == "__main__":
    unittest.main()
