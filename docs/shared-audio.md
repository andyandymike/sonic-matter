# Shared local audio authoring

`python -m tools.authoring` combines registered recording snapshots and the
frozen SonicMatter Q15 profile with shared editing. Python and the decoder are
authoring dependencies; the Godot addon consumes ordinary audio resources.
Both products use Matter Audio Core **0.6.0** for sessions, PCM protection, jobs,
comparisons, loops, scene timelines, cue packages and measured local search.

## Install from a clean checkout

Use Python 3.10+ and Git. Run from this repository's root. The build step accesses
GitHub and the Python package index for source and tooling; it downloads no audio
model. Create and activate an environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

On Linux/macOS, activate with `source .venv/bin/activate` instead. Then run the
same commands on either platform:

```sh
python -m pip wheel --wheel-dir .local/audio-wheels -r requirements-authoring.txt
python -m pip install --no-index --find-links .local/audio-wheels "matter-audio-core==0.6.0" "miniaudio==1.71"
python -m pip check
python -m tools.authoring capabilities --json
python -X utf8 tools/check_shared_audio.py
```

`requirements-authoring.txt` builds the core from immutable commit
`7834d03ad5447dd383b3f011e20d381ac0aa0f03`. It does not assume the core is on PyPI.
The second step installs only the collected wheels. Retain that directory for
offline installation on compatible Python/platform environments. Transitive
third-party dependencies are resolved during the build; this is not a lockfile
for every platform or a byte-reproducible wheel build. An absent core or a version
other than 0.6.0 returns a structured installation error.

The verification script requires every adapter test to pass without skips. It
uses fresh installed CLIs with an existing registered CC0 recording to check
normalization, loops, scene rendering, revision-bound cue exports and local
search, including original and exported bytes. It calls no model and plays no
audio. Windows and Linux run this as a required CI job.

## Start from registered recordings

```sh
python -m tools.authoring --workspace artifacts/shared-audio catalog list --json
python -m tools.authoring --workspace artifacts/shared-audio catalog decode starninjas.book-flip.08 --request-id decode-001 --json
python -m tools.authoring --workspace artifacts/shared-audio inspect ASSET_ID --json
python -m tools.authoring --workspace artifacts/shared-audio action execute --request trim.json --json
```

Use the returned `audio` asset ID for `ASSET_ID` and request inputs. Other outputs
preserve registration JSON and compressed source bytes. The decoder profile is
miniaudio 1.71, PCM16 stereo, 44100 Hz, without dither; it loads only for decoding.
The catalog checks approved StarNinjas CC0 registration and current source hashes.
Arbitrary file import is not exposed by this entry point. Example `trim.json`:

```json
{"schema":"matter-action/v1","request_id":"trim-001","operation":"trim/v1","inputs":["ASSET_ID"],"parameters":{"start_seconds":0,"end_seconds":0.1}}
```

Inside this repository, audio workspaces must be children of `artifacts/`, with
the tracked `artifacts/.gdignore` present. An explicit workspace outside the
Godot project is also supported. Authoring tools, tests, recordings and workspaces
stay outside the frozen addon/package inventory and Godot export.

`sonic.recording_condition/v1` preserves the fused Q15 chain: `start_frame`,
`frame_count`, `fade_in_frames`, `fade_out_frames` and `gain_q15`. It requires
44100 Hz stereo input and keeps the existing frozen derivative byte expectations.
This operation does not project PCM locks; use shared trim/fade after protecting
a selected recording. Obtain every scene/mix input through the registered catalog.

## Shared operations and continued work

`capabilities --json` returns exact schemas:

| Workflow | Commands and operations |
| --- | --- |
| PCM editing | `inspect`, `gain/v1`, `trim/v1`, `fade/v1`, `mix/v1`, `splice/v1` |
| Continued work | `session`, `feedback`, `context`, `constraints` |
| Managed execution | `job`, `batch`, explicit cancellation and recovery |
| Comparison and delivery | `audition`, `export`, `cue-set` |
| Production authoring | `normalize/v1`, `loop/v1`, `scene/v1`, `analyze`, `library` |

Use `action resolve` before editing and `action show REQUEST_ID` to query a
request. Reuse its ID for a retry; a pending request requires inspection or
recovery before resubmission. Read context before editing a selected asset.
Session mutations use the observed `expected_revision`; restoring appends a
revision. Feedback keeps its actual source and evaluated revision.

Managed jobs bind current selection and lock policy. Direct actions can bind a
protection session and revision. Final PCM is verified before publication. To
change one mixed layer, re-render the original immutable recipe with that layer
changed, preserving the relevant protection policy.

Cue exports bind exact WAV bytes and optional saved selections. Comparison-page
preview gain never changes delivery. Normalization uses RMS/peak, not LUFS;
overlap loops shorten the selected window; feature distance does not provide
semantic audio understanding. See the pinned
[core production guide](https://github.com/andyandymike/matter-audio-core/blob/7834d03ad5447dd383b3f011e20d381ac0aa0f03/docs/production.md)
for examples. These core operations call no audio model. Opening a comparison
page does not start playback. Listening and game integration remain separate.

## Upgrade an existing workspace

Stop clients and retain a backup before upgrading. Core 0.6.0 uses SQLite schema
4, the same schema as 0.5. For an older workspace:

```sh
python -m tools.authoring --workspace artifacts/shared-audio session migrate --json
```

Migration preserves audio and historical revisions and calls no model. Install
the same reviewed core version in every client using that workspace.
