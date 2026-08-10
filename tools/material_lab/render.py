from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .analysis import MAX_MODES, MAX_ROUGHNESS_BANDS, MIN_MODES, MIN_ROUGHNESS_BANDS, RECIPE_SCHEMA
from .errors import AudioFormatError, ManifestError
from .io import (
    db_to_amplitude,
    load_json,
    read_wav_mono,
    safe_relative_path,
    sha256_file,
    write_stable_json,
    write_wav_pcm24,
)


ARM_NAMES = (
    "sample_pool",
    "transient_only",
    "hybrid_minus_transient",
    "hybrid_minus_body_resonator",
    "hybrid_minus_roughness",
    "hybrid_full",
)
RENDER_SCHEMA = "sonic-impact-render/v1"
MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1


@dataclass(frozen=True)
class RenderOptions:
    seed: int = 1
    variant: int = 0
    intensity: float = 0.7
    size: float = 1.0
    damping: float = 0.0
    arms: tuple[str, ...] = ARM_NAMES

    def validate(self) -> None:
        if self.seed < 0 or self.seed > MASK64:
            raise ManifestError("seed must be an unsigned 64-bit integer")
        if self.variant < 0:
            raise ManifestError("variant must be non-negative")
        if not 0.0 <= self.intensity <= 1.0:
            raise ManifestError("intensity must be in [0, 1]")
        if not 0.25 <= self.size <= 4.0:
            raise ManifestError("size must be in [0.25, 4]")
        if not 0.0 <= self.damping <= 1.0:
            raise ManifestError("damping must be in [0, 1]")
        if not self.arms:
            raise ManifestError("at least one render arm is required")
        unknown = sorted(set(self.arms) - set(ARM_NAMES))
        if unknown:
            raise ManifestError(f"unknown render arms: {unknown}")
        if len(set(self.arms)) != len(self.arms):
            raise ManifestError("render arms must not contain duplicates")


class _PCG32:
    def __init__(self, seed: int, sequence: int) -> None:
        self.state = 0
        self.increment = ((sequence & MASK64) << 1 | 1) & MASK64
        self.next_uint32()
        self.state = (self.state + (seed & MASK64)) & MASK64
        self.next_uint32()

    def next_uint32(self) -> int:
        old_state = self.state
        self.state = (old_state * 6364136223846793005 + self.increment) & MASK64
        xorshifted = (((old_state >> 18) ^ old_state) >> 27) & MASK32
        rotation = (old_state >> 59) & 31
        return (
            (xorshifted >> rotation)
            | ((xorshifted << ((-rotation) & 31)) & MASK32)
        ) & MASK32

    def uniform_signed(self) -> float:
        return (self.next_uint32() / 2147483648.0) - 1.0


def _domain_seed(base_seed: int, recipe_sha: str, domain: str) -> tuple[int, int]:
    payload = f"{base_seed}:{recipe_sha}:{domain}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "little"), int.from_bytes(digest[8:16], "little")


def _noise(frame_count: int, seed: int, sequence: int) -> np.ndarray:
    generator = _PCG32(seed, sequence)
    result = np.empty(frame_count, dtype=np.float64)
    for index in range(frame_count):
        # Six uniforms are a bounded, deterministic approximation of Gaussian noise.
        result[index] = sum(generator.uniform_signed() for _ in range(6)) / 2.0
    return result


def _require_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ManifestError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ManifestError(f"{label} must be finite")
    return result


def _validate_and_load_audio(
    root: Path, entries: Any, sample_rate: int, label: str
) -> list[np.ndarray]:
    if not isinstance(entries, list) or not entries:
        raise ManifestError(f"{label} must be a non-empty list")
    signals = []
    for index, entry in enumerate(entries):
        item_label = f"{label}[{index}]"
        if not isinstance(entry, dict):
            raise ManifestError(f"{item_label} must be an object")
        raw_path = entry.get("path")
        if not isinstance(raw_path, str):
            raise ManifestError(f"{item_label}.path must be a string")
        path = safe_relative_path(root, raw_path, label=f"{item_label}.path")
        if not path.is_file() or path.is_symlink():
            raise ManifestError(f"missing or unsafe recipe audio: {raw_path}")
        expected_sha = entry.get("sha256")
        if not isinstance(expected_sha, str) or sha256_file(path) != expected_sha:
            raise ManifestError(f"recipe audio hash mismatch: {raw_path}")
        rate, signal = read_wav_mono(path)
        if rate != sample_rate:
            raise AudioFormatError(f"recipe audio sample-rate mismatch: {raw_path}")
        signals.append(signal)
    return signals


