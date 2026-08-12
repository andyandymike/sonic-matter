from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import struct
import tempfile
import wave
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
GENERATED_DIR = Path(__file__).resolve().parent / "generated_ci"

RIGHTS_ACTIONS = (
    "local_preview",
    "source_repo_distribution",
    "material_kit_distribution",
    "game_source_distribution",
    "game_binary_embedding",
    "unchanged_redistribution",
    "standalone_baked_audio_distribution",
    "parameter_fitting",
    "evaluation_use",
    "evaluation_stimulus_publication",
    "training",
    "private_embedding",
    "index_redistribution",
)


def _stable_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pcm16_wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = [0, 12000, -9000, 6000, -3500, 1800, -700, 0] + [0] * 56
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24_000)
        handle.writeframes(b"".join(struct.pack("<h", value) for value in samples))


def _decision(status: str) -> dict[str, object]:
    return {
        "status": status,
        "evidence_ids": ["fixture-grant"] if status in {"allow", "deny"} else [],
        "conditions": [],
    }


def build_compiler_inputs(
    root: Path,
    *,
    rights_overrides: Mapping[str, str] | None = None,
) -> tuple[Path, Path]:
    """Create a tiny independently-authored Kit and explicit compile plan."""

    root = Path(root)
    kit_root = root / "kit"
    audio_path = kit_root / "audio" / "impact.wav"
    evidence_path = kit_root / "rights" / "fixture-grant.txt"
    rights_path = kit_root / "rights" / "asset-rights.json"
    kit_path = kit_root / "kit.json"
    plan_path = root / "compile-plan.json"

    _write_pcm16_wav(audio_path)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        "Project-authored test fixture dedicated to CC0-1.0.\n",
        encoding="utf-8",
        newline="\n",
    )

    actions = {action: _decision("allow") for action in RIGHTS_ACTIONS}
    for action, status in (rights_overrides or {}).items():
        if action not in actions:
            raise ValueError(f"unknown fixture rights action: {action}")
        actions[action] = _decision(status)
    _stable_json(
        rights_path,
        {
            "schema": "sonic-material-rights/v1",
            "pack_id": "sonicmatter.test.authoring_bridge",
            "assets": [
                {
                    "asset_id": "test:impact:fixture",
                    "file": "audio/impact.wav",
                    "sha256": _sha256(audio_path),
                    "intake_tier": "cc0",
                    "license": {
                        "spdx": "CC0-1.0",
                        "name": "CC0 1.0 Universal",
                        "canonical_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                    },
                    "evidence": [
                        {
                            "evidence_id": "fixture-grant",
                            "kind": "project-authored-test-grant",
                            "captured_at": "2026-08-12",
                            "path": "rights/fixture-grant.txt",
                            "sha256": _sha256(evidence_path),
                        }
                    ],
                    "parent_asset_ids": [],
                    "actions": actions,
                }
            ],
        },
    )

    files = []
    for path in sorted(candidate for candidate in kit_root.rglob("*") if candidate.is_file()):
        files.append(
            {
                "path": path.relative_to(kit_root).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    _stable_json(
        kit_path,
        {
            "schema": "sonic-material-kit/v1",
            "kit_id": "sonicmatter.test.authoring_bridge",
            "version": "0.1.0-test",
            "status": "experimental",
            "rights_manifest": "rights/asset-rights.json",
            "files": files,
            "coverage": [
                {
                    "event": "impact",
                    "source": "wood_prop",
                    "target": "stone_floor",
                    "state": "fallback",
                }
            ],
        },
    )

    _stable_json(
        plan_path,
        {
            "schema": "sonic-godot-compile-plan/v1",
            "kit": {
                "kit_id": "sonicmatter.test.authoring_bridge",
                "version": "0.1.0-test",
                "manifest_sha256": _sha256(kit_path),
            },
            "runtime": {
                "contract": "sonic-matter/gate-a-impact/v1",
                "sonic_matter_version": "0.1.0-rc1",
                "godot_version": "4.6",
            },
            "materials": [
                {
                    "material_id": "wood_prop",
                    "family_id": "wood",
                    "roles": ["source"],
                },
                {
                    "material_id": "stone_floor",
                    "family_id": "stone",
                    "roles": ["target"],
                },
            ],
            "palettes": [
                {
                    "palette_id": "wood_on_stone",
                    "family_id": "wood",
                    "impact_gain_db": [-20.0, -4.0],
                    "gain_variation_db": 0.75,
                    "pitch_variation": 0.03,
                    "variants": [
                        {
                            "slot": 0,
                            "asset_id": "test:impact:fixture",
                            "weight": 2.5,
                            "gain_db": -1.5,
                            "pitch_scale": 0.96,
                        }
                    ],
                }
            ],
            "routes": {
                "exact": [],
                "target_family": [
                    {
                        "fallback_id": "stone_family_fallback",
                        "family_id": "stone",
                        "palette_id": "wood_on_stone",
                    }
                ],
                "source_family": [],
                "global_default": None,
            },
        },
    )
    return kit_path, plan_path


def build_generated_fixture(output: Path = GENERATED_DIR) -> Path:
    from tools.material_lab.godot_compiler import compile_godot_kit

    output = Path(output)
    if output.resolve(strict=False) != GENERATED_DIR.resolve(strict=False):
        raise ValueError(f"fixture output is fixed to {GENERATED_DIR}")
    if output.is_symlink():
        raise RuntimeError("refusing to replace a symlinked generated fixture")
    if output.exists():
        shutil.rmtree(output)
    with tempfile.TemporaryDirectory(prefix="sonic-matter-compiler-fixture-") as temporary:
        kit_path, plan_path = build_compiler_inputs(Path(temporary))
        compile_godot_kit(
            kit_path,
            plan_path,
            output,
            rights_targets=("local-preview",),
        )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the fixed Godot compiler smoke fixture."
    )
    parser.parse_args()
    output = build_generated_fixture()
    print(f"GODOT_COMPILER_FIXTURE_OK {output.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
