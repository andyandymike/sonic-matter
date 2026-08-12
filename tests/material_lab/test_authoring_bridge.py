from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.material_lab.errors import ManifestError
from tools.material_lab.godot_compiler import (
    compile_godot_kit,
    _publish_no_replace,
    validate_godot_compile_plan,
)
from tools.material_lab.proposal import validate_proposal
from tools.material_lab.rights import publication_rights

from tests.material_lab.build_godot_compiler_fixture import (
    _write_pcm16_wav,
    build_compiler_inputs,
)


FROZEN_OUTPUT_INVENTORY_SHA256 = (
    "f3b5d492596b39ede86b4b93be1826caa9c7e0509e8f24adb85a0daa81021b9f"
)
FROZEN_COMPILED_MANIFEST_SHA256 = (
    "a4d3b22201636745eb025179ced7a61f894999423b34c1f8924e357c3ef47d89"
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file())
    }


def _replace_fixture_audio(
    root: Path,
    kit_path: Path,
    plan_path: Path,
    payload: bytes,
) -> None:
    audio_path = root / "kit" / "audio" / "impact.wav"
    rights_path = root / "kit" / "rights" / "asset-rights.json"
    audio_path.write_bytes(payload)

    rights = json.loads(rights_path.read_text(encoding="utf-8"))
    rights["assets"][0]["sha256"] = _sha256(audio_path)
    _write_json(rights_path, rights)

    kit = json.loads(kit_path.read_text(encoding="utf-8"))
    for record in kit["files"]:
        if record["path"] == "audio/impact.wav":
            record["sha256"] = _sha256(audio_path)
            record["bytes"] = audio_path.stat().st_size
        elif record["path"] == "rights/asset-rights.json":
            record["sha256"] = _sha256(rights_path)
            record["bytes"] = rights_path.stat().st_size
    _write_json(kit_path, kit)

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["kit"]["manifest_sha256"] = _sha256(kit_path)
    _write_json(plan_path, plan)


def _wave_extensible_pcm16() -> bytes:
    channels = 1
    sample_rate = 8_000
    bits_per_sample = 16
    block_align = channels * bits_per_sample // 8
    pcm_subformat_guid = (
        (1).to_bytes(4, "little")
        + (0).to_bytes(2, "little")
        + (0x10).to_bytes(2, "little")
        + bytes.fromhex("800000aa00389b71")
    )
    fmt = (
        (0xFFFE).to_bytes(2, "little")
        + channels.to_bytes(2, "little")
        + sample_rate.to_bytes(4, "little")
        + (sample_rate * block_align).to_bytes(4, "little")
        + block_align.to_bytes(2, "little")
        + bits_per_sample.to_bytes(2, "little")
        + (22).to_bytes(2, "little")
        + bits_per_sample.to_bytes(2, "little")
        + (0x4).to_bytes(4, "little")
        + pcm_subformat_guid
    )
    data = b"\x00\x00"
    riff_size = 4 + 8 + len(fmt) + 8 + len(data)
    return (
        b"RIFF"
        + riff_size.to_bytes(4, "little")
        + b"WAVEfmt "
        + len(fmt).to_bytes(4, "little")
        + fmt
        + b"data"
        + len(data).to_bytes(4, "little")
        + data
    )


def _build_base_recipe(root: Path) -> Path:
    audio_path = root / "audio" / "proposal-base.wav"
    _write_pcm16_wav(audio_path)
    audio_record = {
        "path": "audio/proposal-base.wav",
        "sha256": _sha256(audio_path),
    }
    recipe_path = root / "recipe.json"
    _write_json(
        recipe_path,
        {
            "schema": "sonic-impact-recipe/v1",
            "status": "experimental",
            "event": "impact",
            "source_material": "wood",
            "target_material": "stone",
            "sample_rate": 24_000,
            "algorithm": {
                "id": "test/manual-fixture/v1",
                "analysis_backend": "none",
                "deterministic": True,
            },
            "rights": publication_rights(
                review_state="unreviewed-local-only",
                parent_publication_eligible=False,
            ),
            "sample_pool": [audio_record],
            "transients": [audio_record],
            "modal_body": {
                "mode_count": 6,
                "modes": [
                    {"frequency_hz": 220.0 + 110.0 * index, "t60_ms": 120.0, "gain": 0.1}
                    for index in range(6)
                ],
                "excitation_pulse": [1.0, -0.45],
            },
            "roughness": {
                "band_count": 2,
                "bands": [
                    {
                        "center_hz": 900.0 + 900.0 * index,
                        "q": 1.0,
                        "envelope": [
                            {"time_ms": 0.0, "level_db": -12.0},
                            {"time_ms": 20.0, "level_db": -48.0},
                        ],
                    }
                    for index in range(2)
                ],
            },
            "mix": {
                "transient_gain_db": 0.0,
                "body_gain_db": 0.0,
                "roughness_gain_db": -3.0,
                "master_gain_db": -9.0,
            },
            "safety": {"peak_limit": 0.98},
            "render": {"duration_ms": 20.0, "variant_count": 1, "pcm": "mono-signed-24-bit"},
        },
    )
    return recipe_path


