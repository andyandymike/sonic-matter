# ADR 0001: Gate A bootstrap target

Status: accepted for the first implementation slice  
Date: 2026-08-10

## Context

SonicMatter needs executable evidence before selecting a native DSP language or
attempting the hybrid B0 renderer. Editing an existing game would couple the
first experiment to unrelated project state and make the open-source example
harder to reproduce.

## Decision

- Use Godot 4.6.1 as the exact development and validation version for Gate A.
- Start with a self-contained 3D acceptance scene under `examples/gate_a_3d/`.
- Support Windows first; this slice makes no cross-platform support claim.
- Use GDScript and engine-native `AudioStreamPlayer3D` playback for Gate A.
- Keep one shared emitter with a hard eight-voice ceiling.
- Drive impacts from `RigidBody3D.body_entered`; configure contact monitoring
  explicitly and treat velocity-derived intensity as estimated, not measured
  impulse.
- Use project-authored, runtime-generated PCM fixtures. They test routing,
  determinism, variation, and voice policy; they are not quality Foley.
- Defer native DSP, resonators, scrape lifecycle, footsteps, WAV baking, and
  active-game integration to later decisions and gates.

## Consequences

The first code can validate sample-first contracts with no compiler, model,
cloud service, downloaded audio, or third-party asset license. It cannot prove
the B0 research hypothesis or claim production sound quality.

Godot's documented positional player and rigid-body contact APIs are the
current integration boundary:

- <https://docs.godotengine.org/en/4.6/classes/class_audiostreamplayer3d.html>
- <https://docs.godotengine.org/en/4.6/classes/class_rigidbody3d.html>

## Revisit conditions

Revisit this ADR if the acceptance scene cannot reproduce routing decisions,
cannot keep the voice ceiling bounded, or cannot run in an exported Godot 4.6.x
build without a local compiler.

