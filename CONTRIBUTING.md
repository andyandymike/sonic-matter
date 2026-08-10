# Contributing to SonicMatter

Thank you for helping shape SonicMatter.

## Current phase

The project is implementing the narrow Gate A vertical slice described in
`docs/gate-a-contract.md`. Changes inside that contract may be proposed
directly. Please open an issue before expanding platforms, event families,
runtime dependencies, authoring tools, models, or asset policy.

## Contribution expectations

- Keep changes narrow and explain the game-development use case.
- Prefer reproducible evidence over subjective performance claims.
- Do not add network services, telemetry, model downloads, or runtime Python
  dependencies without an explicit design decision.
- Do not commit private planning material from `spec/`, `planning-private/`, or
  `.local/`.
- Do not add audio, datasets, model weights, or generated assets without their
  source, author, license, redistribution terms, and permitted use.
- Do not use assets for ML training when their license permits media use but
  prohibits training.
- Keep the audio thread free from blocking I/O, locks, logging, and dynamic
  allocation unless a reviewed design proves otherwise.

## Reports and proposals

Use the issue templates when possible. A useful proposal describes:

1. The sound-design problem.
2. The game event or control signal involved.
3. The expected authoring and runtime behavior.
4. Target platforms and performance constraints.
5. Asset, dependency, and license implications.
6. How success can be measured or heard reproducibly.

## Public documentation

Private working notes are not project documentation. Once a design decision is
stable, rewrite the relevant conclusion under `docs/` without copying private
discussion or unpublished material verbatim.