def _validate_recipe(recipe_path: Path) -> tuple[dict[str, Any], list[np.ndarray], list[np.ndarray]]:
    recipe = load_json(recipe_path)
    if recipe.get("schema") != RECIPE_SCHEMA:
        raise ManifestError(f"recipe schema must be {RECIPE_SCHEMA!r}")
    sample_rate = recipe.get("sample_rate")
    if not isinstance(sample_rate, int) or not 8_000 <= sample_rate <= 192_000:
        raise ManifestError("recipe sample_rate is outside [8000, 192000]")
    root = recipe_path.parent
    samples = _validate_and_load_audio(root, recipe.get("sample_pool"), sample_rate, "sample_pool")
    transients = _validate_and_load_audio(root, recipe.get("transients"), sample_rate, "transients")
    if len(samples) != len(transients):
        raise ManifestError("sample_pool and transients must have equal variant counts")
    modal = recipe.get("modal_body")
    if not isinstance(modal, dict):
        raise ManifestError("modal_body must be an object")
    modes = modal.get("modes")
    if not isinstance(modes, list) or not MIN_MODES <= len(modes) <= MAX_MODES:
        raise ManifestError(f"recipe must contain {MIN_MODES} to {MAX_MODES} modes")
    frequency_limit = min(18_000.0, 0.45 * sample_rate)
    for index, mode in enumerate(modes):
        if not isinstance(mode, dict):
            raise ManifestError(f"modal_body.modes[{index}] must be an object")
        frequency = _require_number(mode.get("frequency_hz"), f"modes[{index}].frequency_hz")
        t60 = _require_number(mode.get("t60_ms"), f"modes[{index}].t60_ms")
        gain = _require_number(mode.get("gain"), f"modes[{index}].gain")
        if not 40.0 <= frequency <= frequency_limit:
            raise ManifestError(f"mode frequency outside safety limits: {frequency}")
        if not 20.0 <= t60 <= 2000.0:
            raise ManifestError(f"mode T60 outside safety limits: {t60}")
        if not 0.0 <= gain <= 1.0:
            raise ManifestError(f"mode gain outside [0, 1]: {gain}")
    pulse = modal.get("excitation_pulse")
    if not isinstance(pulse, list) or not 1 <= len(pulse) <= 16:
        raise ManifestError("excitation_pulse must contain 1 to 16 values")
    for index, value in enumerate(pulse):
        _require_number(value, f"excitation_pulse[{index}]")
    roughness = recipe.get("roughness")
    if not isinstance(roughness, dict):
        raise ManifestError("roughness must be an object")
    bands = roughness.get("bands")
    if not isinstance(bands, list) or not MIN_ROUGHNESS_BANDS <= len(bands) <= MAX_ROUGHNESS_BANDS:
        raise ManifestError(
            f"recipe must contain {MIN_ROUGHNESS_BANDS} to {MAX_ROUGHNESS_BANDS} roughness bands"
        )
    for index, band in enumerate(bands):
        if not isinstance(band, dict):
            raise ManifestError(f"roughness.bands[{index}] must be an object")
        center = _require_number(band.get("center_hz"), f"bands[{index}].center_hz")
        q = _require_number(band.get("q"), f"bands[{index}].q")
        if not 40.0 <= center <= frequency_limit or not 0.3 <= q <= 8.0:
            raise ManifestError(f"roughness band {index} violates frequency/Q safety")
        envelope = band.get("envelope")
        if not isinstance(envelope, list) or not 2 <= len(envelope) <= 32:
            raise ManifestError(f"roughness band {index} has an invalid envelope")
        previous_time = -1.0
        for knot_index, knot in enumerate(envelope):
            if not isinstance(knot, dict):
                raise ManifestError(f"band {index} envelope knot {knot_index} must be an object")
            time_ms = _require_number(knot.get("time_ms"), "envelope.time_ms")
            level_db = _require_number(knot.get("level_db"), "envelope.level_db")
            if not previous_time < time_ms <= 250.0 or not -96.0 <= level_db <= 12.0:
                raise ManifestError(f"band {index} envelope knot violates safety limits")
            previous_time = time_ms
    render = recipe.get("render")
    if not isinstance(render, dict):
        raise ManifestError("render must be an object")
    duration_ms = _require_number(render.get("duration_ms"), "render.duration_ms")
    if not 1.0 <= duration_ms <= 2000.0:
        raise ManifestError("render.duration_ms must be in [1, 2000]")
    mix = recipe.get("mix")
    if not isinstance(mix, dict):
        raise ManifestError("mix must be an object")
    for key in (
        "transient_gain_db",
        "body_gain_db",
        "roughness_gain_db",
        "master_gain_db",
    ):
        value = _require_number(mix.get(key), f"mix.{key}")
        if not -96.0 <= value <= 12.0:
            raise ManifestError(f"mix.{key} is outside [-96, 12] dB")
    safety = recipe.get("safety")
    if not isinstance(safety, dict):
        raise ManifestError("safety must be an object")
    peak_limit = _require_number(safety.get("peak_limit"), "safety.peak_limit")
    if not 0.1 <= peak_limit <= 1.0:
        raise ManifestError("safety.peak_limit must be in [0.1, 1]")
    return recipe, samples, transients


