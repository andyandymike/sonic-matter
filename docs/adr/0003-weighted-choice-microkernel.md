# ADR 0003: freeze Gate A v1 before extracting weighted choice

Status: accepted for Gate A RC1
Date: 2026-08-12

## Context

`SonicSampleSelector` currently owns deterministic seed mixing, material-keyed
no-repeat history, weighted candidate choice, pitch/gain mapping, counters, and
the legacy result dictionary. The implementation is small, but its observable
behavior is now part of the Gate A evidence and package.

A second game-local audio integration uses similar candidate-selection ideas.
That is not enough evidence for a universal event, cue, allocator, telemetry,
or playback API. It is enough to test whether the smallest weighted/no-repeat
mechanism can be isolated without changing Gate A.

The old deterministic test compared two instances of the same current class.
Both instances could drift together, so it was not an independent compatibility
oracle. A refactor therefore requires a pre-refactor, verify-only golden trace.

## Decision

- Freeze the accepted pre-refactor selector, allocator, and emitter observations
  in reviewed JSON fixtures before changing the live selector.
- Treat Godot 4.6.1 on Windows x86-64 as the blocking compatibility oracle.
  Other platforms may replay it as portability observations, but that does not
  expand the Gate A support claim.
- Add one internal GDScript helper with no `class_name`, Node, Resource loading,
  file access, route knowledge, event knowledge, bus knowledge, or player
  lifecycle. It may only apply the existing ordered eligible-candidate,
  immediate no-repeat, and weighted-roulette rules.
- Let the existing `SonicSampleSelector.select_impact()` remain the compatibility
  wrapper. It continues to own validation, eligible-index scratch, stable
  material IDs, the event-ID/seed/material hash mix, pitch/gain mapping,
  history, counters, reset, stream lookup, and the exact legacy result shape.
- Pass a fixed-size caller-owned outcome scratch to the helper so extraction
  does not introduce a second result-object graph on the hot path.
- Preserve variant array order, removal of the previous index before weight
  normalization, and the current last-eligible fallback when the roulette
  target reaches the end.
- Keep `SonicVoiceAllocator`, material routing, `SonicFoleyEvent`,
  `SonicFoleyEmitter3D`, all public script paths and signatures, and all
  serialized Resources unchanged.
- Version the rebuilt public archives as `0.1.0-rc1`. The old RC0 hashes remain
  immutable evidence and must not be overwritten or relabeled.

## Explicit non-decisions

This ADR does not create Runtime v2 as a platform. It does not add UI or 2D
support, a cue catalog, another event family, a policy registry, native DSP,
footsteps, scrapes, resonators, deduplication, cooldown, a new allocator policy,
or audio-thread guarantees. The Judgement Horror cue semantics remain in that
game and the optional page-turn pack remains outside release archives and PCKs.

## Verification

The blocking runner must replay the captured selector outputs exactly:
empty/non-empty result, legacy key set, variant and stream slot, IEEE-754
binary64 pitch/gain bits, and counter deltas. It also replays allocator and
end-to-end emitter decisions, reset behavior, no-repeat, stale-token release,
route identity, voice tokens, and debug snapshots.

Normal tests may only verify the fixtures. Updating a golden requires an
explicit version bump and review; CI must never regenerate one.

RC1 additionally verifies deterministic add-on/demo archives, a blank-project
install, the existing five Gate A runners, and a Windows exported smoke. The
exported program enumerates logical PCK members with path, size, and SHA-256,
compares them with an independently frozen inventory, and rejects private,
test, tool, optional-content, and UI-Foley prefixes. An outer PCK hash alone is
not absence evidence.

## Consequences

The selector gains one narrow internal seam while callers and Resources do not
change. Goldens become permanent regression protection even if the helper is
later removed. The extraction makes no sound-quality or performance claim;
benchmarks only check that compatibility has not added unacceptable overhead or
unbounded retained state.

The RC0 export audit found that `export_filter="all_resources"` admitted the
optional `content-packs/` page-turn audio. RC1 must explicitly exclude that
tree. This is a packaging correction, not promotion of the content pack into
the SonicMatter runtime.

## Rollback and revisit conditions

Revert the helper and wrapper delegation immediately if any frozen selector,
allocator, emitter, package, or export decision drifts. No schema or caller
migration is allowed, so rollback is limited to those implementation changes.

Revisit a broader policy layer only after a second independent public
SonicMatter consumer demonstrates the same stable contract. UI or 2D promotion
requires separate decisions and evidence.
