from __future__ import annotations

import hashlib
import json
import math
import os
import wave
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from .errors import AudioFormatError, ManifestError


PCM24_MAX = (1 << 23) - 1
PCM24_MIN = -(1 << 23)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def write_stable_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stable_json_bytes(value))


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ManifestError(f"JSON root must be an object: {path}")
    return value


def safe_relative_path(root: Path, raw_path: str, *, label: str = "path") -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ManifestError(f"{label} must be a non-empty string")
    normalized = raw_path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts or "." in pure.parts:
        raise ManifestError(f"unsafe {label}: {raw_path!r}")
    if pure.parts and ":" in pure.parts[0]:
        raise ManifestError(f"drive-qualified {label} is forbidden: {raw_path!r}")
    candidate = root.joinpath(*pure.parts)
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as error:
        raise ManifestError(f"{label} escapes root: {raw_path!r}") from error
    return candidate


def portable_relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _decode_pcm(data: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        return (np.frombuffer(data, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    if sample_width == 2:
        return np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768.0
    if sample_width == 3:
        octets = np.frombuffer(data, dtype=np.uint8)
        if octets.size % 3:
            raise AudioFormatError("malformed 24-bit PCM payload")
        triples = octets.reshape(-1, 3).astype(np.int32)
        values = triples[:, 0] | (triples[:, 1] << 8) | (triples[:, 2] << 16)
        values = np.where(values & 0x800000, values - 0x1000000, values)
        return values.astype(np.float64) / 8388608.0
    if sample_width == 4:
        return np.frombuffer(data, dtype="<i4").astype(np.float64) / 2147483648.0
    raise AudioFormatError(f"unsupported PCM sample width: {sample_width} bytes")


def read_wav_mono(path: Path) -> tuple[int, np.ndarray]:
    try:
        with wave.open(os.fspath(path), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise AudioFormatError(f"compressed WAV is unsupported: {path}")
            channels = wav.getnchannels()
            sample_rate = wav.getframerate()
            sample_width = wav.getsampwidth()
            frame_count = wav.getnframes()
            payload = wav.readframes(frame_count)
    except (OSError, wave.Error) as error:
        raise AudioFormatError(f"cannot read WAV {path}: {error}") from error
    if channels < 1 or channels > 8:
        raise AudioFormatError(f"unsupported channel count {channels}: {path}")
    if not 8_000 <= sample_rate <= 192_000:
        raise AudioFormatError(f"unsupported sample rate {sample_rate}: {path}")
    decoded = _decode_pcm(payload, sample_width)
    if decoded.size != frame_count * channels:
        raise AudioFormatError(f"truncated PCM data: {path}")
    mono = decoded.reshape(-1, channels).mean(axis=1, dtype=np.float64)
    if mono.size == 0 or not np.all(np.isfinite(mono)):
        raise AudioFormatError(f"empty or non-finite audio: {path}")
    return sample_rate, mono


def write_wav_pcm24(path: Path, sample_rate: int, samples: np.ndarray) -> None:
    signal = np.asarray(samples, dtype=np.float64).reshape(-1)
    if signal.size == 0:
        raise AudioFormatError("refusing to write an empty WAV")
    if not np.all(np.isfinite(signal)):
        raise AudioFormatError("refusing to write NaN or infinite samples")
    peak = float(np.max(np.abs(signal)))
    if peak > 1.0 + 1e-12:
        raise AudioFormatError(
            f"refusing to clip output silently (peak={peak:.6f}); calibrate the recipe"
        )
    clipped_for_quantization = np.clip(signal, -1.0, 1.0)
    integers = np.rint(clipped_for_quantization * PCM24_MAX).astype(np.int64)
    integers = np.clip(integers, PCM24_MIN, PCM24_MAX)
    unsigned = (integers & 0xFFFFFF).astype(np.uint32)
    payload = np.empty((unsigned.size, 3), dtype=np.uint8)
    payload[:, 0] = unsigned & 0xFF
    payload[:, 1] = (unsigned >> 8) & 0xFF
    payload[:, 2] = (unsigned >> 16) & 0xFF
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with wave.open(os.fspath(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(3)
            wav.setframerate(sample_rate)
            wav.writeframes(payload.tobytes())
    except (OSError, wave.Error) as error:
        raise AudioFormatError(f"cannot write WAV {path}: {error}") from error


def db_to_amplitude(db: float | np.ndarray) -> float | np.ndarray:
    return np.power(10.0, np.asarray(db) / 20.0)


def amplitude_to_db(amplitude: float | np.ndarray, floor_db: float = -120.0) -> float | np.ndarray:
    values = np.maximum(np.asarray(amplitude, dtype=np.float64), math.pow(10.0, floor_db / 20.0))
    return 20.0 * np.log10(values)
