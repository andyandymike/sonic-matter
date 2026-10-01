# Shared local audio authoring

`python -m tools.authoring` combines registered recording snapshots and the
frozen SonicMatter Q15 profile with shared editing. Python and the decoder are
authoring dependencies; the Godot addon consumes ordinary audio resources.
Both products use Matter Audio Core **0.6.0** for sessions, PCM protection, jobs,
comparisons, loops, scene timelines, cue packages and measured local search.

## Install from a clean checkout

Shared audio authoring supports Windows and Linux; Core 0.6.0 cannot publish
artifacts on macOS. Godot runtime support is documented separately in the
[Gate A contract](gate-a-contract.md).

Use Python 3.10+ and Git on Windows or Linux. Run from this repository's root.
The build step accesses GitHub and the Python package index for source and
tooling; it downloads no audio model. Create and activate an environment:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

On Linux, activate with `source .venv/bin/activate` instead. Then run the
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
search, including original and exported bytes. It also imports a synthetic
project WAV with ancillary RIFF metadata, checks idempotent retry and unverified
rights declarations, then exports the same original bytes. It calls no model
and plays no audio. Windows and Linux run this as a required CI job.

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
a selected recording. Obtain scene/mix inputs through the built-in catalog or
the explicit project recording manifest below.

## Import a project's own recordings

Keep `recordings.json` beside the project's source audio. Each source path is
relative to that manifest, even when the CLI runs from another directory.
The `recordings` commands are separate from the built-in approved CC0 catalog;
they do not add files to that catalog or enable generic `assets import`.

```sh
python -m tools.authoring --workspace /absolute/project/artifacts/audio recordings list --manifest /absolute/project/recordings.json --json
python -m tools.authoring --workspace /absolute/project/artifacts/audio recordings import door-close --manifest /absolute/project/recordings.json --request-id door-input-001 --json
```

Use absolute Windows paths such as `D:/Game/recordings.json` on Windows. Replace
the digest and byte count in this minimal manifest with the source file's
actual SHA-256 and size, and supply your own accurate source declarations:

```json
{
  "schema": "sonic-project-recordings/v1",
  "catalog_id": "my-game",
  "recordings": [{
    "recording_id": "door-close",
    "path": "recordings/door-close.wav",
    "sha256": "<64 lowercase hexadecimal characters>",
    "size_bytes": 123456,
    "creator": "Recording creator",
    "source": {"kind": "self_recorded", "reference": "Project field recording, take 3"},
    "rights": {
      "local_preview": {"status": "allow", "evidence_refs": ["recording-note"]}
    },
    "evidence": [{
      "id": "recording-note",
      "kind": "self_declaration",
      "reference": "Project recording log entry identifying creator and permitted local use"
    }]
  }]
}
```

`capabilities --json` exposes the full schema under
`product_capabilities.project_recordings.manifest_schema`. Source kinds are
`self_recorded`, `third_party`, and `synthetic_fixture`. Evidence kinds are
`self_declaration`, `license`, `permission`, and `other`; references are text,
including document references or URLs. The importer does not open or verify
those references, contact a service, or infer permission from a source kind.

Rights use `allow`, `deny`, or `unknown`. Omitted purposes remain `unknown`.
An `allow` declaration must reference an evidence ID present on that recording.
`deny` and `unknown` need no evidence, but any references supplied must exist.
Import requires an explicit `local_preview: allow`. Other purposes include
game source/binary distribution, standalone audio, material kits, evaluation,
fitting, training and embeddings; their exact names are in the schema.
Listing reports all entries, including those whose local use is denied or
unknown, without creating a workspace.

The manifest is strict JSON with unique recording IDs, evidence IDs and
case-insensitive source paths. Paths must be normalized relative WAV paths;
traversal, absolute source paths, symlinks and Windows junctions are rejected.
It supports up to 128 recordings. Listing reads at most 64 MiB of combined
audio; each imported WAV is limited to 64 MiB. WAV input must be ordinary
PCM16, mono or stereo, 8000–192000 Hz. No decoder, model, resampling or
re-encoding is involved. In particular, this does not convert an input to the
44100 Hz stereo format required by the frozen Q15 operation.

Import verifies the declared source hash and size, then publishes an immutable
registration/source/audio group. The original manifest is preserved as
`registration`; `recording_source` and the main `audio` both preserve the full
original WAV bytes, including ancillary metadata. The two copies make the
source-to-audio lineage explicit. Use the returned `audio` asset ID for shared
editing and cue exports. Source files and the manifest remain unchanged.

The same request ID and unchanged manifest/source bytes replay the saved
result. A changed valid manifest or source conflicts with that ID; a stale
hash fails integrity validation. Use `action show REQUEST_ID` to inspect an
existing result without rereading source files. An unfinished transaction claim
returns `recovery_pending`; inspect the running producer and saved request before
continuing. The recording commands add no claim reclamation or automatic retry.

Import does not create a session or change a session's selection. To begin
continued work explicitly, save this as `door-session.json`, replacing
`IMPORTED_AUDIO_ASSET_ID` with the output whose `role` is `audio`:

```json
{"schema":"matter-session-create/v1","request_id":"door-session-001","session_id":"door-work","name":"Door recording","asset_id":"IMPORTED_AUDIO_ASSET_ID"}
```

```sh
python -m tools.authoring --workspace /absolute/project/artifacts/audio session create --request door-session.json --json
python -m tools.authoring --workspace /absolute/project/artifacts/audio context show door-work --json
```

After editing, save `door-select.json` with the new audio asset ID and the
session revision observed in context (`1` immediately after creation):

```json
{"schema":"matter-session-select/v1","request_id":"door-select-001","session_id":"door-work","expected_revision":1,"asset_id":"EDITED_AUDIO_ASSET_ID"}
```

```sh
python -m tools.authoring --workspace /absolute/project/artifacts/audio session select --request door-select.json --json
```

An edit alone does not select its output. Selection rejects a stale revision;
read context again before preparing a new selection request.

Creator, source and rights remain supplied declarations. Results explicitly
record `rights_verification: not_performed`,
`publication_eligibility: not_evaluated`, and `listening: not_performed`.
Neither importing nor the shared core's exact-byte export establishes a
distribution grant, approves a public Material Kit, or records listening
acceptance. The existing product-specific publication checks still apply.

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
request. Reuse its ID to replay a completed request. An unfinished transaction
requires inspection; managed-job recovery is an explicit job workflow and does
not reclaim recording-import claims. Read context before editing a selected asset.
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
