# Gate A 3D acceptance scene

This scene exercises the current sample-first implementation. It creates three
rigid bodies, maps their collision speed to estimated impact intensity, and
routes all playback through one eight-voice emitter.

The sound fixtures are generated in memory by `generated_test_audio.gd`. They
are deliberately synthetic and are not evidence of production Foley quality.

## Controls

- `Space` — reset and drop all three bodies.
- `1`, `2`, `3` — reset one material body.
- `R` — reset all bodies.

The overlay exposes selection, no-repeat, missing-mapping, active-voice, and
voice-steal counters.

Run from the repository root with Godot 4.6.1:

```powershell
godot --path .
```

