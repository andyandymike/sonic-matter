# ADR 0004: bound AI-assisted authoring behind an explicit compile plan

Status: accepted for an offline authoring experiment
Date: 2026-08-12

## Context

Material Kits can carry exact file inventories, recipes, selected audio, and
rights evidence, while the current Godot runtime consumes explicit
`SonicAcousticMaterial` and route resources. Connecting those two forms by hand
is repetitive and easy to review incorrectly.

An AI system may also suggest small mix adjustments, but model output is not a
trusted manifest, a rights decision, or a stable runtime dependency. SonicMatter
needs one public boundary that permits useful experimentation without turning a
proposal into executable authority or widening the Gate A and B0 claims.

## Decision

- Add an offline, deterministic compiler whose only authoritative inputs are a
  validated, exact-inventory Material Kit and an explicit, versioned Godot
  compile plan. The plan selects already declared assets and records stable
  material, variant, route, fallback, and compatibility data.
- Bind a compile to the exact Kit manifest, plan, referenced asset, recipe, and
  rights hashes. A stale or missing reference fails closed.
- Require the caller to state the intended distribution targets. The compiler
  validates the required rights actions for those targets; it never infers a
  grant from the repository license, a filename, an AI answer, or prior use.
- Emit only allowlisted Godot resources, exact copies of already approved audio,
  a provenance-bearing compiled manifest, and an exact output inventory.
  Generated paths are derived from
  validated identifiers and hashes, not from arbitrary proposal text.
- Keep generated kits separate from `addons/sonic_matter/`. The compiler,
  Python dependencies, plans, proposals, and generated content do not enter the
  core add-on or become required by a shipped game.
- Make compilation byte-reproducible for the same frozen inputs, compiler, and
  schema versions. Output contains no timestamp,
  absolute machine path, prompt, import cache, generated UID, or other
  machine-local state.

The optional AI bridge is narrower than the compiler:

- It accepts a versioned proposal bound to the raw SHA-256 of one experimental
  `sonic-impact-recipe/v1` file.
- It may propose only finite, bounded values for the recipe's four existing mix
  gains: transient, body, roughness, and master.
- Validation produces a **valid-draft receipt**, never a recipe, an approved
  plan, or an applied change. Applying a reviewed suggestion is deliberately
  outside this command and remains an explicit human edit.
- A proposal cannot add or select files; alter modes, roughness bands, safety,
  algorithms, render settings, audio paths or hashes; introduce material or
  route IDs; choose a rights target; or modify provenance, license, evidence,
  review, publication, or approval state.
- Unknown fields, duplicate JSON keys, non-finite or out-of-range numbers,
  excessive input, stale hashes, and invalid proposal IDs fail closed. Values
  are rejected rather than silently clamped.
- Raw prompts and provider responses remain local authoring input. Proposal
  rationale is inspected as untrusted text but is not echoed in the receipt or
  copied into generated resources, release archives, CI artifacts, or runtime
  logs.

## Explicit non-decisions

This ADR does not bundle, download, train, fine-tune, or invoke a model. It adds
no network service, embedding index, GPU requirement, model license, or model
file. Producing a proposal is outside the deterministic compiler and validator
boundary.

It does not change the Gate A runtime, public Godot Resource schemas, material
routing, playback policy, voice allocation, or package contents. It does not
implement the B0 modal-plus-residual renderer, promote an experimental recipe,
or claim an audible, perceptual, physical, or performance improvement.

It does not resolve D-007 or select the final Material Kit serialization. The
compile plan is a narrow bridge contract, not an implicit revision of the Kit
schema. It also does not resolve D-015, create an outbound audio license, or
convert unknown rights into permission. Public output remains blocked whenever
the required action or project output-audio grant is deny or unknown.

## Verification

The authoring gate must prove all of the following:

- the same frozen Kit and plan compile twice to identical logical paths, bytes,
  and exact output-inventory hash on each supported authoring CI platform;
  Windows and Linux both replay the same deterministic fixture contract;
- changing any bound Kit/plan byte changes or invalidates the compile, and
  changing any bound recipe byte invalidates its proposal;
- strict negative tests reject traversal, absolute and platform-unsafe paths,
  identifier and Godot-text injection, duplicate or unknown fields, non-finite
  numbers, stale references, output collisions, symlinks, and rights downgrade
  or upgrade attempts;
- a clean Godot 4.6.1 project loads the frozen generated fixture and observes
  the expected material, variant, route, and fallback values;
- the compiler refuses a non-empty or unsafe destination and publishes output
  atomically only after verifying its exact inventory;
- tests can disable network and model access without affecting proposal
  validation or compilation;
- the independently frozen add-on, demo, and Windows PCK inventories remain
  unchanged, and a clean add-on installation still runs without Python, a
  compiler, a model, a cloud service, or a GPU.

CI may generate disposable output only under ignored evidence or temporary
directories. It must not regenerate reviewed goldens or upload private
proposals, prompts, local paths, unapproved audio, or retained rights evidence.

## Consequences

Maintainers can turn an audited Kit and a reviewed plan into inspectable Godot
resources with less repetitive wiring. An external AI tool can help explore a
small recipe-mix space, but the validator does not apply its suggestion or
connect it to the compiler. Any accepted change remains a normal, reviewable
recipe edit followed by the existing analysis, render, rights, and Kit gates.

The boundary deliberately leaves asset selection, taxonomy design, route
semantics, perceptual judgment, rights review, and publication authority with
humans and deterministic project policy. A structurally valid proposal may
still sound worse and may be rejected without affecting the compiler or
runtime.

## Rollback and revisit conditions

Rollback removes the authoring compiler and proposal validator, deletes their
separately generated kit output, and returns to hand-authored Godot resources.
Because no runtime schema or package dependency changes, existing projects and
the Gate A add-on require no migration.

Rollback is required if deterministic output drifts, an unsafe reference can be
emitted, rights fail open, proposal text gains authority, or compiler artifacts
enter the core add-on, demo archive, or Gate A PCK.

Revisit this ADR through a new public decision before allowing AI to select or
create assets, author routes or taxonomy, approve rights, change public Resource
schemas, run inside a game, invoke a bundled or remote model, or participate in
the B0 renderer. Any final D-007 serialization decision and any D-015 outbound
audio grant remain separate decisions with their own evidence.
