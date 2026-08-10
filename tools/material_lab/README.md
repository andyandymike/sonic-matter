# Material Lab (experimental)

Material Lab is SonicMatter's offline, no-training authoring path for impact
research. It turns one to three recordings into a compact modal-plus-residual
recipe, renders the six pre-registered B0 comparison arms, and validates audio
rights before anything enters a public Material Kit.

It is intentionally **not** part of the Godot runtime. Games and the Gate A
addon do not require Python, NumPy, a model, a GPU, or a network connection.

## Current boundary

- Analysis uses deterministic NumPy FFTs and decay fits. The estimates are
  perceptual controls, not claims about a material's physical constants.
- A recipe contains 6-12 resonators total and 2-4 filtered-noise roughness
  bands. Rendering is mono PCM24 and refuses silent clipping.
- The six arms are `sample_pool`, `transient_only`,
  `hybrid_minus_transient`, `hybrid_minus_body_resonator`,
  `hybrid_minus_roughness`, and `hybrid_full`.
- Removing one layer does not perturb another layer's random stream. Roughness
  uses a versioned PCG32 stream derived from recipe hash, seed, and variant.
- Running without a rights manifest is allowed only for private local research;
  the generated report records `publication_eligible: false`.
- This is a bake-first evidence slice. It does not yet satisfy the B0 realtime
  GDExtension, callback timing, listening-test, or public asset gates.

## Environment

From the repository root, use Python 3.12 or newer:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-material-lab.txt
```

NumPy is a BSD-3-Clause authoring/development dependency only. Do not vendor it
into the addon or a game package; it is not part of runtime package notices.

## Analyze and render

```powershell
.venv\Scripts\python -m tools.material_lab analyze `
  --input .local\recordings\wood-stone-01.wav `
          .local\recordings\wood-stone-02.wav `
          .local\recordings\wood-stone-03.wav `
  --source-material wood `
  --target-material stone `
  --output .local\material-lab\wood-stone

.venv\Scripts\python -m tools.material_lab render `
  .local\material-lab\wood-stone\recipe.json `
  --seed 42 `
  --output .local\material-lab\wood-stone-render-42
```

Add `--source-tap` and `--target-tap` recordings when separate free-decay taps
exist. Without them, every mode is explicitly labelled `pair-body`; the tool
does not pretend it has separated source and target physics.

## Quarantine before promotion

Downloaded archives belong under ignored `.local/material-intake/quarantine`.
Inventorying checks path traversal, special files, duplicate names, declared
sizes, compression ratios, and every member hash without extracting the ZIP:

```powershell
.venv\Scripts\python -m tools.material_lab inventory-archive `
  .local\material-intake\quarantine\candidate.zip `
  --source-url https://example.invalid/exact-asset-page `
  --license-claim CC0-1.0 `
  --acquired-at 2026-08-11 `
  --evidence .local\material-intake\quarantine\exact-source-page.html `
  --evidence .local\material-intake\quarantine\cc0-1.0-legalcode.txt `
  --review-note "Uploader authorship still needs human confirmation" `
  --output .local\material-intake\quarantine\candidate.inventory.json
```

The result always remains `approval_state: quarantine` with unknown rights.
Inventory is evidence, not permission. Promotion requires exact asset-page or
archive license evidence, hashes, authorship, parent lineage, and an action-by-
action rights review.

## Validate rights and a kit

```powershell
.venv\Scripts\python -m tools.material_lab validate-rights `
  path\to\asset-rights.json --target material-kit

.venv\Scripts\python -m tools.material_lab validate-kit `
  path\to\kit.json --profile official-cc0
```

Public targets fail closed on either `deny` or `unknown`. Local preview may use
`unknown`, but still rejects an explicit `deny`. `official-cc0` accepts only
project-owned/CC0 intake with an explicit `CC0-1.0` outbound media grant; it
does not infer an audio license from the repository's MIT code license.

## Tests

```powershell
.venv\Scripts\python -X utf8 -m unittest discover -s tests\material_lab -v
```
