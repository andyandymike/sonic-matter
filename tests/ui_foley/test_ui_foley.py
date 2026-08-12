from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

from tools.ui_foley.bake import BakeError, _domain_rng, bake_recipe, load_recipe


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RECIPE_PATH = (
    REPOSITORY_ROOT / "tools" / "ui_foley" / "recipes" / "page-turn-u0.json"
)


class UiFoleyBakeTests(unittest.TestCase):
    def test_recipe_bakes_six_safe_pcm24_masters(self) -> None:
        recipe = load_recipe(RECIPE_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            manifest = bake_recipe(recipe, output, write_stems=False)

            self.assertEqual(6, manifest["summary"]["master_count"])
            self.assertEqual(0, manifest["summary"]["stem_count"])
            self.assertEqual(0, manifest["summary"]["ablation_count"])
            self.assertEqual([], manifest["rights"]["recorded_parents"])
            self.assertEqual([], manifest["rights"]["external_assets"])
            self.assertEqual("UNDECIDED", manifest["rights"]["output_license"])
            self.assertEqual(
                "D-015",
                manifest["rights"]["output_rights_decision_id"],
            )
            self.assertFalse(manifest["rights"]["publication_eligible"])
            self.assertEqual(
                ["project_output_audio_grant_unknown"],
                manifest["rights"]["publication_blockers"],
            )
            self.assertNotEqual(
                "allow", manifest["rights"]["game_binary_embedding"]
            )
            masters = [
                record
                for record in manifest["outputs"]
                if record["kind"] == "master"
            ]
            self.assertEqual(6, len(masters))
            for record in masters:
                wav_path = output / record["path"]
                self.assertTrue(wav_path.is_file())
                self.assertEqual(0, record["audio"]["clipped_samples"])
                self.assertLess(record["audio"]["linear_true_peak_dbfs"], -0.9)
                self.assertLess(record["audio"]["max_dc_offset"], 1.0e-6)
                with wave.open(str(wav_path), "rb") as wav_file:
                    self.assertEqual(2, wav_file.getnchannels())
                    self.assertEqual(3, wav_file.getsampwidth())
                    self.assertEqual(48000, wav_file.getframerate())
                    expected_frames = (
                        13440
                        if record["profile_id"] == "normal"
                        else 5376
                    )
                    self.assertEqual(expected_frames, wav_file.getnframes())

    def test_every_d015_restricted_action_fails_closed(self) -> None:
        recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
        actions = (
            "source_repo_distribution",
            "material_kit_distribution",
            "game_source_distribution",
            "game_binary_embedding",
            "standalone_baked_audio_distribution",
            "training_or_parameter_fitting",
            "evaluation_use",
            "evaluation_stimulus_publication",
            "private_embeddings",
            "index_redistribution",
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for action in actions:
                with self.subTest(action=action):
                    candidate = json.loads(json.dumps(recipe))
                    candidate["rights"][action] = "allow"
                    path = root / f"{action}.json"
                    path.write_text(json.dumps(candidate), encoding="utf-8")
                    with self.assertRaisesRegex(BakeError, "fail-closed"):
                        load_recipe(path)

    def test_repeated_bakes_are_byte_identical(self) -> None:
        recipe = load_recipe(RECIPE_PATH)
        with (
            tempfile.TemporaryDirectory() as first_temporary,
            tempfile.TemporaryDirectory() as second_temporary,
        ):
            first = bake_recipe(
                recipe, Path(first_temporary), write_stems=False
            )
            second = bake_recipe(
                recipe, Path(second_temporary), write_stems=False
            )
            first_hashes = {
                record["path"]: record["sha256"] for record in first["outputs"]
            }
            second_hashes = {
                record["path"]: record["sha256"] for record in second["outputs"]
            }
            self.assertEqual(first_hashes, second_hashes)
            self.assertEqual(
                (Path(first_temporary) / "manifest.json").read_bytes(),
                (Path(second_temporary) / "manifest.json").read_bytes(),
            )

    def test_named_random_domains_are_stable_and_isolated(self) -> None:
        first = _domain_rng("page-turn-u0", 17, "normal", 1, "layer:friction")
        repeat = _domain_rng("page-turn-u0", 17, "normal", 1, "layer:friction")
        other = _domain_rng(
            "page-turn-u0", 17, "normal", 1, "layer:fiber_grains"
        )
        first_values = [first.random() for _ in range(12)]
        self.assertEqual(first_values, [repeat.random() for _ in range(12)])
        self.assertNotEqual(first_values, [other.random() for _ in range(12)])

    def test_divergent_evidence_requires_explicit_reviewed_overwrite(self) -> None:
        recipe = load_recipe(RECIPE_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            bake_recipe(recipe, output, write_stems=False)
            target = output / "masters" / "page_turn_normal_01.wav"
            original = target.read_bytes()
            target.write_bytes(original[:-1] + bytes([original[-1] ^ 0x01]))

            with self.assertRaises(BakeError):
                bake_recipe(recipe, output, write_stems=False)
            bake_recipe(
                recipe,
                output,
                write_stems=False,
                allow_overwrite=True,
            )
            self.assertEqual(original, target.read_bytes())

    def test_manifest_is_strict_json_with_no_machine_local_path(self) -> None:
        recipe = load_recipe(RECIPE_PATH)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            bake_recipe(recipe, output, write_stems=False)
            manifest_text = (output / "manifest.json").read_text(
                encoding="utf-8"
            )
            parsed = json.loads(manifest_text)
            self.assertEqual(
                "sonic-ui-foley-bake-manifest/v1", parsed["schema"]
            )
            self.assertNotIn(str(output), manifest_text)


if __name__ == "__main__":
    unittest.main()
