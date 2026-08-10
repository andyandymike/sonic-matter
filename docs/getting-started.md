# Getting started

SonicMatter currently ships as a small Godot 4.6.1 addon and a standalone 3D
acceptance scene. Gate A is designed for experimentation: bring your own legal
impact samples, connect one shared emitter, and let deterministic event logic
handle variation and bounded playback.

!!! info "Current evidence boundary"
    Gate A is a sample-first runtime slice, not an AI sound generator or the
    planned hybrid DSP renderer. Windows and Godot 4.6.1 are the verified
    development target.

## Try the acceptance scene

Clone the repository and open its project with Godot 4.6.1:

```powershell
git clone https://github.com/andyandymike/sonic-matter.git
cd sonic-matter
godot --path .
```

The scene drops three rigid bodies with deliberately synthetic wood, metal, and
stone test profiles.

| Control | Result |
| --- | --- |
| `Space` | Reset and drop all three bodies |
| `1`, `2`, `3` | Reset one material body |
| `R` | Reset all bodies |

The overlay reports submitted, selected, and played events, active voices,
steals, prevented repeats, missing mappings, and invalid events.

## Install the addon

There is no Asset Library or release package yet. Copy
`addons/sonic_matter/` into the target game's `res://addons/sonic_matter/`, then
enable **SonicMatter** under **Project Settings → Plugins**.

Create this minimal scene relationship:

```text
World
├── SonicFoleyEmitter3D
└── Prop (RigidBody3D)
    ├── CollisionShape3D
    └── SonicRigidBodyImpactAdapter3D
```

The adapter must be a direct child of a `RigidBody3D`. It enables contact
monitoring automatically, but the body still needs valid collision shapes,
layers, and masks.

## Author an acoustic material

1. Create a `SonicAcousticMaterial` resource.
2. Give `material_id` a stable, meaningful value such as `wood_crate`.
3. Add at least two `SonicSampleVariant` entries to `impact_variants`.
4. Assign a legal WAV or OGG `AudioStream` to each variant.
5. Calibrate each variant's `weight`, `gain_db`, and `pitch_scale`.
6. Set the material's intensity gain range and bounded variation.

Using three closely related recordings is a practical starting point. More than
one eligible variant enables the no-adjacent-repeat rule.

## Connect physics events

On `SonicRigidBodyImpactAdapter3D`:

- point `emitter_path` at the scene's shared emitter;
- assign the acoustic material;
- use a scene-unique `stable_source_id`;
- tune `reference_speed_mps` to define a full-strength collision;
- raise `minimum_intensity` to suppress incidental contacts;
- use `priority` to protect important sounds during a voice storm.

The current adapter estimates intensity from body speed. It does not claim to
measure physical collision impulse or resolve source/target material pairs.

## Submit authored events

Gameplay code can bypass the physics adapter and call the emitter directly:

```gdscript
var event := SonicFoleyEvent.impact(
    event_id,
    seed,
    0.7, # Normalized intensity: 0.0–1.0
    global_position,
    10,  # Priority
    SonicFoleyEvent.Evidence.AUTHORED,
)

$SonicFoleyEmitter3D.play_impact(acoustic_material, event)
```

This path fits weapon hits, doors, abilities, and other events that are not
represented by a rigid body collision.

## Verify the checkout

```powershell
godot --headless --path . --script res://tests/gate_a/test_runner.gd
godot --headless --path . --script res://tests/gate_a/scene_smoke_runner.gd
```

Passing runs end with `GATE_A_TESTS_OK` and `GATE_A_SCENE_SMOKE_OK`.

## What is not implemented yet

- production Foley assets or automatic sound generation;
- resonators, material body modes, and roughness synthesis;
- footsteps, scrape, roll, ambience, retrieval, or vocal queries;
- a native DSP runtime, baking pipeline, or exported-package guarantee;
- verified support outside Godot 4.6.1 on Windows.

See the [Gate A contract](gate-a-contract.md) for the normative public scope.
