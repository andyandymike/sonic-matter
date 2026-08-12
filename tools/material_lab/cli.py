from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .analysis import AnalysisOptions, analyze_impacts
from .errors import MaterialLabError
from .intake import inventory_zip
from .io import write_stable_json
from .kit import validate_kit
from .render import ARM_NAMES, RenderOptions, render_recipe
from .rights import TARGET_ACTIONS, validate_rights


def _paths(values: list[str] | None) -> list[Path]:
    return [Path(value) for value in values or []]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.material_lab",
        description="Offline, no-training material analysis and rights-gated baking for SonicMatter.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    rights = subparsers.add_parser("validate-rights", help="validate a rights manifest")
    rights.add_argument("manifest", type=Path)
    rights.add_argument("--root", type=Path)
    rights.add_argument("--target", choices=sorted(TARGET_ACTIONS))

    kit = subparsers.add_parser("validate-kit", help="validate an exact Material Kit inventory")
    kit.add_argument("manifest", type=Path)
    kit.add_argument("--profile", choices=("community", "official-cc0"), default="community")
    kit.add_argument("--rights-target", choices=sorted(TARGET_ACTIONS), default="material-kit")

    inventory = subparsers.add_parser(
        "inventory-archive", help="safely inventory a quarantine ZIP without extracting it"
    )
    inventory.add_argument("archive", type=Path)
    inventory.add_argument("--output", type=Path, required=True)
    inventory.add_argument("--source-url", required=True)
    inventory.add_argument("--license-claim", required=True)
    inventory.add_argument("--acquired-at", required=True, help="UTC timestamp or ISO date")
    inventory.add_argument(
        "--evidence",
        type=Path,
        action="append",
        help="retained exact page, API response, license text, or written grant",
    )
    inventory.add_argument(
        "--review-note",
        action="append",
        help="human provenance or licensing observation retained with the quarantine record",
    )

    analyze = subparsers.add_parser("analyze", help="analyze 1-3 impact WAVs into a recipe")
    analyze.add_argument("--input", nargs="+", required=True)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--source-tap", action="append")
    analyze.add_argument("--target-tap", action="append")
    analyze.add_argument("--rights-manifest", type=Path)
    analyze.add_argument(
        "--rights-root",
        type=Path,
        help="root used by paths inside the rights manifest (defaults to manifest directory)",
    )
    analyze.add_argument("--source-material", default="unknown-source")
    analyze.add_argument("--target-material", default="unknown-target")
    analyze.add_argument("--transient-ms", type=float, default=20.0)
    analyze.add_argument("--mode-count", type=int, default=8)
    analyze.add_argument("--roughness-bands", type=int, default=4)
    analyze.add_argument("--max-seconds", type=float, default=2.0)

    render = subparsers.add_parser("render", help="render one or all six B0 comparison arms")
    render.add_argument("recipe", type=Path)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--seed", type=int, default=1)
    render.add_argument("--variant", type=int, default=0)
    render.add_argument("--intensity", type=float, default=0.7)
    render.add_argument("--size", type=float, default=1.0)
    render.add_argument("--damping", type=float, default=0.0)
    render.add_argument("--arms", nargs="+", choices=ARM_NAMES, default=list(ARM_NAMES))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-rights":
            report = validate_rights(args.manifest, root=args.root, target=args.target)
            print("MATERIAL_RIGHTS_OK " + json.dumps(report.as_dict(), sort_keys=True))
            return 0
        if args.command == "validate-kit":
            report = validate_kit(
                args.manifest, profile=args.profile, rights_target=args.rights_target
            )
            print("MATERIAL_KIT_OK " + json.dumps(report.as_dict(), sort_keys=True))
            return 0
        if args.command == "inventory-archive":
            inventory = inventory_zip(
                args.archive,
                source_url=args.source_url,
                license_claim=args.license_claim,
                acquired_at=args.acquired_at,
                evidence_paths=args.evidence,
                review_notes=args.review_note,
            )
            write_stable_json(args.output, inventory)
            print(
                "MATERIAL_QUARANTINE_INVENTORY_OK "
                + json.dumps(
                    {
                        "output": str(args.output),
                        "members": inventory["member_count"],
                        "expanded_bytes": inventory["expanded_bytes"],
                        "approval_state": inventory["approval_state"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "analyze":
            result = analyze_impacts(
                _paths(args.input),
                args.output,
                options=AnalysisOptions(
                    transient_ms=args.transient_ms,
                    mode_count=args.mode_count,
                    roughness_band_count=args.roughness_bands,
                    max_seconds=args.max_seconds,
                    source_material=args.source_material,
                    target_material=args.target_material,
                ),
                source_taps=_paths(args.source_tap),
                target_taps=_paths(args.target_tap),
                rights_manifest=args.rights_manifest,
                rights_root=args.rights_root,
            )
            print(
                "MATERIAL_ANALYSIS_OK "
                + json.dumps(
                    {
                        "recipe": str(result["recipe"]),
                        "recipe_sha256": result["recipe_sha256"],
                        "mode_count": result["mode_count"],
                        "roughness_band_count": result["roughness_band_count"],
                        "publication_eligible": result["publication_eligible"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "render":
            result = render_recipe(
                args.recipe,
                args.output,
                options=RenderOptions(
                    seed=args.seed,
                    variant=args.variant,
                    intensity=args.intensity,
                    size=args.size,
                    damping=args.damping,
                    arms=tuple(args.arms),
                ),
            )
            print(
                "MATERIAL_RENDER_OK "
                + json.dumps(
                    {
                        "manifest": str(result["manifest"]),
                        "rendered": len(result["rendered"]),
                        "recipe_sha256": result["recipe_sha256"],
                        "publication_eligible": result["publication_eligible"],
                    },
                    sort_keys=True,
                )
            )
            return 0
    except (MaterialLabError, OSError) as error:
        print(f"MATERIAL_LAB_ERROR {error}", file=sys.stderr)
        return 2
    parser.error(f"unhandled command: {args.command}")
    return 2
