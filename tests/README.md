# Tests

Gate A currently tests deterministic selection, no-adjacent-repeat behavior,
fail-closed input handling, generated PCM fixtures, the hard voice budget, and
the real physics-scene route into the shared emitter.

Run from the repository root with Godot 4.6.1:

```powershell
godot --headless --path . --script res://tests/gate_a/test_runner.gd
godot --headless --path . --script res://tests/gate_a/scene_smoke_runner.gd
```

Passing output ends with `GATE_A_TESTS_OK` and `GATE_A_SCENE_SMOKE_OK`; both
processes must exit with code `0`. The scene runner also prints its observable
counter snapshot and fails unless at least three collision events are selected
and played while the active voice count remains within eight.

Audio-thread profiling, clipping/discontinuity analysis, cross-platform golden
renders, asset-package auditing, and proportional runtime benchmarks remain
future gates; the current tests do not establish those claims.
