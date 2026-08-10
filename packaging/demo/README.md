# SonicMatter Gate A demo 0.1.0-rc0

This is a self-contained source demo for Godot 4.6.1 on Windows.

Open `project.godot`, run the main scene, and press Space or 1/2/3 to repeat
the three source-to-ground impact routes. The sounds are synthetic test
fixtures, not production Foley.

Verification commands:

```powershell
godot --headless --path . --script res://tests/gate_a/test_runner.gd
godot --headless --path . --script res://tests/gate_a/scene_smoke_runner.gd
godot --headless --path . --script res://tests/gate_a/lifecycle_smoke_runner.gd
godot --headless --path . --script res://tests/gate_a/audio_safety_runner.gd
godot --headless --path . --script res://tests/gate_a/submission_probe.gd
```

The package manifest records every included file and SHA-256 digest.
