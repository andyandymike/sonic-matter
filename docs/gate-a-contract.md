# Gate A public contract

Gate A is a sample-first implementation slice. It is not the hybrid Foley
research result and it is not a production release.

## Included

- One normalized impact event with stable event ID, seed, estimated intensity,
  priority, and 3D position.
- An acoustic material containing weighted `AudioStream` variants.
- Deterministic weighted selection with no adjacent repeat when at least two
  eligible variants exist.
- Bounded pitch, gain, and intensity mapping.
- A shared pool of at most eight `AudioStreamPlayer3D` voices.
- Deterministic voice replacement and stale-release protection.
- A `RigidBody3D` adapter that labels velocity-based intensity as estimated.
- Observable counters for submissions, playback, invalid events, missing
  mappings, selections, prevented repeats, active voices, and steals.
- A self-contained 3D scene and project-authored synthetic test fixtures.

## Excluded

- Resonators, body modes, roughness synthesis, learned components, or native DSP.
- Footsteps, scrape, roll, ambience, similarity search, and vocal queries.
- Production Foley assets or any claim that the generated fixtures sound real.
- Cross-platform, performance, exported-package, or first-user acceptance
  claims until their evidence exists.

## Current compatibility

The development target is Godot 4.6.1 on Windows. Other Godot or platform
combinations are unverified rather than implicitly supported.

## Evidence required before calling Gate A complete

- Headless determinism, no-repeat, selection, validation, and voice-policy tests.
- Editor import without parser or plugin errors.
- Runtime smoke of the acceptance scene.
- Exported-build smoke.
- Asset-rights and public-package audit.
- The timed first-user workflow described by the private acceptance plan.

