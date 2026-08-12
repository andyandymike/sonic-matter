from __future__ import annotations

import json
import math
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from tools.material_lab.analysis import AnalysisOptions, analyze_impacts
from tools.material_lab.errors import AudioFormatError, ManifestError
from tools.material_lab.intake import inventory_zip
from tools.material_lab.io import (
    load_json,
    read_wav_mono,
    sha256_file,
    write_stable_json,
    write_wav_pcm24,
)
from tools.material_lab.kit import validate_kit
from tools.material_lab.render import ARM_NAMES, RenderOptions, render_recipe
from tools.material_lab.rights import RIGHTS_ACTIONS, validate_rights


SAMPLE_RATE = 24_000


def _synthetic_impact(variant: int) -> np.ndarray:
    onset = 96
    tail_frames = int(SAMPLE_RATE * 0.45)
    time = np.arange(tail_frames, dtype=np.float64) / SAMPLE_RATE
    frequencies = (280.0, 430.0, 680.0, 1080.0, 1680.0, 2550.0, 3900.0, 6100.0)
    signal = np.zeros(onset + tail_frames, dtype=np.float64)
    signal[onset] = 0.55 - 0.02 * variant
    body = np.zeros(tail_frames, dtype=np.float64)
    for index, frequency in enumerate(frequencies):
        t60 = 0.12 + index * 0.025
        amplitude = (0.065 / (1.0 + index * 0.35)) * (1.0 + 0.025 * variant)
        body += amplitude * np.sin(2.0 * math.pi * frequency * time) * np.exp(
            math.log(0.001) * time / t60
        )
    rng = np.random.default_rng(10_000 + variant)
    body += rng.normal(0.0, 0.004, tail_frames) * np.exp(-time / 0.035)
    signal[onset:] += body
    return signal


def _decision(status: str = "allow") -> dict[str, object]:
    return {
        "status": status,
        "evidence_ids": ["grant"] if status in {"allow", "deny"} else [],
        "conditions": [],
    }