def _pad_or_trim(signal: np.ndarray, frame_count: int) -> np.ndarray:
    output = np.zeros(frame_count, dtype=np.float64)
    output[: min(frame_count, len(signal))] = signal[:frame_count]
    return output


def _modal_body(
    recipe: dict[str, Any], options: RenderOptions, frame_count: int
) -> np.ndarray:
    sample_rate = int(recipe["sample_rate"])
    pulse = np.asarray(recipe["modal_body"]["excitation_pulse"], dtype=np.float64)
    excitation = np.zeros(frame_count, dtype=np.float64)
    excitation[: min(frame_count, len(pulse))] = pulse[:frame_count]
    output = np.zeros(frame_count, dtype=np.float64)
    intensity_gain = math.sqrt(options.intensity)
    for mode in recipe["modal_body"]["modes"]:
        frequency = float(mode["frequency_hz"]) / math.sqrt(options.size)
        frequency = float(np.clip(frequency, 40.0, min(18_000.0, 0.45 * sample_rate)))
        t60_ms = float(mode["t60_ms"]) * (1.0 - 0.8 * options.damping)
        t60_s = max(0.02, t60_ms / 1000.0)
        radius = math.exp(math.log(0.001) / (t60_s * sample_rate))
        coefficient = 2.0 * radius * math.cos(2.0 * math.pi * frequency / sample_rate)
        radius_squared = radius * radius
        gain = float(mode["gain"]) * intensity_gain
        previous_1 = 0.0
        previous_2 = 0.0
        for frame in range(frame_count):
            value = coefficient * previous_1 - radius_squared * previous_2 + gain * excitation[frame]
            output[frame] += value
            previous_2 = previous_1
            previous_1 = value
    return output


def _bandpass(signal: np.ndarray, sample_rate: int, center_hz: float, q: float) -> np.ndarray:
    omega = 2.0 * math.pi * center_hz / sample_rate
    alpha = math.sin(omega) / (2.0 * q)
    a0 = 1.0 + alpha
    b0 = alpha / a0
    b1 = 0.0
    b2 = -alpha / a0
    a1 = -2.0 * math.cos(omega) / a0
    a2 = (1.0 - alpha) / a0
    output = np.empty_like(signal)
    x1 = x2 = y1 = y2 = 0.0
    for index, x0 in enumerate(signal):
        y0 = b0 * x0 + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        output[index] = y0
        x2, x1 = x1, float(x0)
        y2, y1 = y1, y0
    return output


