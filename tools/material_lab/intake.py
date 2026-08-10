from __future__ import annotations

import hashlib
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import ManifestError
from .io import sha256_file


SCHEMA = "sonic-material-quarantine/v1"
MAX_MEMBERS = 2_000
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 1_000.0


def _safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute() or ".." in pure.parts:
        raise ManifestError(f"unsafe archive member path: {name!r}")
    if pure.parts and ":" in pure.parts[0]:
        raise ManifestError(f"drive-qualified archive member path: {name!r}")
    return pure.as_posix()


def inventory_zip(
    archive_path: Path,
    *,
    source_url: str,
    license_claim: str,
    acquired_at: str,
    evidence_paths: list[Path] | None = None,
    review_notes: list[str] | None = None,
) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    if not archive_path.is_file() or archive_path.is_symlink():
        raise ManifestError(f"missing or unsafe ZIP archive: {archive_path}")
    members: list[dict[str, Any]] = []
    total = 0
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            infos = archive.infolist()
            if len(infos) > MAX_MEMBERS:
                raise ManifestError(f"archive has {len(infos)} members; limit is {MAX_MEMBERS}")
            for info in infos:
                name = _safe_member_name(info.filename)
                if name in seen:
                    raise ManifestError(f"duplicate archive member path: {name}")
                seen.add(name)
                unix_mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(unix_mode)
                if kind in {stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK}:
                    raise ManifestError(f"archive contains unsafe special member: {name}")
                if info.is_dir():
                    continue
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ManifestError(f"archive member too large: {name}")
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    raise ManifestError("archive expands beyond the total size limit")
                if info.file_size > 1024 * 1024:
                    ratio = info.file_size / max(1, info.compress_size)
                    if ratio > MAX_COMPRESSION_RATIO:
                        raise ManifestError(
                            f"archive member compression ratio is suspicious ({ratio:.1f}): {name}"
                        )
                digest = hashlib.sha256()
                read_bytes = 0
                with archive.open(info, "r") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        read_bytes += len(chunk)
                        if read_bytes > info.file_size or read_bytes > MAX_MEMBER_BYTES:
                            raise ManifestError(f"archive member exceeded declared size: {name}")
                        digest.update(chunk)
                if read_bytes != info.file_size:
                    raise ManifestError(f"archive member size mismatch: {name}")
                members.append(
                    {
                        "path": name,
                        "bytes": info.file_size,
                        "compressed_bytes": info.compress_size,
                        "crc32": f"{info.CRC:08x}",
                        "sha256": digest.hexdigest(),
                    }
                )
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise ManifestError(f"cannot safely inventory ZIP {archive_path}: {error}") from error
    retained_evidence = []
    for evidence_path in evidence_paths or []:
        resolved = evidence_path.resolve()
        if not resolved.is_file() or resolved.is_symlink():
            raise ManifestError(f"missing or unsafe retained evidence: {resolved}")
        retained_evidence.append(
            {
                "filename": resolved.name,
                "bytes": resolved.stat().st_size,
                "sha256": sha256_file(resolved),
            }
        )
    return {
        "schema": SCHEMA,
        "approval_state": "quarantine",
        "archive": {
            "filename": archive_path.name,
            "bytes": archive_path.stat().st_size,
            "sha256": sha256_file(archive_path),
        },
        "source": {
            "canonical_url": source_url,
            "license_claim": license_claim,
            "acquired_at": acquired_at,
            "retained_evidence": sorted(
                retained_evidence, key=lambda item: (item["filename"], item["sha256"])
            ),
            "review_notes": [note.strip() for note in review_notes or [] if note.strip()],
        },
        "member_count": len(members),
        "expanded_bytes": total,
        "members": sorted(members, key=lambda item: item["path"]),
        "default_rights": {
            "status": "unknown",
            "note": "Inventory is evidence, not approval. Promote each selected member through rights review.",
        },
    }
