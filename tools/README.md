# Tools

package_rc0.py builds and verifies deterministic Gate A addon and source-demo
archives. It rejects tracked private paths, validates the rights manifest and
source hashes, records every packaged file SHA-256, and verifies the completed
zip before returning success.

~~~powershell
python -X utf8 tools/package_rc0.py --kind all
python -X utf8 tools/package_rc0.py --verify artifacts/packages/sonic-matter-addon-0.1.0-rc0.zip
python -X utf8 tools/verify_clean_install.py --archive artifacts/packages/sonic-matter-addon-0.1.0-rc0.zip --godot godot
~~~

The packager is maintainer/CI tooling. Games using the addon do not require
Python.

## Experimental Material Lab

`tools/material_lab` is the separate, bake-first research path for rights-gated
Material Kits and no-training modal/residual impact analysis. It remains
outside Gate A and is not imported by the Godot addon. See
`tools/material_lab/README.md` for its exact claims, six-arm workflow, and
quarantine rules.
