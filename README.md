# SonicMatter

Physics-driven, controllable Foley for games.

SonicMatter is an experimental open-source project exploring how gameplay and
physics events can drive responsive sound effects without requiring a cloud
service, a large generative model, or a high-end GPU.

The intended direction combines a small amount of recorded audio with
procedural excitation, resonance, friction, variation, and game-engine spatial
processing. Generated results should remain deterministic when requested and
should be exportable as ordinary audio assets for constrained platforms.

## Status

Gate A implementation has started. The repository now contains a narrow Godot
4.6.1 vertical slice for deterministic, physics-driven 3D impact Foley. It is
an experimental acceptance harness, not a production release.

The private working specification is intentionally excluded from version
control. Stable decisions are rewritten as public documentation before
implementation or release.

The current public contract is [docs/gate-a-contract.md](docs/gate-a-contract.md),
with bootstrap decisions recorded in
[docs/adr/0001-gate-a-bootstrap.md](docs/adr/0001-gate-a-bootstrap.md).

## Principles

- Local-first and offline-capable.
- Useful on ordinary consumer hardware.
- Artistic control over opaque automation.
- Deterministic seeds and reproducible output.
- Standard audio export as a deployment fallback.
- Explicit provenance and licensing for every bundled asset and model.
- A small, engine-independent DSP core with Godot as the first integration.

## Repository layout

- `addons/sonic_matter/` — the experimental Godot addon and runtime slice.
- `docs/` — stable public contracts and architecture decisions.
- `examples/gate_a_3d/` — standalone 3D impact-Foley acceptance scene.
- `tests/gate_a/` — deterministic selection and instrumented scene tests.
- `tools/` — reserved for later authoring and asset-validation tools.

## Quick verification

With Godot 4.6.1 available as `godot`:

```powershell
godot --headless --path . --script res://tests/gate_a/test_runner.gd
godot --headless --path . --script res://tests/gate_a/scene_smoke_runner.gd
```

The commands pass only when they print `GATE_A_TESTS_OK` and
`GATE_A_SCENE_SMOKE_OK`, respectively, and exit with code `0`.

## Contributing

Narrow changes within the current Gate A contract are welcome. Larger runtime,
authoring, model, network, and dependency changes need a public design decision
first. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Project-authored source code and documentation are licensed under the MIT
License unless a file states otherwise. Third-party assets and dependencies
retain their own licenses and must be recorded explicitly.
