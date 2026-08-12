# Gate A public contract

Gate A is a sample-first implementation slice. Version 0.1.0-rc1 is an
acceptance candidate, not the hybrid Foley research result or a production
release.

## Included

- One normalized impact event with stable event ID, seed, intensity, evidence,
  priority, 3D position, and source/target material identities.
- Acoustic materials with stable material/family IDs and weighted AudioStream
  variants.
- Explicit impact resolution in this fixed order: ordered pair, explicitly
  symmetric reverse pair, target family, source family, global default, drop.
- Fail-closed ambiguous, missing, and invalid route behavior.
- SonicMaterialBinding3D for contacted collision bodies.
- Deterministic weighted selection from the same initial state and ordered
  event trace, with no adjacent repeat when at least two eligible variants
  exist.
- A verify-only pre-refactor oracle for selector, allocator, and emitter
  decisions; the live selector delegates only ordered weighted/no-repeat choice
  to a stateless internal helper with no public type or schema.
- Bounded pitch, gain, and intensity mapping.
- One shared pool of at most eight AudioStreamPlayer3D voices.
- Deterministic voice replacement and stale-release protection. A full pool
  always admits the incoming event, then ranks existing voices by priority,
  importance, start order, and slot index; Gate A has no admission rejection.
- A RigidBody3D adapter that labels velocity and source/target roles as
  estimated, uses relative linear speed for two-rigid-body contacts, and
  suppresses duplicate two-adapter reports with a stable rule.
- Observable counters for route tiers/drops, submissions, playback, invalid
  events, sample misses, selections, prevented repeats, active voices, and
  steals.
- A self-contained 3D scene and project-authored synthetic test fixtures.
- Deterministic addon/demo archives with per-file hashes and a fail-closed
  rights audit.
- A checked-in Windows export preset, exported-build sentinel smoke, and
  logical PCK path/size/hash inventory that rejects forbidden content.

## Excluded

- Resonators, body modes, roughness synthesis, learned components, or native DSP.
- Footsteps, scrape, roll, ambience, similarity search, and vocal queries.
- Production Foley assets or any claim that the generated fixtures sound real.
- Cross-platform or measured real-time performance claims.
- A Gate A completion claim until the required first-user evidence passes.

## Current compatibility

The bound target is Godot 4.6.1 on Windows. Other Godot or platform combinations
are unverified rather than implicitly supported.

## Evidence required before calling Gate A complete

- Headless determinism, route-order, ambiguity, no-repeat, validation, and
  voice-policy tests.
- Editor import and plugin initialization without parser errors.
- Runtime, lifecycle/burst, generated-audio safety, and exported Windows
  release smokes.
- Blank-project plugin disable/enable/disable/re-enable and routed-impact smoke.
- Main-thread submission scaling metrics, explicitly not audio callback timing.
- Asset-rights and public-package audit with deterministic archive hashes.
- At least four of five new users reaching a first audible impact within 15
  minutes from an uninstalled local release archive without maintainer help.

The RC1 automation implements the machine-verifiable evidence paths. The timed
first-user study remains outstanding, so Gate A remains in progress.
