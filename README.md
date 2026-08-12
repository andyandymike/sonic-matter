# SonicMatter

Physics-driven, controllable Foley for games.

[![CI](https://github.com/andyandymike/sonic-matter/actions/workflows/ci.yml/badge.svg)](https://github.com/andyandymike/sonic-matter/actions/workflows/ci.yml)
[![Docs](https://github.com/andyandymike/sonic-matter/actions/workflows/docs.yml/badge.svg)](https://andyandymike.github.io/sonic-matter/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

SonicMatter is an experimental open-source project exploring how gameplay and
physics events can drive responsive sound effects without requiring a cloud
service, a large generative model, or a high-end GPU.

The intended direction combines a small amount of recorded audio with
procedural excitation, resonance, friction, variation, and game-engine spatial
processing. Generated results should remain deterministic when requested and
should be exportable as ordinary audio assets for constrained platforms.

## Status

Gate A 0.1.0-rc1 contains an explicit source-target material router,
deterministic sample selection, an eight-voice runtime, lifecycle/burst smokes,
fail-closed rights-aware packaging, and a real Windows exported-build smoke on
Godot 4.6.1. It remains an experimental acceptance candidate rather than a
production release: the five-person timed workflow is still outstanding.
RC1 freezes the RC0 selector, allocator, and emitter decisions in an external
verify-only oracle before extracting one private weighted/no-repeat helper; it
does not add a new event family, UI/2D API, DSP renderer, or quality claim.

The private working specification is intentionally excluded from version
control. Stable decisions are rewritten as public documentation before
implementation or release.

The current public contract is [docs/gate-a-contract.md](docs/gate-a-contract.md).
Bootstrap and explicit pair-routing decisions are recorded in
[ADR 0001](docs/adr/0001-gate-a-bootstrap.md) and
[ADR 0002](docs/adr/0002-impact-material-routing.md). The compatibility-only
extraction is recorded in [ADR 0003](docs/adr/0003-weighted-choice-microkernel.md).
The rendered documentation is published at
[andyandymike.github.io/sonic-matter](https://andyandymike.github.io/sonic-matter/).

## Principles

- Local-first and offline-capable.
- Useful on ordinary consumer hardware.
- Artistic control over opaque automation.
- Reproducible output for the same initial selector state and ordered event stream.
- Standard audio export as a deployment fallback.
- Explicit provenance and licensing for every bundled asset and model.
- A small, engine-independent DSP core with Godot as the first integration.

## Repository layout

- `addons/sonic_matter/` — the experimental Godot addon and runtime slice.
- `docs/` — stable public contracts and architecture decisions.
- `content-packs/` — optional, separately licensed audio with per-file provenance.
- `examples/gate_a_3d/` — explicit material-pair acceptance scene.
- `tests/gate_a/` — deterministic, scene, lifecycle, and burst evidence.
- `tests/runtime_v2/` — verify-only legacy decision goldens and replay runner.
- `packaging/` — canonical addon/demo package inputs.
- `tools/package_rc0.py` — deterministic package and rights audit.

## Quick verification

With Godot 4.6.1 available as `godot`:

```powershell
godot --headless --path . --script res://tests/gate_a/test_runner.gd
godot --headless --path . --script res://tests/gate_a/scene_smoke_runner.gd
godot --headless --path . --script res://tests/gate_a/lifecycle_smoke_runner.gd
godot --headless --path . --script res://tests/gate_a/audio_safety_runner.gd
godot --headless --path . --script res://tests/gate_a/submission_probe.gd
godot --headless --path . --script res://tests/runtime_v2/gate_a_policy_compat_runner.gd
python -X utf8 tools/package_rc0.py --kind all
```

Passing output includes `GATE_A_TESTS_OK`, `GATE_A_SCENE_SMOKE_OK`,
`GATE_A_LIFECYCLE_OK`, and two `PACKAGE_BUILD_OK` records. CI additionally
requires `RUNTIME_V2_COMPAT_OK`, exports and runs the Windows release sentinel,
and audits the logical PCK inventory.

## Contributing

Narrow changes within the current Gate A contract are welcome. Larger runtime,
authoring, model, network, and dependency changes need a public design decision
first. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Project-authored source code and documentation are licensed under the MIT
License unless a file states otherwise. Third-party assets and dependencies
retain their own licenses and must be recorded explicitly.