def _proposal(base_path: Path) -> dict[str, object]:
    return {
        "schema": "sonic-authoring-proposal/v1",
        "status": "draft",
        "profile": "material-lab-impact-mix/v1",
        "proposal_id": "test.mix.balance",
        "base": {
            "artifact_schema": "sonic-impact-recipe/v1",
            "sha256": _sha256(base_path),
        },
        "summary": "Reduce the roughness layer in a human-reviewed draft.",
        "changes": [
            {
                "kind": "set_layer_gain_db",
                "layer": "roughness",
                "from_db": -3.0,
                "to_db": -6.0,
                "reason": "Keep the test proposal inside the mix-only boundary.",
            }
        ],
    }


class GodotCompilerTests(unittest.TestCase):
    def test_compile_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kit_path, plan_path = build_compiler_inputs(root / "inputs")
            first = root / "first"
            second = root / "second"
            first_report = compile_godot_kit(
                kit_path,
                plan_path,
                first,
                rights_targets=("local-preview", "game-source"),
            )
            second_report = compile_godot_kit(
                kit_path,
                plan_path,
                second,
                rights_targets=("game-source", "local-preview"),
            )
            self.assertEqual(_tree_bytes(first), _tree_bytes(second))
            self.assertEqual(first_report.manifest_sha256, second_report.manifest_sha256)
            manifest = json.loads(first_report.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                first_report.output_inventory_sha256,
                FROZEN_OUTPUT_INVENTORY_SHA256,
            )
            self.assertEqual(first_report.manifest_sha256, FROZEN_COMPILED_MANIFEST_SHA256)
            self.assertEqual(manifest["source"]["rights_targets"], ["game-source", "local-preview"])
            self.assertEqual(manifest["coverage"][0]["resolution"], "target_family")

    def test_compile_rights_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            kit_path, plan_path = build_compiler_inputs(
                Path(temporary),
                rights_overrides={"game_source_distribution": "unknown"},
            )
            with self.assertRaisesRegex(ManifestError, "not publishable for game-source"):
                validate_godot_compile_plan(
                    kit_path,
                    plan_path,
                    rights_targets=("game-source",),
                )

    def test_stale_kit_lock_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            kit_path, plan_path = build_compiler_inputs(Path(temporary))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["kit"]["manifest_sha256"] = "0" * 64
            _write_json(plan_path, plan)
            with self.assertRaisesRegex(ManifestError, "compile plan is stale"):
                validate_godot_compile_plan(
                    kit_path,
                    plan_path,
                    rights_targets=("local-preview",),
                )

    def test_existing_output_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kit_path, plan_path = build_compiler_inputs(root / "inputs")
            output = root / "compiled"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep\n", encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "overwrite is forbidden"):
                compile_godot_kit(
                    kit_path,
                    plan_path,
                    output,
                    rights_targets=("local-preview",),
                )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")
            self.assertEqual([marker], list(output.iterdir()))


    def test_atomic_publication_never_replaces_a_racing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / "stage"
            output = root / "output"
            stage.mkdir()
            (stage / "compiled.txt").write_text("new\n", encoding="utf-8")
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("keep\n", encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "overwrite is forbidden"):
                _publish_no_replace(stage, output)
            self.assertTrue(stage.is_dir())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep\n")

    def test_reserved_material_id_fails_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            kit_path, plan_path = build_compiler_inputs(Path(temporary))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["materials"][0]["material_id"] = "con"
            _write_json(plan_path, plan)
            with self.assertRaisesRegex(ManifestError, "reserved Windows path"):
                validate_godot_compile_plan(
                    kit_path,
                    plan_path,
                    rights_targets=("local-preview",),
                )

    def test_malformed_wav_never_compiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kit_path, plan_path = build_compiler_inputs(root)
            audio_path = root / "kit" / "audio" / "impact.wav"
            rights_path = root / "kit" / "rights" / "asset-rights.json"
            audio_path.write_bytes(b"not-a-wave")

            rights = json.loads(rights_path.read_text(encoding="utf-8"))
            rights["assets"][0]["sha256"] = _sha256(audio_path)
            _write_json(rights_path, rights)

            kit = json.loads(kit_path.read_text(encoding="utf-8"))
            for record in kit["files"]:
                if record["path"] == "audio/impact.wav":
                    record["sha256"] = _sha256(audio_path)
                    record["bytes"] = audio_path.stat().st_size
                elif record["path"] == "rights/asset-rights.json":
                    record["sha256"] = _sha256(rights_path)
                    record["bytes"] = rights_path.stat().st_size
            _write_json(kit_path, kit)

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["kit"]["manifest_sha256"] = _sha256(kit_path)
            _write_json(plan_path, plan)

            with self.assertRaisesRegex(ManifestError, "RIFF/WAVE"):
                validate_godot_compile_plan(
                    kit_path,
                    plan_path,
                    rights_targets=("local-preview",),
                )

    def test_wave_extensible_pcm_never_compiles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kit_path, plan_path = build_compiler_inputs(root)
            _replace_fixture_audio(
                root,
                kit_path,
                plan_path,
                _wave_extensible_pcm16(),
            )
            output = root / "compiled"
            with self.assertRaisesRegex(ManifestError, "format tag must be PCM 1"):
                compile_godot_kit(
                    kit_path,
                    plan_path,
                    output,
                    rights_targets=("local-preview",),
                )
            self.assertFalse(output.exists())


