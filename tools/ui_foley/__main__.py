from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bake import BakeError, bake_recipe, load_recipe
from .derive_recordings import (
    DerivativeError,
    derive_recordings,
    load_derivative_recipe,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.ui_foley",
        description="Bake deterministic UI Foley masters and recording derivatives.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    bake = subparsers.add_parser("bake", help="Bake one JSON recipe.")
    bake.add_argument("--recipe", type=Path, required=True)
    bake.add_argument("--output", type=Path, required=True)
    bake.add_argument(
        "--no-stems",
        action="store_true",
        help="Write only the six deployable masters and the manifest.",
    )
    bake.add_argument(
        "--overwrite-reviewed",
        action="store_true",
        help="Replace divergent existing evidence after an explicit review.",
    )

    derive = subparsers.add_parser(
        "derive-recordings",
        help="Create bounded PCM16 WAV derivatives from an audited recording pack.",
    )
    derive.add_argument("--recipe", type=Path, required=True)
    derive.add_argument("--output", type=Path, required=True)
    derive.add_argument(
        "--overwrite-reviewed",
        action="store_true",
        help="Replace divergent existing evidence after an explicit review.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        if args.command == "bake":
            recipe = load_recipe(args.recipe)
            manifest = bake_recipe(
                recipe,
                args.output,
                write_stems=not args.no_stems,
                allow_overwrite=args.overwrite_reviewed,
            )
            print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
            return 0
        if args.command == "derive-recordings":
            recipe = load_derivative_recipe(args.recipe)
            manifest = derive_recordings(
                recipe,
                args.output,
                allow_overwrite=args.overwrite_reviewed,
            )
            print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
            return 0
    except (BakeError, DerivativeError) as exc:
        print(f"ui-foley authoring failed: {exc}")
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
