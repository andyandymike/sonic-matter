from __future__ import annotations

import hashlib
import json
import struct
import unittest
from pathlib import Path, PurePosixPath


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = REPOSITORY_ROOT / "content-packs" / "ui-page-turn-starninjas-cc0"
MANIFEST_PATH = PACK_ROOT / "asset-rights.json"
REQUIRED_RIGHTS = {
    "source_repo_distribution",
    "material_kit_distribution",
    "game_source_distribution",
    "game_binary_embedding",
    "standalone_baked_audio_distribution",
}


def _ogg_metadata(payload: bytes) -> tuple[int, int, float]:
    offset = 0
    channels = 0
    sample_rate = 0
    last_granule = 0
    while offset + 27 <= len(payload):
        if payload[offset : offset + 4] != b"OggS":
            raise AssertionError(f"invalid Ogg page at byte {offset}")
        granule = struct.unpack_from("<Q", payload, offset + 6)[0]
        if granule != (1 << 64) - 1:
            last_granule = max(last_granule, granule)
        segment_count = payload[offset + 26]
        table_start = offset + 27
        body_start = table_start + segment_count
        body_size = sum(payload[table_start:body_start])
        body = payload[body_start : body_start + body_size]
        marker = body.find(b"\x01vorbis")
        if marker >= 0 and marker + 16 <= len(body):
            channels = body[marker + 11]
            sample_rate = struct.unpack_from("<I", body, marker + 12)[0]
        offset = body_start + body_size
    if offset != len(payload) or channels < 1 or sample_rate < 1:
        raise AssertionError("incomplete or unsupported Ogg Vorbis stream")
    return channels, sample_rate, last_granule * 1000.0 / sample_rate


class UiPageTurnContentPackTests(unittest.TestCase):
    def test_manifest_rights_and_audio_integrity(self) -> None:
        self.assertTrue((PACK_ROOT / "THIRD_PARTY_NOTICES.md").is_file())
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            "sonicmatter-content-pack-rights/v1", manifest["schema"]
        )
        self.assertEqual("approved", manifest["approval_state"])
        self.assertEqual("CC0-1.0", manifest["license"]["spdx"])
        for action in REQUIRED_RIGHTS:
            self.assertEqual("allow", manifest["rights"].get(action))

        assets = manifest["assets"]
        self.assertEqual(10, len(assets))
        self.assertEqual(10, len({asset["asset_id"] for asset in assets}))
        self.assertEqual(10, len({asset["sha256"] for asset in assets}))
        declared_paths: set[str] = set()
        total_size = 0
        for asset in assets:
            relative = PurePosixPath(asset["path"])
            self.assertFalse(relative.is_absolute())
            self.assertNotIn("..", relative.parts)
            self.assertNotIn(asset["path"], declared_paths)
            declared_paths.add(asset["path"])

            path = PACK_ROOT.joinpath(*relative.parts)
            payload = path.read_bytes()
            total_size += len(payload)
            self.assertEqual(asset["size_bytes"], len(payload))
            self.assertEqual(
                asset["sha256"], hashlib.sha256(payload).hexdigest()
            )
            channels, sample_rate, duration_ms = _ogg_metadata(payload)
            self.assertEqual(2, channels)
            self.assertEqual(44100, sample_rate)
            self.assertAlmostEqual(asset["duration_ms"], duration_ms, delta=0.1)
            self.assertGreaterEqual(duration_ms, 580.0)
            self.assertLessEqual(duration_ms, 1150.0)
        self.assertLess(total_size, 256 * 1024)

        packaged_audio = {
            path.relative_to(PACK_ROOT).as_posix()
            for path in (PACK_ROOT / "audio").glob("*.ogg")
        }
        self.assertEqual(declared_paths, packaged_audio)


if __name__ == "__main__":
    unittest.main()
