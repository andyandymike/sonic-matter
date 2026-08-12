# Runtime v2 compatibility evidence

`Runtime v2` is an internal architecture label, not a public platform or
support claim. This directory protects the Gate A v1 selector, allocator, and
emitter observations that existed before ADR 0003's narrow extraction.

Run the blocking Windows/Godot 4.6.1 replay with:

```powershell
godot --headless --path . --script res://tests/runtime_v2/gate_a_policy_compat_runner.gd
```

Passing output is `RUNTIME_V2_COMPAT_OK`.

The files under `golden/` were captured from commit
`52a25dc5c7cef4ab0136563b55d9d434afadbd86` while the add-on runtime, Gate A
examples, and Gate A tests had no diff. Each fixture records the source-file
hashes and exact little-endian IEEE-754 binary64 pitch/gain bits.

Normal tests and CI are verify-only. They must not regenerate these files.
Changing a golden requires an explicit oracle-version bump, reviewed migration
record, and public compatibility decision. JSON parses integral values as
numbers, so the runner normalizes only integral numeric representation; all
observable floating-point decisions remain exact hex strings.

The selector fixture also covers reset replay, non-contiguous eligible indices,
one eligible candidate, empty/default material identity, zero/non-finite
weights, legacy result keys, stream slot identity, and every counter. The
allocator fixture freezes steal ordering and stale-token release. The
end-to-end fixture freezes route identity, selection, voice tokens/steals, and
debug snapshots.

Ubuntu may run the same script as a non-support portability observation. A pass
does not expand the public compatibility target beyond Windows/Godot 4.6.1.
