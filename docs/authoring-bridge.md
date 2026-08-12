# Offline authoring bridge

Status: experimental public contract
Runtime impact: none
Model requirement: none

The authoring bridge has two independent, offline paths:

1. compile an audited sample-first Material Kit and an explicit plan into the
   current Gate A Godot resources; and
2. validate a tightly bounded mix suggestion as a non-authorizing draft.

Neither path performs AI inference. A future local model or user-supplied API
may create proposal JSON, but it receives no authority from this contract.
Runtime games continue to load ordinary audio and `.tres` resources without
Python, NumPy, a model, a network connection, or a GPU.

See [ADR 0004](adr/0004-ai-assisted-authoring-bridge.md) for the decision and
trust boundary.

## Trust boundaries

- Kit inventory, source bytes, hashes, rights records, and the explicit compile
  plan are authoritative inputs to compilation.
- Proposal text is untrusted input. Validation never applies it.
- `allow` and publication eligibility come only from deterministic rights
  validation and project decisions. The proposal validator cannot edit them.
- The compiler supports only the current sample-first Gate A impact resources.
  It does not decide the future B0 portable hybrid format.
- Generated output belongs outside `addons/sonic_matter/`. It is game content,
  not a dependency of the core addon.

## Compile-plan contract

The plan schema is `sonic-godot-compile-plan/v1`. It must be a regular UTF-8
JSON file outside the Kit directory. It locks the exact raw SHA-256 of the Kit
manifest; whitespace changes therefore invalidate a stale plan.

Minimal target-family example:

```json
{
  "schema": "sonic-godot-compile-plan/v1",
  "kit": {
    "kit_id": "mygame.starter.impacts",
    "version": "0.1.0",
    "manifest_sha256": "<64 lowercase hex characters>"
  },
  "runtime": {
    "contract": "sonic-matter/gate-a-impact/v1",
    "sonic_matter_version": "0.1.0-rc1",
    "godot_version": "4.6"
  },
  "materials": [
    {
      "material_id": "wood_prop",
      "family_id": "wood",
      "roles": ["source"]
    },
    {
      "material_id": "stone_floor",
      "family_id": "stone",
      "roles": ["target"]
    }
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
          "asset_id": "mygame:impact:wood-stone-01",
          "weight": 1.0,
          "gain_db": 0.0,
          "pitch_scale": 1.0
        }
      ]
    }
  ],
  "routes": {
    "exact": [],
    "target_family": [
      {
        "fallback_id": "stone_family_fallback",
        "family_id": "stone",
        "palette_id": "wood_on_stone"
      }
    ],
    "source_family": [],
    "global_default": null
  }
}
```

Important rules:

- IDs are bounded lowercase ASCII identifiers. Material IDs and palette IDs
  cannot collide.
- Every material declares at least one `source` or `target` role. The complete
  source-role by target-role matrix must equal the Kit coverage matrix.
- A palette has 1-32 variants. Slots are unique and contiguous from zero.
  Variant order is semantic. Adjacent no-repeat needs at least two eligible
  variants; one variant intentionally produces a fixed sound.
- `asset_id` resolves through the rights manifest, Kit inventory, current input
  bytes, and copied output bytes to the same SHA-256 and byte count.
- Compiler v1 accepts only non-empty RIFF/WAVE format-tag-1, uncompressed
  mono/stereo PCM with a bounded sample rate and complete frame payload. It
  validates content, copies
  bytes, and does not transcode them or emit `.import` state.
- Numeric values must be finite and within the current runtime contract. Values
  are rejected rather than clamped.
- Exact routes, target-family fallbacks, source-family fallbacks, and the global
  default follow the current Gate A precedence. Same-tier ambiguity is an
  error.

Coverage is checked, not inferred:

| Kit state | Required result |
| --- | --- |
| `verified` | exact ordered or explicitly symmetric route |
| `fallback` | target family, source family, or global default |
| `unsupported` | deterministic drop |

