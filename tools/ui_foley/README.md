# Experimental UI Foley Baker

This directory contains two offline authoring paths. The original `bake`
command is standard-library-only and renders the private Experiment U0
paper-turn candidates. The `derive-recordings` command creates bounded PCM16
WAV derivatives from an explicitly audited recording pack and uses one pinned,
authoring-only decoder. Both paths are deliberately outside the public Godot
add-on and do not create a public SonicMatter API or a runtime dependency.

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

## Audited recording derivatives

Install the optional authoring dependency, then run the derivative recipe from
the repository root:

~~~powershell
.venv\Scripts\python -m pip install -r requirements-ui-derivative.txt
.venv\Scripts\python -X utf8 -m tools.ui_foley derive-recordings --recipe tools/ui_foley/recipes/judgement-horror-paper-switch-v1.json --output artifacts/ui-foley/judgement-horror-paper-switch-v1
~~~

`miniaudio==1.71` is pinned only to decode the approved Ogg Vorbis parents into
the recipe's frozen signed-16, 44.1 kHz stereo profile. It is not imported by
the Godot add-on and must not be bundled with a game. The recipe locks the
parent manifest and source hashes, exact frame slice, linear fade frames, Q15
gain, and expected output hash for every output. The command writes ordinary
PCM16 WAV files plus
`derivative-manifest.json`; it does not write Godot resources or `.import`
state. Output is constrained below ignored `artifacts/ui-foley/`. A reviewed
overwrite stages and verifies the complete file inventory before replacing the
prior pack, so validation failure cannot leave a mixed old/new manifest.

Derivative manifests remain `approval_state: candidate`. A byte-reproducible
bake and permissive parent rights are necessary provenance evidence, not a
listening approval. Review each cue unprompted and in its real interaction,
then copy only accepted WAV files and their manifest/notices into the game.
The game should import and play those ordinary assets through its own
non-spatial UI audio layer. The SonicMatter runtime add-on, Python, miniaudio,
and recipes are not runtime requirements; a copied manifest is provenance,
not executable runtime input.

## Rights boundary

The recipe uses no recordings or external sound assets. That fact does not
grant an outbound media license. The current outputs are authorized only for
local preview and the private Judgement Horror dogfood integration. Public
source, binary, Material Kit, evaluation-stimulus, and standalone-audio
distribution remain fail-closed until the private D-015 decision is made.
Training/fitting, private embeddings, and index redistribution remain unknown
under the same decision; a successful local bake is not a publication grant.

Recording derivatives have a separate boundary. Their recipe must bind an
approved CC0 parent manifest and preserve explicit `allow` decisions for game
source and binary distribution. Each generated asset records its parent ID,
path and hash, the ordered transforms, output hash, audio format, and safety
metrics. Those rights do not promote the experimental U0 synthesis outputs or
the derivative command into the public runtime add-on.
