# Tools

package_rc0.py (historical name) builds and verifies the current Gate A addon and source-demo
archives. It rejects tracked private paths, validates the rights manifest and
source hashes, records every packaged file SHA-256, and verifies the completed
zip before returning success.

~~~powershell
python -X utf8 tools/package_rc0.py --kind all
python -X utf8 tools/package_rc0.py --verify artifacts/packages/sonic-matter-addon-0.1.0-rc1.zip
python -X utf8 tools/verify_clean_install.py --archive artifacts/packages/sonic-matter-addon-0.1.0-rc1.zip --godot godot
~~~

The packager is maintainer/CI tooling. Games using the addon do not require
Python.

## Experimental Material Lab

`tools/material_lab` is the separate, bake-first research path for rights-gated
Material Kits and no-training modal/residual impact analysis. It remains
outside Gate A and is not imported by the Godot addon. See
`tools/material_lab/README.md` for its exact claims, six-arm workflow, and
quarantine rules. Its optional authoring bridge also validates draft-only mix
suggestions and deterministically compiles an audited sample-first Kit into
current Gate A Godot resources; neither path invokes a model or enters runtime.

## Experimental UI Foley

The tools/ui_foley directory contains a standard-library-only, deterministic
procedural baker for the private page-turn Experiment U0. The first generated
candidate failed the maintainer's unprompted paper-identity listening check on
2026-08-11 and is retained as a negative control, not recommended game audio.
The optional `content-packs/ui-page-turn-starninjas-cc0` pack supplies ten real
CC0 page-turn recordings for current sample-first use.