Unused routes, fallbacks, palettes, or material definitions fail validation.
A fallback is retained as `fallback`; compilation never upgrades it to
`verified`.

## Compiler rights and output

Compiler targets are explicit, repeatable, and limited to:

- `local-preview`
- `game-source`
- `game-binary`

The compiler runs the existing `official-cc0` Kit validator for every requested
target. Unknown or denied public rights fail closed. A local-preview success is
not evidence that source or binary distribution is permitted.

```powershell
.venv\Scripts\python -m tools.material_lab validate-godot-plan `
  path\to\kit.json --plan path\to\plan.json `
  --rights-target game-source --rights-target game-binary

.venv\Scripts\python -m tools.material_lab compile-godot-kit `
  path\to\kit.json --plan path\to\plan.json `
  --output path\to\new-output-directory `
  --rights-target game-source --rights-target game-binary
```

The output directory must not exist. The compiler builds a sibling staging
directory, verifies inputs and output again, then publishes it with an atomic
no-replace operation. Compiler publication is supported on Windows and Linux in
v1; other authoring platforms fail closed until they have an equivalent
no-replace primitive. A
successful tree contains:

```text
audio/<source-sha256>.wav
materials/<material-id>.tres
impact_route_map.tres
compiled-manifest.json
```

`compiled-manifest.json` records source locks, requested rights targets, copied
asset lineage, resource mappings, resolved coverage, the exact non-manifest
file list, and `output_inventory_sha256`. It contains no timestamp, absolute
machine path, prompt, provider response, or private rights evidence.

Install the compiled tree in a Godot 4.6 project that already contains the
SonicMatter addon. Assign identity materials to the current impact adapter and
material bindings, and assign `impact_route_map.tres` to
`SonicFoleyEmitter3D`. Godot generates its own `.import` cache after install.

## Draft proposal contract

The proposal schema is `sonic-authoring-proposal/v1` with profile
`material-lab-impact-mix/v1`. It binds the exact raw SHA-256 of one existing
experimental `sonic-impact-recipe/v1` file.

```json
{
  "schema": "sonic-authoring-proposal/v1",
  "status": "draft",
  "profile": "material-lab-impact-mix/v1",
  "proposal_id": "local.wood-stone.mix.001",
  "base": {
    "artifact_schema": "sonic-impact-recipe/v1",
    "sha256": "<64 lowercase hex characters>"
  },
  "summary": "Reduce roughness dominance.",
  "changes": [
    {
      "kind": "set_layer_gain_db",
      "layer": "roughness",
      "from_db": -3.0,
      "to_db": -7.5,
      "reason": "The residual masks the current modal tail."
    }
  ]
}
```

Only `transient`, `body`, `roughness`, and `master` gains may change. There is
no JSON Pointer or generic patch operation. Each layer appears at most once;
`from_db` must match the base; changes must be finite, bounded, and non-noop.
All unknown fields and duplicate JSON keys fail closed.

```powershell
.venv\Scripts\python -m tools.material_lab validate-proposal `
  path\to\proposal.json --base path\to\recipe.json
```

Success prints `MATERIAL_PROPOSAL_DRAFT_OK`. The receipt says
`applied: false`, `authorization: "none"`, and
`render_safety_evaluated: false`. The validator writes no candidate recipe and
does not render, approve, publish, or compile anything. It also verifies that
algorithm, safety, rights, modes, roughness, audio paths and hashes, identity,
render settings, and every undeclared field remain unchanged in its in-memory
candidate.

## Claim boundary

This feature proves that untrusted authoring suggestions can be placed behind a
typed, reviewable, fail-closed envelope. It does not prove that an AI suggestion
is useful, sounds better, is safe to render, is legally publishable, or should
be accepted. Adding a model, provider SDK, remote API, embedding index, or
generated waveform requires a separate public decision and evaluation.
