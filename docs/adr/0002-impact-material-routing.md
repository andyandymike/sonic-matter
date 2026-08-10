# ADR 0002: explicit impact material-pair routing

Status: accepted for Gate A RC0  
Date: 2026-08-10

## Context

The bootstrap adapter selected its own acoustic material and ignored the
contacted body. That was enough to prove deterministic sample selection, but it
could not distinguish a wood prop striking stone from the same prop striking
metal, nor could it expose a missing contact mapping.

Gate A needs one small, inspectable routing contract before DSP work starts.

## Decision

- The adapter's rigid body is the **source** and the contacted collision body is
  the **target**. Because body_entered does not report physical exciter roles,
  this assignment is marked estimated.
- A target exposes its SonicAcousticMaterial through a direct
  SonicMaterialBinding3D child or another impact adapter.
- When both rigid bodies have impact adapters, only the lower
  stable_source_id reports the contact. A stable node-path comparison breaks
  an accidental equal-ID tie. Scene authors remain responsible for unique IDs.
- One emitter owns a SonicImpactRouteMap. Resolution order is:
  1. exact ordered source-target pair;
  2. reverse match only for a route explicitly marked symmetric;
  3. target-family fallback;
  4. source-family fallback;
  5. global impact default;
  6. deterministic drop.
- More than one match at the same tier, or a matched route without an output
  material, fails closed instead of selecting by container order.
- The resolved output material owns the weighted sample variants. Source and
  target resources retain stable material and family identities.
- Every resolution tier and drop is visible in the emitter debug snapshot.

## Consequences

The acceptance scene now proves three explicit ordered routes:
wood_prop, metal_prop, and stone_prop striking stone_ground. Existing synthetic
profiles remain the audible baseline, so routing work does not claim a
sound-quality improvement.

Authored gameplay events call
play_impact(source_material, target_material, event). Missing route maps no
longer fall back silently to the source material.

The canonical source rule prevents duplicate reports from two monitored rigid
bodies, but it is still an estimated Gate A policy. A later measured-contact
adapter may replace it behind a new public decision.

## Revisit conditions

Revisit this ADR if a representative game cannot supply stable source IDs, if
compound colliders require per-shape bindings, or if measured contact data
provides a better deterministic source-target rule.
