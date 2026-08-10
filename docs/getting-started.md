# Getting started

SonicMatter 0.1.0-rc0 is a small Godot 4.6.1 addon plus a standalone 3D
acceptance scene. Bring legal impact samples, describe both sides of a contact,
and let an explicit route map choose the bounded, deterministic sample pool.

!!! info "Current evidence boundary"
    Gate A is sample-first, not an AI sound generator or the planned hybrid DSP
    renderer. Windows and Godot 4.6.1 are the bound target. The timed first-user
    study is still outstanding, so RC0 is not a Gate A completion claim.

## Try the acceptance scene

Clone the repository and open it with Godot 4.6.1:

```powershell
git clone https://github.com/andyandymike/sonic-matter.git
cd sonic-matter
godot --path .
```

The scene drops `wood_prop`, `metal_prop`, and `stone_prop` onto
`stone_ground`. Each collision uses an exact ordered route while retaining the
synthetic profiles you hear in the baseline demo.

| Control | Result |
| --- | --- |
| `Space` | Reset and drop all three bodies |
| `1`, `2`, `3` | Reset one material body |
| `R` | Reset all bodies |

The overlay reports route tiers and drops alongside selection, playback,
no-repeat, missing mappings, voices, and steals.

## Install the addon

Every successful RC0 CI run builds an addon zip and a self-contained source-demo
zip. Until a tagged release exists, you can also build both locally:

```powershell
python -X utf8 tools/package_rc0.py --kind all
```

Extract `sonic-matter-addon-0.1.0-rc0.zip` into the root of a Godot project,
then enable **SonicMatter** under **Project Settings → Plugins**. Python is only
maintainer packaging tooling; the installed addon needs no Python, compiler,
model, cloud service, or GPU.

Create this minimal relationship:

```text
World
├── SonicFoleyEmitter3D (owns SonicImpactRouteMap)
├── Ground (StaticBody3D)
│   ├── CollisionShape3D
│   └── SonicMaterialBinding3D (target material)
└── Prop (RigidBody3D)
    ├── CollisionShape3D
    └── SonicRigidBodyImpactAdapter3D (source material)
```

The adapter and binding must be direct children of their collision bodies.
Collision shapes, layers, and masks still come from the game.

## Author materials and routes

Create three resources for a first pair:

1. A source `SonicAcousticMaterial`, for example `wood_crate`, with a stable
   `family_id` such as `wood`.
2. A target `SonicAcousticMaterial`, for example `stone_floor`, with family
   `stone`.
3. An output `SonicAcousticMaterial` containing at least two
   `SonicSampleVariant` entries with legal WAV or OGG streams.

Set each variant's weight, gain, and pitch, then bound the output material's
intensity gain and variation. Three closely related recordings are a practical
starting point; more than one eligible variant enables no-adjacent-repeat.

Create a `SonicImpactRoute` whose source and target IDs match the first two
resources and whose output points at the third. Append it to
`SonicImpactRouteMap.exact_routes`, then assign that map to the emitter.

Resolution is always:

1. exact ordered pair;
2. reverse pair only when that route declares `symmetric`;
3. target-family fallback;
4. source-family fallback;
5. global default;
6. visible deterministic drop.

Multiple matches at one tier fail closed.

## Connect physics events

On `SonicRigidBodyImpactAdapter3D`:

- point `emitter_path` at the shared emitter;
- assign the source acoustic material;
- use a scene-unique `stable_source_id`;
- tune `reference_speed_mps` and `minimum_intensity`;
- use `priority` to protect important events during a voice storm.

Add `SonicMaterialBinding3D` to the contacted static or physics body and
assign its target material. If both bodies have adapters, the lower stable
source ID emits one canonical report. Source/target roles and intensity remain
estimated rather than measured physical impulse.

## Submit authored events

Gameplay code can bypass the physics adapter while using the same route map:

```gdscript
var event := SonicFoleyEvent.impact(
    event_id,
    seed,
    0.7,
    global_position,
    10,
    SonicFoleyEvent.Evidence.AUTHORED,
    source_material.stable_id(),
    target_material.stable_id(),
    SonicFoleyEvent.Evidence.AUTHORED,
)

$SonicFoleyEmitter3D.play_impact(
    source_material,
    target_material,
    event,
)
```

This path fits weapon hits, doors, abilities, and events not represented by a
rigid-body contact.

## Verify the checkout

```powershell
godot --headless --path . --script res://tests/gate_a/test_runner.gd
godot --headless --path . --script res://tests/gate_a/scene_smoke_runner.gd
godot --headless --path . --script res://tests/gate_a/lifecycle_smoke_runner.gd
godot --headless --path . --script res://tests/gate_a/audio_safety_runner.gd
godot --headless --path . --script res://tests/gate_a/submission_probe.gd
python -X utf8 tools/package_rc0.py --kind all
python -X utf8 tools/verify_clean_install.py --archive artifacts/packages/sonic-matter-addon-0.1.0-rc0.zip --godot godot
```

Passing runs emit `GATE_A_TESTS_OK`, `GATE_A_SCENE_SMOKE_OK`,
`GATE_A_LIFECYCLE_OK`, and two `PACKAGE_BUILD_OK` records. CI additionally
exports the Windows release, runs its `--gate-a-export-smoke` path, and retains
the executable, PCK, logs, and archives as a workflow artifact.

## What is not implemented yet

- production Foley assets or automatic sound generation;
- resonators, material body modes, and roughness synthesis;
- footsteps, scrape, roll, ambience, retrieval, or vocal queries;
- a native DSP runtime or baking pipeline;
- verified support outside Godot 4.6.1 on Windows;
- the five-person timed Gate A acceptance study.

See the [Gate A contract](gate-a-contract.md) for the normative public scope.
