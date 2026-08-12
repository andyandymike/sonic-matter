# Experimental UI Foley Baker

This standard-library-only authoring tool renders the private Experiment U0
paper-turn candidates. It is deliberately outside the public Godot add-on and
does not create a public SonicMatter API or a runtime model dependency.

## Experiment result

The initial `page-turn-u0` candidate failed its first maintainer listening
check on 2026-08-11: it was not identified as book or paper-page movement. Its
continuous friction sweep dominates the sparse details and reads as a generic
noise motion effect. Treat this bake as a reproducible negative control, not as
production Foley. Current game use should start from the separately licensed
real recordings in `content-packs/ui-page-turn-starninjas-cc0`.

Run it from the repository root:

~~~powershell
python -X utf8 -m tools.ui_foley bake --recipe tools/ui_foley/recipes/page-turn-u0.json --output artifacts/ui-foley/page-turn-u0
~~~

The default bake writes six experimental stereo PCM24 masters, layer stems,
ablations, and a hash-addressed manifest. All randomness is derived from named
domains, so a change to one layer cannot silently reshuffle another layer.

## Rights boundary

The recipe uses no recordings or external sound assets. That fact does not
grant an outbound media license. The current outputs are authorized only for
local preview and the private Judgement Horror dogfood integration. Public
source, binary, Material Kit, evaluation-stimulus, and standalone-audio
distribution remain fail-closed until the private D-015 decision is made.
Training/fitting, private embeddings, and index redistribution remain unknown
under the same decision; a successful local bake is not a publication grant.