def _roughness(
    recipe: dict[str, Any], options: RenderOptions, frame_count: int, recipe_sha: str
) -> np.ndarray:
    sample_rate = int(recipe["sample_rate"])
    namespace = str(recipe["roughness"].get("seed_namespace", "roughness"))
    seed, sequence = _domain_seed(options.seed, recipe_sha, f"{namespace}:{options.variant}")
    noise = _noise(frame_count, seed, sequence)
    output = np.zeros(frame_count, dtype=np.float64)
    frame_times_ms = np.arange(frame_count, dtype=np.float64) * 1000.0 / sample_rate
    for band in recipe["roughness"]["bands"]:
        filtered = _bandpass(
            noise,
            sample_rate,
            float(band["center_hz"]),
            float(band["q"]),
        )
        knot_times = np.asarray([float(knot["time_ms"]) for knot in band["envelope"]])
        knot_levels = np.asarray([float(knot["level_db"]) for knot in band["envelope"]])
        levels = np.interp(frame_times_ms, knot_times, knot_levels, left=knot_levels[0], right=-96.0)
        output += filtered * np.asarray(db_to_amplitude(levels))
    return output * math.sqrt(options.intensity)


def render_recipe(
    recipe_path: Path,
    output_dir: Path,
    *,
    options: RenderOptions | None = None,
) -> dict[str, Any]:
    options = options or RenderOptions()
    options.validate()
    recipe_path = recipe_path.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ManifestError(f"output directory must be empty: {output_dir}")
    recipe, samples, transients = _validate_recipe(recipe_path)
    recipe_sha = sha256_file(recipe_path)
    sample_rate = int(recipe["sample_rate"])
    duration_ms = float(recipe["render"]["duration_ms"])
    frame_count = max(1, int(round(duration_ms * sample_rate / 1000.0)))
    variant = options.variant % len(samples)
    intensity_gain = math.sqrt(options.intensity)
    sample_component = _pad_or_trim(samples[variant], frame_count) * intensity_gain
    transient_component = _pad_or_trim(transients[variant], frame_count) * intensity_gain
    body_component = _modal_body(recipe, options, frame_count)
    roughness_component = _roughness(recipe, options, frame_count, recipe_sha)
    mix = recipe["mix"]
    transient_component *= float(db_to_amplitude(float(mix["transient_gain_db"])))
    body_component *= float(db_to_amplitude(float(mix["body_gain_db"])))
    roughness_component *= float(db_to_amplitude(float(mix["roughness_gain_db"])))
    master = float(db_to_amplitude(float(mix["master_gain_db"])))
    components = {
        "sample_pool": sample_component,
        "transient_only": transient_component,
        "hybrid_minus_transient": body_component + roughness_component,
        "hybrid_minus_body_resonator": transient_component + roughness_component,
        "hybrid_minus_roughness": transient_component + body_component,
        "hybrid_full": transient_component + body_component + roughness_component,
    }
    peak_limit = float(recipe["safety"]["peak_limit"])
    prepared_outputs = []
    for arm in options.arms:
        signal = np.asarray(components[arm] * master, dtype=np.float64)
        peak = float(np.max(np.abs(signal)))
        if peak > peak_limit + 1e-12:
            raise AudioFormatError(
                f"{arm} exceeds recipe peak_limit ({peak:.6f} > {peak_limit:.6f}); no limiter was applied"
            )
        prepared_outputs.append((arm, signal, peak))
    # Validate every requested arm before creating output.  A safety failure
    # therefore cannot strand a half-written render directory.
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered = []
    for arm, signal, peak in prepared_outputs:
        output_path = output_dir / f"{arm}.wav"
        write_wav_pcm24(output_path, sample_rate, signal)
        rendered.append(
            {
                "arm": arm,
                "path": output_path.name,
                "sha256": sha256_file(output_path),
                "frames": frame_count,
                "peak": round(peak, 9),
                "rms": round(float(np.sqrt(np.mean(np.square(signal)))), 9),
            }
        )
    manifest = {
        "schema": RENDER_SCHEMA,
        "recipe_sha256": recipe_sha,
        "renderer": "modal-residual-pcm24/0.1",
        "sample_rate": sample_rate,
        "options": {
            "seed": options.seed,
            "variant": options.variant,
            "resolved_variant": variant,
            "intensity": options.intensity,
            "size": options.size,
            "damping": options.damping,
            "arms": list(options.arms),
        },
        "rendered": rendered,
        "safety": {
            "limiter_applied": False,
            "silent_clipping_allowed": False,
        },
    }
    manifest_path = output_dir / "render-manifest.json"
    write_stable_json(manifest_path, manifest)
    return {
        "manifest": manifest_path,
        "rendered": tuple(output_dir / item["path"] for item in rendered),
        "recipe_sha256": recipe_sha,
    }
