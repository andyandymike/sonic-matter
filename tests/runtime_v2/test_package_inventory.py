from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile

from tools import package_rc0
from tools import verify_clean_install


def record(path: str, payload: bytes) -> dict[str, object]:
    return {
        "path": path,
        "sha256": package_rc0.sha256_bytes(payload),
        "size": len(payload),
    }


class ExactPackageInventoryTests(unittest.TestCase):
    def test_clean_install_godot_resolution_fails_closed(self) -> None:
        missing_path = Path(tempfile.gettempdir()) / "missing-sonic-godot.exe"
        environment_before = os.environ.get("GODOT")
        os.environ["GODOT"] = sys.executable
        try:
            with self.assertRaisesRegex(package_rc0.AuditError, "does not resolve"):
                verify_clean_install.resolve_godot_executable(str(missing_path))
            with mock.patch("shutil.which", return_value=None):
                with self.assertRaisesRegex(package_rc0.AuditError, "was not found"):
                    verify_clean_install.resolve_godot_executable("godot4")
        finally:
            if environment_before is None:
                os.environ.pop("GODOT", None)
            else:
                os.environ["GODOT"] = environment_before

    def test_exact_records_pass(self) -> None:
        records = [record("a.txt", b"a"), record("b.txt", b"bb")]
        package_rc0.assert_exact_inventory("fixture", records, records.copy())

    def test_missing_extra_and_changed_fail_closed(self) -> None:
        expected = [record("a.txt", b"a"), record("b.txt", b"b")]
        cases = {
            "missing": expected[:1],
            "extra": expected + [record("c.txt", b"c")],
            "changed": [expected[0], record("b.txt", b"changed")],
        }
        for label, actual in cases.items():
            with self.subTest(label=label):
                with self.assertRaisesRegex(package_rc0.AuditError, label):
                    package_rc0.assert_exact_inventory(label, expected, actual)

    def test_current_collections_match_independent_oracles(self) -> None:
        for kind in ("addon", "demo"):
            with self.subTest(kind=kind):
                files = package_rc0.collect_package(kind)
                package_rc0.validate_inventory_oracle(kind, files)

    def test_package_collections_exclude_private_and_optional_content(self) -> None:
        forbidden = ("spec/", "planning-private/", ".local/", "content-packs/")
        for kind in ("addon", "demo"):
            with self.subTest(kind=kind):
                paths = package_rc0.collect_package(kind)
                leaked = [path for path in paths if path.startswith(forbidden)]
                self.assertEqual([], leaked)

    def test_windows_export_oracles_are_synchronized(self) -> None:
        compact_path = Path("examples/gate_a_3d/export_inventory_v1.json")
        golden_path = Path("tests/runtime_v2/golden/windows_export_inventory_v1.json")
        compact_bytes = compact_path.read_bytes()
        compact = json.loads(compact_bytes)
        golden = json.loads(golden_path.read_text(encoding="utf-8"))

        self.assertEqual("0.1.0-rc1", compact["release"])
        self.assertEqual(compact["release"], golden["release"])
        self.assertEqual(compact["records"], golden["records"])
        self.assertEqual(
            hashlib.sha256(compact_bytes).hexdigest(),
            golden["compact_oracle_sha256"],
        )

        canonical_records = json.dumps(
            compact["records"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        inventory_sha256 = hashlib.sha256(canonical_records).hexdigest()
        self.assertEqual(inventory_sha256, compact["inventory_sha256"])
        self.assertEqual(inventory_sha256, golden["inventory_sha256"])

    def test_archive_verify_rejects_self_consistent_content_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = package_rc0.write_archive("addon", Path(temporary))
            with zipfile.ZipFile(archive_path, "r") as source:
                members = {name: source.read(name) for name in source.namelist()}
            root = PurePosixPath(next(iter(members))).parts[0]
            target_name = f"{root}/docs/gate-a-contract.md"
            members[target_name] += b"\nself-consistent tamper\n"
            manifest_name = f"{root}/PACKAGE_MANIFEST.json"
            manifest = json.loads(members[manifest_name])
            for record in manifest["files"]:
                if record["path"] == "docs/gate-a-contract.md":
                    record["size"] = len(members[target_name])
                    record["sha256"] = package_rc0.sha256_bytes(members[target_name])
            members[manifest_name] = (
                json.dumps(manifest, indent=2, sort_keys=True) + "\n"
            ).encode("utf-8")
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as target:
                for name, payload in members.items():
                    target.writestr(name, payload)
            with self.assertRaisesRegex(package_rc0.AuditError, "exact inventory drift"):
                package_rc0.verify_archive(archive_path)

    def test_archive_verify_rejects_duplicate_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = package_rc0.write_archive("addon", Path(temporary))
            with zipfile.ZipFile(archive_path, "a") as archive:
                first_name = archive.namelist()[0]
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    archive.writestr(first_name, archive.read(first_name))
            with self.assertRaisesRegex(package_rc0.AuditError, "duplicate archive member"):
                package_rc0.verify_archive(archive_path)


if __name__ == "__main__":
    unittest.main()