def _rights_manifest(
    root: Path, audio_path: Path, *, overrides: dict[str, str] | None = None
) -> Path:
    evidence_path = root / "rights" / "evidence" / "cc0-legal-code.txt"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text("Test fixture grant: CC0-1.0\n", encoding="utf-8")
    actions = {action: _decision() for action in RIGHTS_ACTIONS}
    for action, status in (overrides or {}).items():
        actions[action] = _decision(status)
    manifest = {
        "schema": "sonic-material-rights/v1",
        "pack_id": "test.material.kit",
        "assets": [
            {
                "asset_id": "test:impact:one",
                "file": audio_path.relative_to(root).as_posix(),
                "sha256": sha256_file(audio_path),
                "intake_tier": "cc0",
                "license": {
                    "spdx": "CC0-1.0",
                    "name": "CC0 1.0 Universal",
                    "canonical_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                },
                "evidence": [
                    {
                        "evidence_id": "grant",
                        "kind": "retained-license-text",
                        "path": evidence_path.relative_to(root).as_posix(),
                        "sha256": sha256_file(evidence_path),
                        "canonical_url": "https://creativecommons.org/publicdomain/zero/1.0/legalcode",
                        "captured_at": "2026-08-11",
                    }
                ],
                "parent_asset_ids": [],
                "actions": actions,
            }
        ],
    }
    path = root / "rights" / "asset-rights.json"
    write_stable_json(path, manifest)
    return path


class Pcm24Tests(unittest.TestCase):
    def test_pcm24_round_trip_and_clipping_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "roundtrip.wav"
            original = np.linspace(-0.9, 0.9, 1024, dtype=np.float64)
            write_wav_pcm24(path, SAMPLE_RATE, original)
            rate, decoded = read_wav_mono(path)
            self.assertEqual(rate, SAMPLE_RATE)
            self.assertLess(float(np.max(np.abs(decoded - original))), 2.0 / (1 << 23))
            with self.assertRaises(AudioFormatError):
                write_wav_pcm24(Path(temporary) / "clip.wav", SAMPLE_RATE, np.array([1.01]))


class AnalysisRenderTests(unittest.TestCase):
    def test_analysis_is_deterministic_and_six_arms_are_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = []
            for variant in range(3):
                path = root / f"impact-{variant}.wav"
                write_wav_pcm24(path, SAMPLE_RATE, _synthetic_impact(variant))
                inputs.append(path)
            options = AnalysisOptions(
                transient_ms=18.0,
                mode_count=8,
                roughness_band_count=4,
                max_seconds=0.45,
                source_material="wood",
                target_material="stone",
            )
            first = analyze_impacts(inputs, root / "analysis-a", options=options)
            second = analyze_impacts(inputs, root / "analysis-b", options=options)
            self.assertEqual(first["recipe_sha256"], second["recipe_sha256"])
            recipe = load_json(first["recipe"])
            self.assertEqual(recipe["modal_body"]["mode_count"], 8)
            self.assertEqual(recipe["roughness"]["band_count"], 4)
            self.assertFalse(recipe["rights"]["publication_eligible"])
            self.assertEqual(
                recipe["rights"]["project_output_audio_grant"]["decision_id"],
                "D-015",
            )
            self.assertEqual(
                recipe["rights"]["project_output_audio_grant"]["status"],
                "unknown",
            )
            self.assertEqual(
                {mode["role"] for mode in recipe["modal_body"]["modes"]}, {"pair-body"}
            )

            render_a = render_recipe(
                first["recipe"], root / "render-a", options=RenderOptions(seed=42)
            )
            render_b = render_recipe(
                first["recipe"], root / "render-b", options=RenderOptions(seed=42)
            )
            self.assertEqual(len(render_a["rendered"]), len(ARM_NAMES))
            hashes_a = [sha256_file(path) for path in render_a["rendered"]]
            hashes_b = [sha256_file(path) for path in render_b["rendered"]]
            self.assertEqual(hashes_a, hashes_b)
            render_c = render_recipe(
                first["recipe"],
                root / "render-c",
                options=RenderOptions(seed=43, arms=("hybrid_full",)),
            )
            full_a = root / "render-a" / "hybrid_full.wav"
            self.assertNotEqual(sha256_file(full_a), sha256_file(render_c["rendered"][0]))
            manifest = load_json(render_a["manifest"])
            self.assertFalse(manifest["safety"]["limiter_applied"])
            self.assertFalse(manifest["rights"]["publication_eligible"])
            self.assertIn(
                "project_output_audio_grant_unknown",
                manifest["rights"]["publication_blockers"],
            )
            self.assertTrue(all(item["peak"] <= 0.98 for item in manifest["rendered"]))

            silent = render_recipe(
                first["recipe"],
                root / "render-silent",
                options=RenderOptions(intensity=0.0, arms=("hybrid_full",)),
            )
            _, silent_signal = read_wav_mono(silent["rendered"][0])
            self.assertEqual(float(np.max(np.abs(silent_signal))), 0.0)

            unsafe_recipe = load_json(first["recipe"])
            unsafe_recipe["mix"]["master_gain_db"] = 12.0
            unsafe_recipe_path = first["recipe"].parent / "unsafe-recipe.json"
            write_stable_json(unsafe_recipe_path, unsafe_recipe)
            failed_output = root / "render-over-peak"
            with self.assertRaises(AudioFormatError):
                render_recipe(
                    unsafe_recipe_path,
                    failed_output,
                    options=RenderOptions(arms=("sample_pool",)),
                )
            self.assertFalse(failed_output.exists())

    def test_parent_rights_cannot_bypass_open_output_audio_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio_path = root / "audio" / "impact.wav"
            write_wav_pcm24(audio_path, SAMPLE_RATE, _synthetic_impact(0))
            rights_path = _rights_manifest(root, audio_path)
            result = analyze_impacts(
                [audio_path],
                root / "analysis",
                rights_manifest=rights_path,
                rights_root=root,
            )
            recipe = load_json(result["recipe"])
            self.assertTrue(recipe["rights"]["parent_publication_eligible"])
            self.assertFalse(recipe["rights"]["publication_eligible"])
            self.assertEqual(
                ["project_output_audio_grant_unknown"],
                recipe["rights"]["publication_blockers"],
            )

            rendered = render_recipe(result["recipe"], root / "render")
            render_manifest = load_json(rendered["manifest"])
            self.assertFalse(render_manifest["rights"]["publication_eligible"])
            self.assertEqual(
                "D-015",
                render_manifest["rights"]["project_output_audio_grant"]["decision_id"],
            )

            recipe["rights"]["publication_eligible"] = True
            tampered_recipe = result["recipe"].parent / "tampered-rights-recipe.json"
            write_stable_json(tampered_recipe, recipe)
            rejected_output = root / "tampered-render"
            with self.assertRaises(ManifestError):
                render_recipe(tampered_recipe, rejected_output)
            self.assertFalse(rejected_output.exists())


class RightsAndKitTests(unittest.TestCase):
    def test_unknown_public_right_fails_closed_but_local_preview_remains_possible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio_path = root / "audio" / "impact.wav"
            write_wav_pcm24(audio_path, SAMPLE_RATE, _synthetic_impact(0))
            manifest = _rights_manifest(
                root,
                audio_path,
                overrides={"standalone_baked_audio_distribution": "unknown"},
            )
            validate_rights(manifest, root=root, target="local-preview")
            with self.assertRaises(ManifestError):
                validate_rights(manifest, root=root, target="public-bake")

    def test_exact_official_cc0_kit_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio_path = root / "audio" / "impact.wav"
            write_wav_pcm24(audio_path, SAMPLE_RATE, _synthetic_impact(0))
            rights_path = _rights_manifest(root, audio_path)
            recipe_path = root / "recipes" / "wood-stone.json"
            write_stable_json(recipe_path, {"fixture": True})
            files = []
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    files.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "sha256": sha256_file(path),
                            "bytes": path.stat().st_size,
                        }
                    )
            kit_path = root / "kit.json"
            write_stable_json(
                kit_path,
                {
                    "schema": "sonic-material-kit/v1",
                    "kit_id": "sonicmatter.test.cc0",
                    "version": "0.1.0-experimental",
                    "status": "experimental",
                    "rights_manifest": rights_path.relative_to(root).as_posix(),
                    "files": files,
                    "coverage": [
                        {
                            "event": "impact",
                            "source": "wood",
                            "target": "stone",
                            "state": "fallback",
                        },
                        {
                            "event": "impact",
                            "source": "metal",
                            "target": "stone",
                            "state": "unsupported",
                        },
                    ],
                },
            )
            report = validate_kit(kit_path, profile="official-cc0")
            self.assertEqual(report.file_count, len(files))
            audio_path.write_bytes(audio_path.read_bytes() + b"tamper")
            with self.assertRaises(ManifestError):
                validate_kit(kit_path, profile="official-cc0")

    def test_verified_recipe_fails_closed_while_d015_is_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio_path = root / "audio" / "impact.wav"
            write_wav_pcm24(audio_path, SAMPLE_RATE, _synthetic_impact(0))
            rights_path = _rights_manifest(root, audio_path)
            recipe_path = root / "recipes" / "wood-stone.json"
            write_stable_json(
                recipe_path,
                {
                    "schema": "sonic-impact-recipe/v1",
                    "rights": {
                        "review_state": "validated",
                        "parent_publication_eligible": True,
                        "project_output_audio_grant": {
                            "decision_id": "D-015",
                            "status": "unknown",
                            "license_spdx": None,
                            "evidence_ids": [],
                        },
                        "publication_eligible": False,
                        "publication_blockers": [
                            "project_output_audio_grant_unknown"
                        ],
                    },
                },
            )
            files = []
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    files.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "sha256": sha256_file(path),
                            "bytes": path.stat().st_size,
                        }
                    )
            kit_path = root / "kit.json"
            write_stable_json(
                kit_path,
                {
                    "schema": "sonic-material-kit/v1",
                    "kit_id": "sonicmatter.test.blocked",
                    "version": "0.1.0-experimental",
                    "status": "experimental",
                    "rights_manifest": rights_path.relative_to(root).as_posix(),
                    "files": files,
                    "coverage": [
                        {
                            "event": "impact",
                            "source": "wood",
                            "target": "stone",
                            "state": "verified",
                            "recipe": recipe_path.relative_to(root).as_posix(),
                        }
                    ],
                },
            )
            for rights_target in (
                "source-repo",
                "material-kit",
                "game-source",
                "game-binary",
                "public-bake",
            ):
                with self.subTest(rights_target=rights_target):
                    with self.assertRaisesRegex(
                        ManifestError,
                        "not publication-eligible",
                    ):
                        validate_kit(
                            kit_path,
                            profile="official-cc0",
                            rights_target=rights_target,
                        )
            validate_kit(
                kit_path,
                profile="official-cc0",
                rights_target="local-preview",
            )

    def test_unregistered_audio_cannot_enter_a_kit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registered = root / "audio" / "registered.wav"
            unregistered = root / "audio" / "generated.wav"
            write_wav_pcm24(registered, SAMPLE_RATE, _synthetic_impact(0))
            write_wav_pcm24(unregistered, SAMPLE_RATE, _synthetic_impact(1))
            rights_path = _rights_manifest(root, registered)
            files = []
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    files.append(
                        {
                            "path": path.relative_to(root).as_posix(),
                            "sha256": sha256_file(path),
                            "bytes": path.stat().st_size,
                        }
                    )
            kit_path = root / "kit.json"
            write_stable_json(
                kit_path,
                {
                    "schema": "sonic-material-kit/v1",
                    "kit_id": "sonicmatter.test.unregistered",
                    "version": "0.1.0-experimental",
                    "status": "experimental",
                    "rights_manifest": rights_path.relative_to(root).as_posix(),
                    "files": files,
                    "coverage": [
                        {
                            "event": "impact",
                            "source": "wood",
                            "target": "stone",
                            "state": "fallback",
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(
                ManifestError,
                "audio rights coverage is not exact",
            ):
                validate_kit(kit_path, profile="official-cc0")


class QuarantineTests(unittest.TestCase):
    def test_inventory_hashes_members_without_extracting(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "safe.zip"
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("audio/impact.wav", b"fixture")
            report = inventory_zip(
                archive_path,
                source_url="https://example.invalid/exact-item",
                license_claim="CC0-1.0",
                acquired_at="2026-08-11",
                evidence_paths=[archive_path],
                review_notes=["Fixture remains unapproved."],
            )
            self.assertEqual(report["approval_state"], "quarantine")
            self.assertEqual(report["member_count"], 1)
            self.assertEqual(report["default_rights"]["status"], "unknown")
            self.assertEqual(
                report["source"]["retained_evidence"][0]["sha256"], sha256_file(archive_path)
            )
            self.assertEqual(report["source"]["review_notes"], ["Fixture remains unapproved."])

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "unsafe.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.wav", b"not allowed")
            with self.assertRaises(ManifestError):
                inventory_zip(
                    archive_path,
                    source_url="https://example.invalid/item",
                    license_claim="unknown",
                    acquired_at="2026-08-11",
                )


if __name__ == "__main__":
    unittest.main()