class ProposalValidatorTests(unittest.TestCase):
    def test_mix_only_proposal_returns_non_authorizing_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base_path = _build_base_recipe(root)
            proposal_path = root / "proposal.json"
            _write_json(proposal_path, _proposal(base_path))
            receipt = validate_proposal(proposal_path, base_path)
            self.assertEqual(receipt["result"], "valid_draft")
            self.assertEqual(receipt["changed_layers"], ["roughness"])
            self.assertTrue(receipt["protected_fields_unchanged"])
            self.assertFalse(receipt["applied"])
            self.assertEqual(receipt["authorization"], "none")
            self.assertFalse(receipt["render_safety_evaluated"])

    def test_proposal_cannot_gain_rights_or_asset_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base_path = _build_base_recipe(root)
            baseline = _proposal(base_path)
            cases = {}
            rights = copy.deepcopy(baseline)
            rights["rights"] = {"publication_eligible": True}
            cases["rights"] = rights
            output = copy.deepcopy(baseline)
            output["output_path"] = "res://addons/sonic_matter/owned.tres"
            cases["output"] = output
            asset = copy.deepcopy(baseline)
            asset["changes"][0]["kind"] = "select_asset"
            cases["asset"] = asset
            for label, proposal in cases.items():
                with self.subTest(label=label):
                    proposal_path = root / f"proposal-{label}.json"
                    _write_json(proposal_path, proposal)
                    with self.assertRaises(ManifestError):
                        validate_proposal(proposal_path, base_path)

    def test_adversarial_json_and_numbers_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base_path = _build_base_recipe(root)
            baseline = _proposal(base_path)

            huge = copy.deepcopy(baseline)
            huge["changes"][0]["to_db"] = 10**4000
            huge_path = root / "proposal-huge.json"
            _write_json(huge_path, huge)
            with self.assertRaisesRegex(ManifestError, "binary64"):
                validate_proposal(huge_path, base_path)

            duplicate_path = root / "proposal-duplicate.json"
            duplicate_path.write_text(
                '{"schema":"sonic-authoring-proposal/v1","schema":"duplicate"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ManifestError, "duplicate JSON key"):
                validate_proposal(duplicate_path, base_path)

            deep_path = root / "proposal-deep.json"
            deep_path.write_text(
                '{"wrapper":' * 1500 + "null" + "}" * 1500,
                encoding="utf-8",
            )
            with self.assertRaises(ManifestError):

                validate_proposal(deep_path, base_path)
    def test_proposal_rejects_stale_bounds_nonfinite_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base_path = _build_base_recipe(root)
            baseline = _proposal(base_path)

            cases = {}
            stale = copy.deepcopy(baseline)
            stale["base"]["sha256"] = "0" * 64
            cases["stale"] = stale
            out_of_range = copy.deepcopy(baseline)
            out_of_range["changes"][0]["to_db"] = 13.0
            cases["out-of-range"] = out_of_range
            nonfinite = copy.deepcopy(baseline)
            nonfinite["changes"][0]["to_db"] = float("nan")
            cases["nonfinite"] = nonfinite
            for label, proposal in cases.items():
                with self.subTest(label=label):
                    proposal_path = root / f"proposal-{label}.json"
                    _write_json(proposal_path, proposal)
                    with self.assertRaises(ManifestError):
                        validate_proposal(proposal_path, base_path)

            proposal_path = root / "proposal-symlink.json"
            _write_json(proposal_path, baseline)
            with mock.patch.object(Path, "is_symlink", return_value=True):
                with self.assertRaisesRegex(ManifestError, "non-symlink"):
                    validate_proposal(proposal_path, base_path)

    def test_bridge_runs_with_network_and_model_imports_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kit_path, plan_path = build_compiler_inputs(root / "compiler")
            base_path = _build_base_recipe(root / "proposal")
            proposal_path = root / "proposal" / "proposal.json"
            _write_json(proposal_path, _proposal(base_path))
            unavailable_models = {
                "torch": None,
                "transformers": None,
                "tensorflow": None,
                "onnxruntime": None,
            }
            with mock.patch(
                "socket.socket",
                side_effect=AssertionError("network access is forbidden"),
            ), mock.patch.dict("sys.modules", unavailable_models):
                report = compile_godot_kit(
                    kit_path,
                    plan_path,
                    root / "compiled",
                    rights_targets=("local-preview",),
                )
                receipt = validate_proposal(proposal_path, base_path)
            self.assertTrue(report.manifest_path.is_file())
            self.assertEqual(receipt["authorization"], "none")


if __name__ == "__main__":
    unittest.main()
